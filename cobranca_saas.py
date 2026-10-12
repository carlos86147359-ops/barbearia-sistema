"""Cobrança Grupo Havo: homologação Asaas, isolada das mensalidades e do acesso real.

Produção está deliberadamente bloqueada até a homologação financeira completa.
Nenhum cartão, chave de API ou corpo bruto de webhook é persistido.
"""
import asyncio
import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse

DDL = {
    'saas_contratos': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,ambiente TEXT NOT NULL,usuario_id TEXT NOT NULL,valor_centavos INTEGER NOT NULL,checkout_id TEXT,assinatura_id TEXT,cliente_id TEXT,status TEXT NOT NULL,proximo_vencimento TEXT,pago_ate TEXT,criado_em BIGINT NOT NULL,atualizado_em BIGINT NOT NULL,erro TEXT',
    'saas_cobrancas': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,contrato_id TEXT NOT NULL,ambiente TEXT NOT NULL,provedor_id TEXT NOT NULL,valor_centavos INTEGER NOT NULL,status TEXT NOT NULL,vencimento TEXT NOT NULL,pago_em TEXT,periodo_fim TEXT NOT NULL,fatura_url TEXT,atualizado_em BIGINT NOT NULL,UNIQUE(ambiente,provedor_id)',
    'saas_webhooks': 'id TEXT PRIMARY KEY,ambiente TEXT NOT NULL,tipo TEXT NOT NULL,recurso_id TEXT NOT NULL,referencia TEXT,status TEXT NOT NULL,tentativas INTEGER NOT NULL,proxima_tentativa BIGINT NOT NULL,criado_em BIGINT NOT NULL,processado_em BIGINT,erro TEXT',
    'saas_auditoria': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,contrato_id TEXT NOT NULL,usuario_id TEXT NOT NULL,acao TEXT NOT NULL,criado_em BIGINT NOT NULL',
}
TABLES = {name: [p.strip().split()[0] for p in ddl.split(',UNIQUE(', 1)[0].split(',')] for name, ddl in DDL.items()}
INDEXES = [
    'CREATE UNIQUE INDEX IF NOT EXISTS saas_checkout_unico ON saas_contratos(ambiente,checkout_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS saas_assinatura_unica ON saas_contratos(ambiente,assinatura_id)',
    "CREATE UNIQUE INDEX IF NOT EXISTS saas_contratacao_aberta ON saas_contratos(loja_id,ambiente) WHERE status NOT IN ('cancelada','expirada')",
    'CREATE INDEX IF NOT EXISTS saas_fila ON saas_webhooks(status,proxima_tentativa)',
    'CREATE INDEX IF NOT EXISTS saas_pagamentos_loja ON saas_cobrancas(loja_id,ambiente,vencimento)',
]
PAID = {'RECEIVED', 'CONFIRMED', 'RECEIVED_IN_CASH'}
EVENTS = {'CHECKOUT_CREATED','CHECKOUT_PAID','CHECKOUT_CANCELED','CHECKOUT_EXPIRED',
          'SUBSCRIPTION_CREATED','SUBSCRIPTION_UPDATED','SUBSCRIPTION_INACTIVATED','SUBSCRIPTION_DELETED',
          'PAYMENT_CREATED','PAYMENT_UPDATED','PAYMENT_CONFIRMED','PAYMENT_RECEIVED','PAYMENT_OVERDUE',
          'PAYMENT_CREDIT_CARD_CAPTURE_REFUSED','PAYMENT_DELETED','PAYMENT_RESTORED','PAYMENT_REFUNDED',
          'PAYMENT_REFUND_IN_PROGRESS','PAYMENT_CHARGEBACK_REQUESTED','PAYMENT_CHARGEBACK_DISPUTE',
          'PAYMENT_AWAITING_CHARGEBACK_REVERSAL'}


def enabled():
    return (os.environ.get('ASAAS_ENV') == 'sandbox' and bool(os.environ.get('ASAAS_API_KEY'))
            and len(os.environ.get('ASAAS_WEBHOOK_TOKEN','')) >= 32)


def cents(value):
    try:
        n = Decimal(str(value)) * 100
        if not n.is_finite() or n != n.to_integral_value() or n < 0:
            raise ValueError()
        return int(n)
    except (InvalidOperation, ValueError):
        raise ValueError('Valor financeiro inválido.')


def month_end(day):
    d = date.fromisoformat(day)
    month = d.month % 12 + 1
    year = d.year + (d.month == 12)
    return d.replace(year=year,month=month,day=min(d.day,calendar.monthrange(year,month)[1])).isoformat()


def safe_invoice(url):
    if not isinstance(url,str): return None
    p = urllib.parse.urlparse(url)
    if p.scheme == 'https' and p.hostname == 'sandbox.asaas.com' and not p.username and p.port in (None,443):
        return url
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def api(method,path,body=None):
    if not enabled(): raise HTTPException(503,'Integração Sandbox não configurada. Cobranças reais permanecem desabilitadas.')
    if not path.startswith('/') or '..' in path: raise ValueError('Rota inválida.')
    req = urllib.request.Request('https://api-sandbox.asaas.com/v3'+path,
        data=json.dumps(body).encode() if body is not None else None,method=method,
        headers={'access_token':os.environ['ASAAS_API_KEY'],'Content-Type':'application/json','User-Agent':'GrupoHavo/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=65) as response:
            return json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as exc:
        # Nunca devolver mensagens do provedor: podem conter dados pessoais.
        if method == 'GET' and exc.code == 404: return {'deleted':True}
        raise HTTPException(502,'O Asaas não concluiu a operação. Consulte o estado antes de tentar novamente.') from None
    except (OSError,ValueError):
        raise HTTPException(502,'Sem confirmação do Asaas. A tentativa foi preservada para evitar duplicidade.') from None


def ident(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_&.-]{1,180}',value):
        raise ValueError('Identificador inválido.')
    return value


def instalar(app,c):
    banco = c['banco']
    with banco() as db:
        for name,ddl in DDL.items(): db.execute('CREATE TABLE IF NOT EXISTS '+name+' ('+ddl+')')
        for sql in INDEXES: db.execute(sql)

    def lock(db):
        if c['DATABASE_URL']: db.execute('SELECT pg_advisory_xact_lock(?)',(7821615,))
        else: db.execute('BEGIN IMMEDIATE')

    def sandbox_allowed(user):
        emails = {e.strip().lower() for e in os.environ.get('ASAAS_SANDBOX_TEST_EMAILS','').split(',') if e.strip()}
        return c['eh_admin'](user) or str(user['email']).lower() in emails

    def owner(request,db,change=False):
        user = c['dono'](request,db,change)
        # Sandbox nunca é oferecido aos clientes pagantes da plataforma.
        if not sandbox_allowed(user): raise HTTPException(403,'Conta não autorizada para homologação Sandbox.')
        if not enabled(): raise HTTPException(503,'Integração Sandbox ainda indisponível.')
        return user

    def audit(db,row,user,action):
        db.execute('INSERT INTO saas_auditoria(id,loja_id,contrato_id,usuario_id,acao,criado_em) VALUES(?,?,?,?,?,?)',
                   (secrets.token_hex(16),row['loja_id'],row['id'],user,action,int(time.time())))

    def contract_view(row):
        out = {k:row[k] for k in ('id','valor_centavos','status','proximo_vencimento','pago_ate','erro','criado_em')}
        if row['checkout_id'] and row['status'] == 'checkout':
            out['checkout_url'] = 'https://sandbox.asaas.com/checkoutSession/show?id='+urllib.parse.quote(row['checkout_id'])
        return out

    @app.get('/cobranca-saas.js')
    def script(): return FileResponse(c['ROOT']/'cobranca-saas.js',media_type='application/javascript')

    @app.get('/api/saas/assinatura')
    def summary(request:Request):
        with banco() as db:
            user = c['dono'](request,db)
            if not enabled() or not sandbox_allowed(user): return {'disponivel':False}
            rows = db.execute('SELECT * FROM saas_contratos WHERE loja_id=? AND ambiente=? ORDER BY criado_em DESC,id DESC',
                              (user['loja_id'],'sandbox')).fetchall()
            payments = db.execute('SELECT valor_centavos,status,vencimento,pago_em,fatura_url FROM saas_cobrancas WHERE loja_id=? AND ambiente=? ORDER BY vencimento DESC,id DESC LIMIT 100',
                                  (user['loja_id'],'sandbox')).fetchall()
        return {'disponivel':True,'ambiente':'sandbox','valor_centavos':9000,
                'contratos':[contract_view(r) for r in rows], 'pagamentos':[dict(r) for r in payments]}

    @app.post('/api/saas/checkout')
    def checkout(request:Request):
        now = int(time.time())
        base = os.environ.get('PUBLIC_BASE_URL','').rstrip('/')
        p = urllib.parse.urlparse(base)
        if p.scheme != 'https' or not p.hostname or p.query or p.fragment or p.username:
            raise HTTPException(503,'Configure PUBLIC_BASE_URL com a URL HTTPS do aplicativo.')
        with banco() as db:
            user = owner(request,db,True)
            c['limitar'](request,'asaas-checkout',8,3600)
            lock(db)
            old = db.execute("SELECT * FROM saas_contratos WHERE loja_id=? AND ambiente='sandbox' AND status NOT IN ('cancelada','expirada')",(user['loja_id'],)).fetchone()
            if old:
                if old['status'] == 'checkout' and old['checkout_id']: return contract_view(old)
                raise HTTPException(409,'Já existe uma contratação ou tentativa em conferência. Sincronize antes de criar outra.')
            cid = secrets.token_hex(24)
            db.execute('INSERT INTO saas_contratos(id,loja_id,ambiente,usuario_id,valor_centavos,status,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?)',
                       (cid,user['loja_id'],'sandbox',user['id'],9000,'criando',now,now))
        # A tentativa é confirmada no banco ANTES da chamada externa.
        # Timeout nunca provoca uma segunda criação automática.
        try:
            result = api('POST','/checkouts',{'externalReference':'havo:'+cid,
                'billingTypes':['CREDIT_CARD'],'chargeTypes':['RECURRENT'],'minutesToExpire':60,
                'callback':{k:base+'/painel#plano' for k in ('successUrl','cancelUrl','expiredUrl')},
                'items':[{'name':'Grupo Havo - Plano mensal (TESTE)','description':'Homologação Sandbox, sem cobrança real','quantity':1,'value':90}],
                'subscription':{'cycle':'MONTHLY','nextDueDate':datetime.now(c['BRASIL']).strftime('%Y-%m-%d %H:%M:%S')}})
            checkout_id = ident(result.get('id'))
        except (HTTPException,ValueError):
            with banco() as db:
                db.execute("UPDATE saas_contratos SET status=CASE WHEN status='criando' THEN 'incerta' ELSE status END,erro=?,atualizado_em=? WHERE id=?",
                           ('Tentativa sem confirmação. Aguarde o webhook e sincronize; não gere outra cobrança.',now,cid))
            raise HTTPException(502,'Tentativa registrada sem confirmação. Sincronize ou consulte os logs do Asaas antes de repetir.') from None
        with banco() as db:
            db.execute("UPDATE saas_contratos SET checkout_id=?,status=CASE WHEN status IN ('criando','incerta') THEN 'checkout' ELSE status END,atualizado_em=? WHERE id=?",(checkout_id,now,cid))
            row = db.execute('SELECT * FROM saas_contratos WHERE id=?',(cid,)).fetchone()
            audit(db,row,user['id'],'checkout_criado')
            return contract_view(row)

    def store_payment(db,row,payment):
        if payment.get('subscription') != row['assinatura_id'] or payment.get('customer') != row['cliente_id']:
            raise ValueError('Vínculo da cobrança incompatível.')
        value = cents(payment.get('value'))
        if value != row['valor_centavos'] or payment.get('billingType') != 'CREDIT_CARD':
            raise ValueError('Cobrança fora do contrato.')
        pid = ident(payment.get('id'))
        due = date.fromisoformat(payment['dueDate']).isoformat()
        status = str(payment.get('status','PENDING'))[:60]
        if payment.get('deleted'): status = 'DELETED'
        paid = payment.get('paymentDate') or payment.get('confirmedDate') or payment.get('clientPaymentDate')
        if paid: paid = date.fromisoformat(str(paid)[:10]).isoformat()
        # Pagamento atrasado dá um novo mês a partir da quitação, sem contar duas vezes.
        end = month_end(max(due,paid or due))
        db.execute('INSERT INTO saas_cobrancas(id,loja_id,contrato_id,ambiente,provedor_id,valor_centavos,status,vencimento,pago_em,periodo_fim,fatura_url,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ambiente,provedor_id) DO UPDATE SET status=excluded.status,pago_em=excluded.pago_em,periodo_fim=excluded.periodo_fim,fatura_url=excluded.fatura_url,atualizado_em=excluded.atualizado_em',
                   ('sandbox:'+pid,row['loja_id'],row['id'],'sandbox',pid,value,status,due,paid,end,safe_invoice(payment.get('invoiceUrl')),int(time.time())))

    def sync_contract(cid):
        with banco() as db: found = db.execute('SELECT * FROM saas_contratos WHERE id=? AND ambiente=?',(cid,'sandbox')).fetchone()
        if not found or not found['checkout_id']: return
        row = dict(found)
        sid = row['assinatura_id']
        if not sid:
            data = api('GET','/payments?'+urllib.parse.urlencode({'checkoutSession':row['checkout_id'],'limit':100}))
            payments = data.get('data',[])
            ids = {p.get('subscription') for p in payments if p.get('subscription')}
            if len(ids) != 1:
                if ids: raise ValueError('Mais de uma assinatura no checkout.')
                return
            sid = ident(ids.pop())
            subscription = api('GET','/subscriptions/'+sid)
            if subscription.get('deleted'): return
            row['assinatura_id'] = sid
            row['cliente_id'] = ident(subscription.get('customer'))
        else:
            subscription = api('GET','/subscriptions/'+ident(sid))
            payments = []
        if not subscription.get('deleted'):
            if subscription.get('id') != sid or subscription.get('customer') != row['cliente_id'] or subscription.get('cycle') != 'MONTHLY' or subscription.get('billingType') != 'CREDIT_CARD' or cents(subscription.get('value')) != row['valor_centavos']:
                raise ValueError('Assinatura fora do contrato.')
        # Lista paginada, com limite explícito de trabalho por passagem.
        for offset in range(0,1000,100):
            page = api('GET','/subscriptions/'+sid+'/payments?'+urllib.parse.urlencode({'limit':100,'offset':offset}))
            payments.extend(page.get('data',[]))
            if not page.get('hasMore'): break
        with banco() as db:
            lock(db)
            current = db.execute('SELECT * FROM saas_contratos WHERE id=?',(cid,)).fetchone()
            if current['assinatura_id'] and current['assinatura_id'] != sid: raise ValueError('Assinatura alterada.')
            for payment in payments: store_payment(db,row,payment)
            paid = db.execute("SELECT MAX(periodo_fim) AS fim FROM saas_cobrancas WHERE contrato_id=? AND status IN ('RECEIVED','CONFIRMED','RECEIVED_IN_CASH')",(cid,)).fetchone()['fim']
            late = db.execute("SELECT COUNT(*) AS n FROM saas_cobrancas WHERE contrato_id=? AND status IN ('OVERDUE','CREDIT_CARD_CAPTURE_REFUSED')",(cid,)).fetchone()['n']
            canceled = subscription.get('deleted') or subscription.get('status') == 'INACTIVE'
            status = 'cancelada' if canceled else 'atrasada' if late else 'ativa' if paid else 'aguardando_pagamento'
            next_due = subscription.get('nextDueDate')
            if next_due: next_due = date.fromisoformat(next_due[:10]).isoformat()
            db.execute('UPDATE saas_contratos SET assinatura_id=?,cliente_id=?,status=?,proximo_vencimento=?,pago_ate=?,erro=NULL,atualizado_em=? WHERE id=?',
                       (sid,row['cliente_id'],status,None if canceled else next_due,paid,int(time.time()),cid))
        # IMPORTANTE: Sandbox NÃO escreve em assinaturas/pagamentos/cortesias.

    def process_event(event):
        kind = event['tipo']
        if kind.startswith('CHECKOUT_'):
            with banco() as db:
                lock(db)
                row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND checkout_id=?',('sandbox',event['recurso_id'])).fetchone()
                if not row and event['referencia'] and event['referencia'].startswith('havo:'):
                    row = db.execute("SELECT * FROM saas_contratos WHERE id=? AND ambiente='sandbox' AND status IN ('criando','incerta')",(event['referencia'][5:],)).fetchone()
                    if row:
                        db.execute("UPDATE saas_contratos SET checkout_id=?,status='checkout',erro=NULL WHERE id=?",(event['recurso_id'],row['id']))
                cid = row['id'] if row else None
                if cid and kind in ('CHECKOUT_CANCELED','CHECKOUT_EXPIRED') and not row['assinatura_id']:
                    # Não substitui assinatura paga por evento antigo do checkout.
                    db.execute('UPDATE saas_contratos SET status=?,atualizado_em=? WHERE id=?',('cancelada' if kind.endswith('CANCELED') else 'expirada',int(time.time()),cid))
            if cid: sync_contract(cid)
        elif kind.startswith('PAYMENT_'):
            payment = api('GET','/payments/'+ident(event['recurso_id']))
            sid = payment.get('subscription')
            if not sid: return
            with banco() as db:
                row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND assinatura_id=?',('sandbox',sid)).fetchone()
                if not row and payment.get('checkoutSession'):
                    row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND checkout_id=?',('sandbox',payment['checkoutSession'])).fetchone()
            if not row:
                # Um evento de cobrança pode chegar antes do CHECKOUT_PAID.
                reconcile_pending()
                with banco() as db: row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND assinatura_id=?',('sandbox',sid)).fetchone()
            if row: sync_contract(row['id'])
        elif kind.startswith('SUBSCRIPTION_'):
            with banco() as db: row = db.execute('SELECT id FROM saas_contratos WHERE ambiente=? AND assinatura_id=?',('sandbox',event['recurso_id'])).fetchone()
            if row: sync_contract(row['id'])
            else: reconcile_pending()

    def reconcile_pending():
        with banco() as db:
            rows = db.execute("SELECT id FROM saas_contratos WHERE ambiente='sandbox' AND checkout_id IS NOT NULL AND assinatura_id IS NULL AND status NOT IN ('cancelada','expirada') ORDER BY atualizado_em LIMIT 10").fetchall()
        for row in rows: sync_contract(row['id'])

    def tick():
        if not enabled(): return
        now = int(time.time())
        with banco() as db:
            lock(db)
            events = [dict(r) for r in db.execute("SELECT * FROM saas_webhooks WHERE ambiente='sandbox' AND status IN ('pendente','processando') AND proxima_tentativa<=? ORDER BY criado_em LIMIT 10",(now,)).fetchall()]
            for event in events:
                db.execute("UPDATE saas_webhooks SET status='processando',tentativas=tentativas+1,proxima_tentativa=? WHERE id=?",(now+900,event['id']))
        for event in events:
            try:
                process_event(event)
                with banco() as db: db.execute("UPDATE saas_webhooks SET status='processado',processado_em=?,erro=NULL WHERE id=?",(int(time.time()),event['id']))
            except Exception:
                # Backoff persistente: reiniciar o servidor não perde a fila.
                with banco() as db: db.execute("UPDATE saas_webhooks SET status='pendente',proxima_tentativa=?,erro=? WHERE id=?",(now+min(3600,30*2**min(event['tentativas'],7)),'Falha na sincronização; próxima tentativa agendada.',event['id']))
        # Conferência leve no backend: recupera eventos perdidos enquanto o serviço
        # esteve desligado. Nunca usa loops no navegador ou tarefas só em memória.
        with banco() as db:
            stale = db.execute("SELECT id FROM saas_contratos WHERE ambiente='sandbox' AND checkout_id IS NOT NULL AND atualizado_em<? AND status NOT IN ('cancelada','expirada') ORDER BY atualizado_em LIMIT 5",(now-3600,)).fetchall()
        for row in stale:
            try: sync_contract(row['id'])
            except Exception:
                with banco() as db: db.execute('UPDATE saas_contratos SET atualizado_em=?,erro=? WHERE id=?',(now,'Conferência pendente; tente sincronizar novamente.',row['id']))

    @app.post('/api/saas/webhook')
    async def webhook(request:Request,background:BackgroundTasks):
        secret = os.environ.get('ASAAS_WEBHOOK_TOKEN','')
        if not enabled() or len(secret)<32 or secret == os.environ.get('ASAAS_API_KEY'):
            raise HTTPException(503,'Webhook indisponível.')
        if not hmac.compare_digest(secret,request.headers.get('asaas-access-token','')):
            raise HTTPException(401,'Webhook não autorizado.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>128_000: raise HTTPException(413,'Evento excede o limite.')
        try:
            data = json.loads(raw)
            eid = ident(data['id']); kind = data['event']
            if kind not in EVENTS: return {'recebido':True,'ignorado':True}
            obj = data[kind.split('_')[0].lower()]
            rid = ident(obj['id'])
            ref = obj.get('externalReference')
            if ref is not None and (not isinstance(ref,str) or not re.fullmatch(r'havo:[a-f0-9]{48}',ref)): ref = None
        except (ValueError,KeyError,TypeError): raise HTTPException(422,'Evento inválido.') from None
        with banco() as db:
            db.execute("INSERT INTO saas_webhooks(id,ambiente,tipo,recurso_id,referencia,status,tentativas,proxima_tentativa,criado_em) VALUES(?,?,?,?,?,'pendente',0,?,?) ON CONFLICT(id) DO NOTHING",('sandbox:'+eid,'sandbox',kind,rid,ref,int(time.time()),int(time.time())))
        background.add_task(tick)
        return {'recebido':True}

    @app.post('/api/saas/sincronizar')
    def sync_owner(request:Request):
        with banco() as db:
            user = owner(request,db,True)
            c['limitar'](request,'asaas-sync',12,3600)
            rows = db.execute("SELECT id FROM saas_contratos WHERE loja_id=? AND ambiente='sandbox' ORDER BY criado_em DESC LIMIT 10",(user['loja_id'],)).fetchall()
        tick()
        for row in rows: sync_contract(row['id'])
        return {'status':'sincronizado'}

    @app.post('/api/saas/contratos/{cid}/cancelar')
    def cancel(cid:str,request:Request):
        with banco() as db:
            user = owner(request,db,True)
            row = db.execute('SELECT * FROM saas_contratos WHERE id=? AND loja_id=? AND ambiente=?',(cid,user['loja_id'],'sandbox')).fetchone()
            if not row: raise HTTPException(404,'Contrato não encontrado.')
            if row['status'] == 'cancelada': return {'status':'cancelada'}
            row = dict(row)
        if row['assinatura_id']:
            api('PUT','/subscriptions/'+ident(row['assinatura_id']),{'status':'INACTIVE'})
            sync_contract(cid)
        elif row['checkout_id']:
            api('POST','/checkouts/'+ident(row['checkout_id'])+'/cancel')
        else: raise HTTPException(409,'Tentativa sem confirmação; confira os logs do Asaas antes de cancelar.')
        with banco() as db:
            lock(db)
            # Uma assinatura encontrada durante o cancelamento do checkout deve ser
            # cancelada explicitamente antes de liberar uma nova contratação.
            current = db.execute('SELECT * FROM saas_contratos WHERE id=?',(cid,)).fetchone()
            if not row['assinatura_id'] and current['assinatura_id']:
                raise HTTPException(409,'A assinatura foi criada durante a operação. Sincronize e cancele novamente.')
            db.execute("UPDATE saas_contratos SET status='cancelada',proximo_vencimento=NULL,atualizado_em=? WHERE id=?",(int(time.time()),cid))
            audit(db,row,user['id'],'cancelamento_confirmado_asaas')
        return {'status':'cancelada'}

    @app.get('/api/gestao/asaas')
    def admin_report(request:Request):
        with banco() as db:
            c['administrador'](request,db)
            rows = db.execute("SELECT s.*,u.email,l.slug FROM saas_contratos s JOIN lojas l ON l.id=s.loja_id JOIN usuarios u ON u.loja_id=s.loja_id WHERE s.ambiente='sandbox' ORDER BY s.criado_em DESC LIMIT 200").fetchall()
            pending = db.execute("SELECT COUNT(*) AS n FROM saas_webhooks WHERE status!='processado'").fetchone()['n']
        return {'ambiente':'sandbox','eventos_pendentes':pending,'contratos':[contract_view(r)|{'email':r['email'],'slug':r['slug']} for r in rows],
                'receita_real_centavos':0,'observacao':'Somente simulação. Pagamentos Sandbox não são receita nem liberam acesso real.'}

    async def worker():
        while True:
            try: await asyncio.to_thread(tick)
            except Exception: pass
            await asyncio.sleep(60)

    @app.on_event('startup')
    async def start(): app.state.asaas_worker = asyncio.create_task(worker())

    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state,'asaas_worker',None)
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

    # Exposto apenas para testes locais, não como rota HTTP pública.
    c['asaas_sync_contract'] = sync_contract
    c['asaas_tick'] = tick
