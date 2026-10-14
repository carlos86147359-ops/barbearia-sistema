"""Cobrança Grupo Havo: ambientes separados e confirmação financeira no servidor.

Produção exige habilitação explícita; Sandbox nunca libera acesso real.
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
from fastapi.responses import FileResponse, JSONResponse
import qrcode

DDL = {
    'saas_contratos': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,ambiente TEXT NOT NULL,usuario_id TEXT NOT NULL,valor_centavos INTEGER NOT NULL,checkout_id TEXT,assinatura_id TEXT,cliente_id TEXT,status TEXT NOT NULL,proximo_vencimento TEXT,pago_ate TEXT,criado_em BIGINT NOT NULL,atualizado_em BIGINT NOT NULL,erro TEXT',
    'saas_cobrancas': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,contrato_id TEXT NOT NULL,ambiente TEXT NOT NULL,provedor_id TEXT NOT NULL,valor_centavos INTEGER NOT NULL,status TEXT NOT NULL,vencimento TEXT NOT NULL,pago_em TEXT,periodo_fim TEXT NOT NULL,fatura_url TEXT,atualizado_em BIGINT NOT NULL,UNIQUE(ambiente,provedor_id)',
    'saas_webhooks': 'id TEXT PRIMARY KEY,ambiente TEXT NOT NULL,tipo TEXT NOT NULL,recurso_id TEXT NOT NULL,referencia TEXT,status TEXT NOT NULL,tentativas INTEGER NOT NULL,proxima_tentativa BIGINT NOT NULL,criado_em BIGINT NOT NULL,processado_em BIGINT,erro TEXT',
    'saas_condicoes': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,ambiente TEXT NOT NULL,oferta TEXT NOT NULL,primeiro_vencimento TEXT NOT NULL,ultimo_vencimento TEXT,aceite_em BIGINT NOT NULL',
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


def environment():
    value = os.environ.get('ASAAS_ENV', '')
    return value if value in ('sandbox', 'production') else None


def api_key():
    return os.environ.get('ASAAS_PRODUCTION_API_KEY' if environment() == 'production' else 'ASAAS_API_KEY', '')


def webhook_secret():
    return os.environ.get('ASAAS_PRODUCTION_WEBHOOK_TOKEN' if environment() == 'production' else 'ASAAS_WEBHOOK_TOKEN', '')


def enabled():
    return bool(environment() and api_key() and len(webhook_secret()) >= 32 and webhook_secret() != api_key())


def limited_offer_enabled():
    return environment() == 'production' or (environment() == 'sandbox' and os.environ.get('ASAAS_SANDBOX_PROMO_TEST','').lower() == 'true')


def production_sales_enabled():
    return os.environ.get('ASAAS_PRODUCTION_ENABLED', '').lower() == 'true'


def add_months(day, count):
    d = date.fromisoformat(day)
    total = d.year * 12 + d.month - 1 + count
    year, month = divmod(total, 12)
    month += 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def production_access(db, shop_id, today):
    # Somente recebimentos reais confirmados e período vigente, nunca redirects.
    paid = db.execute("SELECT MAX(periodo_fim) AS fim FROM saas_cobrancas WHERE loja_id=? AND ambiente=? AND status IN ('RECEIVED','CONFIRMED') AND vencimento<=? AND periodo_fim>?",
                      (shop_id, 'production', today, today)).fetchone()['fim']
    return paid



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
    if p.scheme == 'https' and p.hostname == ('www.asaas.com' if environment() == 'production' else 'sandbox.asaas.com') and not p.username and p.port in (None,443):
        return url
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


class CheckoutRejected(Exception):
    pass


def api(method,path,body=None):
    if not enabled(): raise HTTPException(503,'Integração Asaas não configurada.')
    if not path.startswith('/') or '..' in path: raise ValueError('Rota inválida.')
    req = urllib.request.Request(('https://api.asaas.com/v3' if environment() == 'production' else 'https://api-sandbox.asaas.com/v3')+path,
        data=json.dumps(body).encode() if body is not None else None,method=method,
        headers={'access_token':api_key(),'Content-Type':'application/json','User-Agent':'GrupoHavo/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=65) as response:
            return json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as exc:
        # Nunca devolver mensagens do provedor: podem conter dados pessoais.
        if method == 'GET' and exc.code == 404: return {'deleted':True}
        if method == 'POST' and path == '/checkouts' and exc.code == 400:
            raise CheckoutRejected() from None
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
        if environment() == 'sandbox' and not sandbox_allowed(user): raise HTTPException(403,'Conta não autorizada para homologação Sandbox.')
        if not enabled(): raise HTTPException(503,'Integração Asaas ainda indisponível.')
        return user

    def audit(db,row,user,action):
        db.execute('INSERT INTO saas_auditoria(id,loja_id,contrato_id,usuario_id,acao,criado_em) VALUES(?,?,?,?,?,?)',
                   (secrets.token_hex(16),row['loja_id'],row['id'],user,action,int(time.time())))

    def contract_view(row):
        out = {k:row[k] for k in ('ambiente','id','valor_centavos','status','proximo_vencimento','pago_ate','erro','criado_em')}
        if row['checkout_id'] and row['status'] == 'checkout':
            out['checkout_url'] = ('https://www.asaas.com' if row['ambiente'] == 'production' else 'https://sandbox.asaas.com')+'/checkoutSession/show?id='+urllib.parse.quote(row['checkout_id'])
        with banco() as db: terms = db.execute('SELECT * FROM saas_condicoes WHERE id=?',(row['id'],)).fetchone()
        out['condicoes'] = dict(terms) if terms else None
        out['forma_pagamento'] = 'PIX' if terms and terms['oferta'].startswith('pix_') else 'CREDIT_CARD'
        if out['forma_pagamento'] == 'PIX' and row['pago_ate']: out['status'] = 'quitada'
        return out

    @app.get('/cobranca-saas.js')
    def script(): return FileResponse(c['ROOT']/'cobranca-saas.js',media_type='application/javascript')

    def pix_cycles(db, shop):
        if db is None:
            with banco() as conn: return pix_cycles(conn,shop)
        # Cada mês promocional pago consome uma posição, inclusive após estorno.
        return db.execute("SELECT COUNT(DISTINCT s.id) AS n FROM saas_contratos s JOIN saas_condicoes t ON t.id=s.id JOIN saas_cobrancas p ON p.contrato_id=s.id AND p.ambiente=s.ambiente WHERE s.loja_id=? AND s.ambiente=? AND t.oferta='pix_60_v1' AND p.pago_em IS NOT NULL",(shop,environment())).fetchone()['n']

    def used_offer(db=None, shop=None):
        def check(conn):
            return pix_cycles(conn,shop) >= 3 or bool(conn.execute("SELECT 1 FROM saas_condicoes t JOIN saas_contratos s ON s.id=t.id WHERE t.loja_id=? AND t.ambiente=? AND t.oferta=? AND (s.assinatura_id IS NOT NULL OR s.status IN ('criando','incerta','checkout')) LIMIT 1",
                                     (shop, environment(), 'tres_meses_60_v1')).fetchone())
        if db is not None: return check(db)
        with banco() as conn: return check(conn)

    @app.get('/api/saas/assinatura')
    def summary(request:Request):
        with banco() as db:
            user = c['dono'](request,db)
            if not enabled() or (environment() == 'sandbox' and not sandbox_allowed(user)): return {'disponivel':False}
            if environment() == 'production' and db.execute('SELECT 1 FROM cortesias WHERE loja_id=?',(user['loja_id'],)).fetchone(): return {'disponivel':False}
            rows = db.execute('SELECT * FROM saas_contratos WHERE loja_id=? AND ambiente=? ORDER BY criado_em DESC,id DESC',
                              (user['loja_id'],environment())).fetchall()
            access = c['assinatura'](db,user['loja_id'])
            manual = [dict(p) for p in db.execute('SELECT valor_centavos,confirmado_em,vencimento FROM pagamentos WHERE loja_id=? ORDER BY confirmado_em DESC LIMIT 100',(user['loja_id'],)).fetchall()]
            can_contract = not access.get('vencimento') or datetime.fromisoformat(access['vencimento']) <= datetime.now(c['BRASIL'])
            payments = db.execute('SELECT valor_centavos,status,vencimento,pago_em,fatura_url FROM saas_cobrancas WHERE loja_id=? AND ambiente=? ORDER BY vencimento DESC,id DESC LIMIT 100',
                                  (user['loja_id'],environment())).fetchall()
        return {'disponivel':True,'ambiente':environment(),'oferta_limitada':limited_offer_enabled(),'valor_centavos':6000 if limited_offer_enabled() and not used_offer(db=None, shop=user['loja_id']) else 9000,
                'vendas_habilitadas':environment() == 'sandbox' or production_sales_enabled(),
                'acesso_atual':access,'pagamentos_manuais':manual,'contratacao_disponivel':environment() == 'sandbox' or can_contract,
                'pix_disponivel':limited_offer_enabled(), 'ciclos_promocionais_restantes':max(0,3-pix_cycles(None,user['loja_id'])),
                'contratos':[contract_view(r) for r in rows], 'pagamentos':[dict(r) for r in payments]}

    @app.post('/api/saas/checkout')
    async def checkout(request:Request):
        body = {}
        if limited_offer_enabled() and enabled():
            raw = await request.body()
            if len(raw)>4096: raise HTTPException(413,'Pedido excede o limite.')
            try: body = json.loads(raw)
            except (ValueError,TypeError): raise HTTPException(422,'Confirme as condições da contratação.') from None
        if limited_offer_enabled() and enabled() and (not isinstance(body,dict) or body.get('aceite_condicoes') != 'tres_meses_60_depois_nova_contratacao_90_v1'):
            raise HTTPException(422,'Confirme as condições da contratação.')
        method = body.get('forma_pagamento','CREDIT_CARD')
        if method not in ('CREDIT_CARD','PIX'): raise HTTPException(422,'Forma de pagamento inválida.')
        if method == 'PIX' and not limited_offer_enabled(): raise HTTPException(409,'PIX indisponível neste modo de homologação.')
        if method == 'PIX' and body.get('aceite_pix') != 'pix_mensal_sem_debito_automatico_v1': raise HTTPException(422,'Confirme as condições do PIX mensal.')
        now = int(time.time())
        base = os.environ.get('PUBLIC_BASE_URL','').rstrip('/')
        p = urllib.parse.urlparse(base)
        if p.scheme != 'https' or not p.hostname or p.query or p.fragment or p.username:
            raise HTTPException(503,'Configure PUBLIC_BASE_URL com a URL HTTPS do aplicativo.')
        with banco() as db:
            user = owner(request,db,True)
            if environment() == 'production':
                if not production_sales_enabled(): raise HTTPException(503,'Novas contratações reais ainda não estão habilitadas.')
                if db.execute('SELECT 1 FROM cortesias WHERE loja_id=?',(user['loja_id'],)).fetchone():
                    raise HTTPException(409,'Conta liberada por cortesia. Nenhuma cobrança necessária.')
            c['limitar'](request,'asaas-checkout',8,3600)
            lock(db)
            old = db.execute("SELECT * FROM saas_contratos WHERE loja_id=? AND ambiente=? AND status NOT IN ('cancelada','expirada')",(user['loja_id'],environment())).fetchone()
            if old:
                if old['status'] == 'checkout' and old['checkout_id']:
                    view = contract_view(old)
                    if view['forma_pagamento'] != method: raise HTTPException(409,'Já existe um checkout de outra forma de pagamento. Cancele-o antes de trocar.')
                    return view
                raise HTTPException(409,'Já existe uma contratação ou tentativa em conferência. Sincronize antes de criar outra.')
            first_due = datetime.now(c['BRASIL']).date().isoformat()
            promo = limited_offer_enabled() and not used_offer(db,user['loja_id'])
            price = 6000 if promo else 9000
            last_due = first_due if method == 'PIX' else add_months(first_due,max(0,2-pix_cycles(db,user['loja_id']))) if promo else None
            if environment() == 'production':
                pending = db.execute("SELECT 1 FROM saas_cobrancas WHERE loja_id=? AND ambiente=? AND status IN ('PENDING','OVERDUE','CREDIT_CARD_CAPTURE_REFUSED','AWAITING_RISK_ANALYSIS','AUTHORIZED') LIMIT 1",(user['loja_id'],'production')).fetchone()
                if pending: raise HTTPException(409,'Existe mensalidade pendente. Regularize a fatura antes de criar nova assinatura.')
                access = c['assinatura'](db,user['loja_id'])
                if access.get('vencimento') and datetime.fromisoformat(access['vencimento']) > datetime.now(c['BRASIL']):
                    raise HTTPException(409,'Seu período pago ainda está vigente. Aguarde o fim do período para nova contratação.')
            cid = secrets.token_hex(24)
            db.execute('INSERT INTO saas_contratos(id,loja_id,ambiente,usuario_id,valor_centavos,status,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?)',
                       (cid,user['loja_id'],environment(),user['id'],price,'criando',now,now))
            db.execute('INSERT INTO saas_condicoes(id,loja_id,ambiente,oferta,primeiro_vencimento,ultimo_vencimento,aceite_em) VALUES(?,?,?,?,?,?,?)',
                       (cid,user['loja_id'],environment(),('pix_60_v1' if promo else 'pix_90_v1') if method == 'PIX' else ('tres_meses_60_v1' if promo else 'mensal_90_v1'),first_due,last_due,now))
        # A tentativa é confirmada no banco ANTES da chamada externa.
        # Timeout nunca provoca uma segunda criação automática.
        try:
            result = api('POST','/checkouts',{'externalReference':'havo:'+cid,
                'billingTypes':[method],'chargeTypes':['DETACHED' if method == 'PIX' else 'RECURRENT'],'minutesToExpire':1440 if method == 'PIX' else 60,
                'callback':{k:base+'/painel#plano' for k in ('successUrl','cancelUrl','expiredUrl')},
                'items':[{'name':'Grupo Havo - Mensal TESTE' if environment() == 'sandbox' else 'Grupo Havo - Mensal',
                          'description':'Homologação Sandbox, sem cobrança real' if environment() == 'sandbox' else ('Uma mensalidade via PIX. Renovação exige novo pagamento; sem débito automático.' if method == 'PIX' else 'R$60 por mês por 3 ciclos. Depois exige nova contratação de R$90/mês.' if promo else 'R$90 por mês. Recorrência mensal até cancelamento.'),
                          'quantity':1,'value':price/100}],
                **({'subscription':{'cycle':'MONTHLY','nextDueDate':datetime.now(c['BRASIL']).strftime('%Y-%m-%d %H:%M:%S'),**({'endDate':last_due+' 23:59:59'} if last_due else {})}} if method != 'PIX' else {})})
            checkout_id = ident(result.get('id'))
        except CheckoutRejected:
            with banco() as db:
                db.execute("UPDATE saas_contratos SET status='expirada',erro=?,atualizado_em=? WHERE id=? AND status='criando'",
                           ('Asaas recusou os dados do checkout (HTTP 400). Nenhum checkout confirmado.',now,cid))
                row = db.execute('SELECT * FROM saas_contratos WHERE id=?',(cid,)).fetchone()
                audit(db,row,user['id'],'checkout_rejeitado_http400')
            raise HTTPException(422,'O Asaas recusou os dados do checkout. A tentativa foi encerrada sem cobrança.') from None
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
        end = month_end(due if row['ambiente'] == 'production' else max(due,paid or due))
        if row['ambiente'] == 'production':
            terms = db.execute('SELECT * FROM saas_condicoes WHERE id=?',(row['id'],)).fetchone()
            if not terms or due < terms['primeiro_vencimento'] or (terms['ultimo_vencimento'] and due > terms['ultimo_vencimento']):
                raise ValueError('Cobrança fora do período contratado.')
            anchor = date.fromisoformat(terms['primeiro_vencimento'])
            due_day = date.fromisoformat(due)
            cycle = (due_day.year-anchor.year)*12 + due_day.month-anchor.month
            if due != add_months(terms['primeiro_vencimento'],cycle):
                raise ValueError('Vencimento fora do calendário contratado.')
            end = add_months(terms['primeiro_vencimento'],cycle+1)
        db.execute('INSERT INTO saas_cobrancas(id,loja_id,contrato_id,ambiente,provedor_id,valor_centavos,status,vencimento,pago_em,periodo_fim,fatura_url,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ambiente,provedor_id) DO UPDATE SET status=excluded.status,pago_em=excluded.pago_em,periodo_fim=excluded.periodo_fim,fatura_url=excluded.fatura_url,atualizado_em=excluded.atualizado_em',
                   (row['ambiente']+':'+pid,row['loja_id'],row['id'],row['ambiente'],pid,value,status,due,paid,end,safe_invoice(payment.get('invoiceUrl')),int(time.time())))

    def sync_pix(db,row,terms,payment_hint=None):
        # Checkout avulso: confirmar cobrança canônica, nunca CHECKOUT_PAID sozinho.
        page = api('GET','/payments?'+urllib.parse.urlencode({'checkoutSession':row['checkout_id'],'limit':100}))
        if page.get('hasMore'): raise ValueError('Checkout PIX com cobranças inesperadas.')
        candidates = {ident(p['id']):p for p in page.get('data',[]) if p.get('checkoutSession') == row['checkout_id']}
        known = db.execute('SELECT * FROM saas_cobrancas WHERE contrato_id=? AND ambiente=?',(row['id'],row['ambiente'])).fetchall()
        for p in known: candidates[p['provedor_id']] = None
        if payment_hint and payment_hint.get('checkoutSession') == row['checkout_id']: candidates[ident(payment_hint['id'])] = None
        if len(candidates)>1: raise ValueError('Mais de uma cobrança no checkout PIX.')
        for pid in candidates:
            p = api('GET','/payments/'+pid)
            previous = next((k for k in known if k['provedor_id']==pid),None)
            if p.get('deleted'):
                if not previous: continue
                db.execute("UPDATE saas_cobrancas SET status='DELETED',atualizado_em=? WHERE ambiente=? AND provedor_id=?",(int(time.time()),row['ambiente'],pid))
                continue
            if p.get('id') != pid or p.get('checkoutSession') != row['checkout_id'] or p.get('subscription') or p.get('billingType') != 'PIX' or cents(p.get('value')) != row['valor_centavos']:
                raise ValueError('Cobrança PIX fora do contrato.')
            customer = ident(p.get('customer'))
            if row['cliente_id'] and customer != row['cliente_id']: raise ValueError('Cliente PIX incompatível.')
            status = str(p.get('status','PENDING'))[:60]
            paid = p.get('paymentDate') or p.get('confirmedDate') or p.get('clientPaymentDate')
            paid = date.fromisoformat(str(paid)[:10]).isoformat() if paid else None
            if status in ('CONFIRMED','RECEIVED') and not paid: raise ValueError('PIX sem data de confirmação.')
            if status not in ('CONFIRMED','RECEIVED','REFUNDED','REFUND_IN_PROGRESS','CHARGEBACK_REQUESTED','CHARGEBACK_DISPUTE','AWAITING_CHARGEBACK_REVERSAL'): paid = previous['pago_em'] if previous else None
            start = previous['vencimento'] if previous and previous['pago_em'] else max(terms['primeiro_vencimento'],paid or terms['primeiro_vencimento'])
            end = previous['periodo_fim'] if previous and previous['pago_em'] else month_end(start)
            db.execute("INSERT INTO saas_cobrancas(id,loja_id,contrato_id,ambiente,provedor_id,valor_centavos,status,vencimento,pago_em,periodo_fim,fatura_url,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ambiente,provedor_id) DO UPDATE SET status=excluded.status,pago_em=COALESCE(saas_cobrancas.pago_em,excluded.pago_em),vencimento=excluded.vencimento,periodo_fim=excluded.periodo_fim,fatura_url=excluded.fatura_url,atualizado_em=excluded.atualizado_em",
                (row['ambiente']+':'+pid,row['loja_id'],row['id'],row['ambiente'],pid,row['valor_centavos'],status,start,paid,end,safe_invoice(p.get('invoiceUrl')),int(time.time())))
            db.execute('UPDATE saas_contratos SET cliente_id=? WHERE id=?',(customer,row['id']))
        paid_end = db.execute("SELECT MAX(periodo_fim) AS fim FROM saas_cobrancas WHERE contrato_id=? AND status IN ('CONFIRMED','RECEIVED')",(row['id'],)).fetchone()['fim']
        # Fecha somente esta cobrança avulsa; não há recorrência para cancelar.
        ever_paid = any(k['pago_em'] for k in db.execute('SELECT pago_em FROM saas_cobrancas WHERE contrato_id=?',(row['id'],)).fetchall())
        state = 'cancelada' if ever_paid else row['status']
        db.execute('UPDATE saas_contratos SET status=?,pago_ate=?,proximo_vencimento=NULL,erro=NULL,atualizado_em=? WHERE id=?',(state,paid_end,int(time.time()),row['id']))

    def sync_contract(cid,payment_hint=None):
        # Serializa leituras canônicas e gravações inclusive entre processos.
        # Nenhuma consulta antiga sobrescreve um estorno ou cancelamento novo.
        with banco() as db:
            lock(db)
            invalid = sync_locked(db,cid,payment_hint)
        if invalid: raise ValueError('Há cobrança fora das condições contratadas; conferência necessária.')

    def sync_locked(db,cid,payment_hint=None):
        found = db.execute('SELECT * FROM saas_contratos WHERE id=? AND ambiente=?',(cid,environment())).fetchone()
        if not found or not found['checkout_id']: return
        row = dict(found)
        terms = db.execute('SELECT * FROM saas_condicoes WHERE id=?',(cid,)).fetchone()
        if terms and terms['oferta'].startswith('pix_'):
            return sync_pix(db,row,terms,payment_hint)
        sid = row['assinatura_id']
        if not sid:
            data = api('GET','/payments?'+urllib.parse.urlencode({'checkoutSession':row['checkout_id'],'limit':100}))
            payments = data.get('data',[])
            # Vincular apenas cobranças recuperadas da API, nunca o corpo do webhook.
            if payment_hint and payment_hint.get('checkoutSession') == row['checkout_id']:
                payments.append(payment_hint)
            if not any(p.get('subscription') for p in payments):
                candidates = db.execute("SELECT DISTINCT recurso_id FROM saas_webhooks WHERE ambiente=? AND tipo LIKE ? AND criado_em>=? ORDER BY recurso_id LIMIT 100",(environment(),'PAYMENT_%',row['criado_em'])).fetchall()
                for candidate in candidates:
                    canonical = api('GET','/payments/'+ident(candidate['recurso_id']))
                    if canonical.get('checkoutSession') == row['checkout_id'] and canonical.get('subscription'):
                        payments.append(canonical)
                        break
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
        terms = db.execute('SELECT * FROM saas_condicoes WHERE id=?',(cid,)).fetchone()
        if (row['ambiente'] == 'production' or (terms and terms['ultimo_vencimento'])) and not subscription.get('deleted'):
            expected_end = terms['ultimo_vencimento'] if terms else None
            actual_end = str(subscription.get('endDate') or '')[:10] or None
            if not terms or actual_end != expected_end:
                raise ValueError('Prazo da recorrência diferente do contrato.')
        # Lista paginada, com limite explícito de trabalho por passagem.
        for offset in range(0,1000,100):
            page = api('GET','/subscriptions/'+sid+'/payments?'+urllib.parse.urlencode({'limit':100,'offset':offset}))
            payments.extend(page.get('data',[]))
            if not page.get('hasMore'): break
        if payment_hint and payment_hint.get('subscription') == sid:
            payments = [p for p in payments if p.get('id') != payment_hint.get('id')] + [payment_hint]
        current = db.execute('SELECT * FROM saas_contratos WHERE id=?',(cid,)).fetchone()
        if current['assinatura_id'] and current['assinatura_id'] != sid: raise ValueError('Assinatura alterada.')
        invalid = False
        for payment in payments:
            try: store_payment(db,row,payment)
            except ValueError: invalid = True
        paid = db.execute("SELECT MAX(periodo_fim) AS fim FROM saas_cobrancas WHERE contrato_id=? AND status IN ('RECEIVED','CONFIRMED','RECEIVED_IN_CASH')",(cid,)).fetchone()['fim']
        late = db.execute("SELECT COUNT(*) AS n FROM saas_cobrancas WHERE contrato_id=? AND status IN ('OVERDUE','CREDIT_CARD_CAPTURE_REFUSED')",(cid,)).fetchone()['n']
        ended = terms and terms['ultimo_vencimento'] and datetime.now(c['BRASIL']).date().isoformat() > terms['ultimo_vencimento']
        canceled = subscription.get('deleted') or subscription.get('status') == 'INACTIVE' or ended
        status = 'cancelada' if canceled else 'atrasada' if late else 'ativa' if paid else 'aguardando_pagamento'
        if row['ambiente'] == 'production' and current['status'] == 'cancelando': status = 'cancelando'
        next_due = subscription.get('nextDueDate')
        if next_due: next_due = date.fromisoformat(next_due[:10]).isoformat()
        db.execute('UPDATE saas_contratos SET assinatura_id=?,cliente_id=?,status=?,proximo_vencimento=?,pago_ate=?,erro=?,atualizado_em=? WHERE id=?',
                   (sid,row['cliente_id'],status,None if canceled else next_due,paid,'Cobrança fora das condições; conferência necessária.' if invalid else None,int(time.time()),cid))
        # Confirmações/estornos válidos são preservados mesmo se outra cobrança exigir revisão.
        return invalid
        # Acesso real é calculado pelos recebimentos de produção, sem alterar Pix/cortesia.

    def process_event(event):
        kind = event['tipo']
        if kind.startswith('CHECKOUT_'):
            with banco() as db:
                lock(db)
                row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND checkout_id=?',(environment(),event['recurso_id'])).fetchone()
                if not row and event['referencia'] and event['referencia'].startswith('havo:'):
                    row = db.execute("SELECT * FROM saas_contratos WHERE id=? AND ambiente=? AND status IN ('criando','incerta')",(event['referencia'][5:],environment())).fetchone()
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
            if not sid:
                with banco() as db:
                    pix_row = db.execute("SELECT s.* FROM saas_contratos s JOIN saas_condicoes t ON t.id=s.id LEFT JOIN saas_cobrancas p ON p.contrato_id=s.id AND p.ambiente=s.ambiente WHERE s.ambiente=? AND t.oferta IN ('pix_60_v1','pix_90_v1') AND (s.checkout_id=? OR p.provedor_id=?) LIMIT 1",(environment(),payment.get('checkoutSession'),event['recurso_id'])).fetchone()
                if pix_row:
                    sync_contract(pix_row['id'],payment)
                    return
            if payment.get('deleted') and not sid:
                with banco() as db:
                    known = db.execute('SELECT p.*,s.assinatura_id,s.cliente_id FROM saas_cobrancas p JOIN saas_contratos s ON s.id=p.contrato_id AND s.ambiente=p.ambiente WHERE p.provedor_id=? AND p.ambiente=?',(event['recurso_id'],environment())).fetchone()
                if known:
                    payment = {'id':event['recurso_id'],'subscription':known['assinatura_id'],'customer':known['cliente_id'],
                               'value':known['valor_centavos']/100,'billingType':'CREDIT_CARD','dueDate':known['vencimento'],'deleted':True,'status':'DELETED'}
                    sid = known['assinatura_id']
            if not sid: return
            with banco() as db:
                row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND assinatura_id=?',(environment(),sid)).fetchone()
                if not row and payment.get('checkoutSession'):
                    row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND checkout_id=?',(environment(),payment['checkoutSession'])).fetchone()
            if not row:
                # Um evento de cobrança pode chegar antes do CHECKOUT_PAID.
                reconcile_pending()
                with banco() as db: row = db.execute('SELECT * FROM saas_contratos WHERE ambiente=? AND assinatura_id=?',(environment(),sid)).fetchone()
            if row: sync_contract(row['id'],payment)
        elif kind.startswith('SUBSCRIPTION_'):
            with banco() as db: row = db.execute('SELECT id FROM saas_contratos WHERE ambiente=? AND assinatura_id=?',(environment(),event['recurso_id'])).fetchone()
            if row: sync_contract(row['id'])
            else: reconcile_pending()

    def reconcile_pending():
        with banco() as db:
            rows = db.execute("SELECT id FROM saas_contratos WHERE ambiente=? AND checkout_id IS NOT NULL AND assinatura_id IS NULL AND status NOT IN ('cancelada','expirada') ORDER BY atualizado_em LIMIT 10",(environment(),)).fetchall()
        for row in rows: sync_contract(row['id'])

    def tick():
        if not enabled(): return
        now = int(time.time())
        with banco() as db:
            lock(db)
            events = [dict(r) for r in db.execute("SELECT * FROM saas_webhooks WHERE ambiente=? AND status IN ('pendente','processando') AND proxima_tentativa<=? ORDER BY criado_em LIMIT 10",(environment(),now)).fetchall()]
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
            stale = db.execute("SELECT id FROM saas_contratos WHERE ambiente=? AND checkout_id IS NOT NULL AND atualizado_em<? AND status NOT IN ('cancelada','expirada') ORDER BY atualizado_em LIMIT 5",(environment(),now-3600)).fetchall()
        for row in stale:
            try: sync_contract(row['id'])
            except Exception:
                with banco() as db: db.execute('UPDATE saas_contratos SET atualizado_em=?,erro=? WHERE id=?',(now,'Conferência pendente; tente sincronizar novamente.',row['id']))

    @app.post('/api/saas/webhook')
    async def webhook(request:Request,background:BackgroundTasks):
        secret = webhook_secret()
        if not enabled() or len(secret)<32 or secret == api_key():
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
            db.execute("INSERT INTO saas_webhooks(id,ambiente,tipo,recurso_id,referencia,status,tentativas,proxima_tentativa,criado_em) VALUES(?,?,?,?,?,'pendente',0,?,?) ON CONFLICT(id) DO NOTHING",(environment()+':'+eid,environment(),kind,rid,ref,int(time.time()),int(time.time())))
        background.add_task(tick)
        return {'recebido':True}

    @app.get('/api/saas/contratos/{cid}/pix')
    def pix_code(cid:str,request:Request):
        with banco() as db:
            user = owner(request,db)
            row = db.execute('SELECT * FROM saas_contratos WHERE id=? AND loja_id=? AND ambiente=?',(cid,user['loja_id'],environment())).fetchone()
            terms = db.execute('SELECT oferta FROM saas_condicoes WHERE id=? AND loja_id=? AND ambiente=?',(cid,user['loja_id'],environment())).fetchone()
            if not row or not terms or not terms['oferta'].startswith('pix_'): raise HTTPException(404,'PIX não encontrado.')
            c['limitar'](request,'asaas-pix-qr',20,60)
        sync_contract(cid)
        with banco() as db:
            row = db.execute('SELECT * FROM saas_contratos WHERE id=? AND loja_id=? AND ambiente=?',(cid,user['loja_id'],environment())).fetchone()
            payments = db.execute('SELECT * FROM saas_cobrancas WHERE contrato_id=? AND loja_id=? AND ambiente=?',(cid,user['loja_id'],environment())).fetchall()
        def result(data): return JSONResponse(data,headers={'Cache-Control':'no-store','Pragma':'no-cache'})
        if any(p['status'] in ('CONFIRMED','RECEIVED') for p in payments): return result({'situacao':'pago'})
        pending = [p for p in payments if p['status'] in ('PENDING','OVERDUE')]
        if not pending:
            return result({'situacao':'encerrado' if row['status'] in ('cancelada','expirada') else 'aguardando_dados'})
        if len(pending)!=1: raise HTTPException(409,'Cobrança PIX exige conferência.')
        p = api('GET','/payments/'+ident(pending[0]['provedor_id']))
        if p.get('deleted') or p.get('status') not in ('PENDING','OVERDUE'): return result({'situacao':'atualizar'})
        if p.get('checkoutSession')!=row['checkout_id'] or p.get('customer')!=row['cliente_id'] or p.get('billingType')!='PIX' or p.get('subscription') or cents(p.get('value'))!=row['valor_centavos']:
            raise HTTPException(409,'Vínculo PIX exige conferência.')
        qr = api('GET','/payments/'+ident(p['id'])+'/pixQrCode')
        payload = qr.get('payload')
        if not isinstance(payload,str) or not payload.startswith('000201') or not 30<=len(payload)<=4096 or not payload.isascii():
            raise HTTPException(502,'O Asaas ainda não disponibilizou um código PIX válido. Tente novamente.')
        expires = qr.get('expirationDate')
        try:
            expiry = datetime.fromisoformat(expires.replace('Z','+00:00'))
            if len(expires)==10: expiry=expiry.replace(hour=23,minute=59,second=59)
            if expiry.tzinfo is None: expiry=expiry.replace(tzinfo=c['BRASIL'])
        except (ValueError,TypeError,AttributeError): raise HTTPException(502,'Validade do PIX indisponível. Tente novamente.') from None
        if expiry<=datetime.now(c['BRASIL']): return result({'situacao':'expirado'})
        # Renderização local do MESMO código oficial. Nenhuma imagem externa,
        # chave genérica ou alteração no payload de pagamento.
        image=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=1,border=4)
        image.add_data(payload);image.make(fit=True)
        matrix=image.get_matrix()
        if len(matrix)>185: raise HTTPException(502,'Código PIX excede o limite de renderização.')
        return result({'situacao':'pendente','payload':payload,'matriz':matrix,'expira_em':expiry.isoformat(),'valor_centavos':row['valor_centavos']})

    @app.post('/api/saas/sincronizar')
    def sync_owner(request:Request):
        with banco() as db:
            user = owner(request,db,True)
            c['limitar'](request,'asaas-sync',12,3600)
            rows = db.execute("SELECT id FROM saas_contratos WHERE loja_id=? AND ambiente=? ORDER BY criado_em DESC LIMIT 10",(user['loja_id'],environment())).fetchall()
        tick()
        for row in rows: sync_contract(row['id'])
        return {'status':'sincronizado'}

    @app.post('/api/saas/contratos/{cid}/cancelar')
    def cancel(cid:str,request:Request):
        with banco() as db:
            user = owner(request,db,True)
            row = db.execute('SELECT * FROM saas_contratos WHERE id=? AND loja_id=? AND ambiente=?',(cid,user['loja_id'],environment())).fetchone()
            if not row: raise HTTPException(404,'Contrato não encontrado.')
            if row['status'] == 'cancelada' and row['ambiente'] == 'sandbox': return {'status':'cancelada'}
            row = dict(row)
            if row['ambiente'] == 'production' and row['assinatura_id'] and row['status'] != 'cancelada':
                db.execute("UPDATE saas_contratos SET status='cancelando',atualizado_em=? WHERE id=?",(int(time.time()),cid))
                audit(db,row,user['id'],'cancelamento_solicitado')
        if row['assinatura_id']:
            api('PUT','/subscriptions/'+ident(row['assinatura_id']),{'status':'INACTIVE'})
            if row['ambiente'] == 'production':
                # INACTIVE não cancela cobranças já emitidas pelo Asaas. Retirar
                # somente pendências FUTURAS para não debitar após cancelamento.
                today = datetime.now(c['BRASIL']).date().isoformat()
                for offset in range(0,1000,100):
                    page = api('GET','/subscriptions/'+ident(row['assinatura_id'])+'/payments?'+urllib.parse.urlencode({'limit':100,'offset':offset}))
                    for p in page.get('data',[]):
                        if p.get('subscription') != row['assinatura_id'] or p.get('customer') != row['cliente_id']:
                            raise HTTPException(502,'Vínculo da cobrança exige conferência.')
                        if p.get('status') in ('PENDING','OVERDUE','CREDIT_CARD_CAPTURE_REFUSED') and p.get('dueDate','') > today and not p.get('deleted'):
                            pid = ident(p['id'])
                            api('DELETE','/payments/'+pid)
                            removed = api('GET','/payments/'+pid)
                            if not removed.get('deleted'):
                                raise HTTPException(502,'Cancelamento de mensalidade futura ainda não confirmado.')
                            sync_contract(cid,{**p,'deleted':True,'status':'DELETED'})
                    if not page.get('hasMore'): break
            sync_contract(cid)
            with banco() as db:
                verified = db.execute('SELECT status FROM saas_contratos WHERE id=?',(cid,)).fetchone()
                confirmed_cancel = api('GET','/subscriptions/'+ident(row['assinatura_id'])) if row['ambiente'] == 'production' else None
                if not verified or (row['ambiente'] == 'production' and not (confirmed_cancel.get('deleted') or confirmed_cancel.get('status') == 'INACTIVE')) or (row['ambiente'] == 'sandbox' and verified['status'] != 'cancelada'):
                    raise HTTPException(502,'O Asaas ainda não confirmou o cancelamento. Sincronize antes de repetir.')
        elif row['checkout_id']:
            api('POST','/checkouts/'+ident(row['checkout_id'])+'/cancel')
            with banco() as db: terms = db.execute('SELECT oferta FROM saas_condicoes WHERE id=?',(cid,)).fetchone()
            if terms and terms['oferta'].startswith('pix_'):
                sync_contract(cid)
                with banco() as db:
                    pending_pix = db.execute("SELECT provedor_id FROM saas_cobrancas WHERE contrato_id=? AND ambiente=? AND status IN ('PENDING','OVERDUE')",(cid,row['ambiente'])).fetchall()
                for p in pending_pix:
                    pid = ident(p['provedor_id'])
                    canonical = api('GET','/payments/'+pid)
                    if canonical.get('checkoutSession') != row['checkout_id']: raise HTTPException(502,'Vínculo PIX exige conferência.')
                    if canonical.get('status') in ('PENDING','OVERDUE'):
                        api('DELETE','/payments/'+pid)
                        if not api('GET','/payments/'+pid).get('deleted'): raise HTTPException(502,'Cancelamento PIX não confirmado.')
                sync_contract(cid)
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

    @app.post('/api/gestao/asaas/{cid}/encerrar-rejeitada')
    def reject_confirmed(cid:str,request:Request):
        # Exceção operacional SOMENTE Sandbox: administrador conferiu HTTP 400
        # nos logs privados do Asaas. Nunca inferir rejeição a partir de timeout.
        with banco() as db:
            user = c['administrador'](request,db,True)
            if not enabled() or environment() != 'sandbox': raise HTTPException(503,'Exceção disponível somente no Sandbox.')
            lock(db)
            row = db.execute("SELECT * FROM saas_contratos WHERE id=? AND ambiente='sandbox'",(cid,)).fetchone()
            if not row: raise HTTPException(404,'Tentativa não encontrada.')
            if row['checkout_id'] or row['assinatura_id'] or row['status'] not in ('incerta','expirada'):
                raise HTTPException(409,'Somente tentativa incerta sem checkout pode ser encerrada após conferência.')
            if row['status']=='expirada': return {'status':'expirada'}
            db.execute("UPDATE saas_contratos SET status='expirada',erro=?,atualizado_em=? WHERE id=?",
                       ('Administrador confirmou rejeição HTTP 400 nos logs do Asaas.',int(time.time()),cid))
            audit(db,row,user['id'],'rejeicao_http400_conferida_manualmente')
        return {'status':'expirada'}

    @app.get('/api/gestao/asaas')
    def admin_report(request:Request):
        with banco() as db:
            c['administrador'](request,db)
            rows = db.execute("SELECT s.*,u.email,l.slug FROM saas_contratos s JOIN lojas l ON l.id=s.loja_id JOIN usuarios u ON u.id=s.usuario_id AND u.loja_id=s.loja_id WHERE s.ambiente=? ORDER BY s.criado_em DESC LIMIT 200",(environment() or 'sandbox',)).fetchall()
            pending = db.execute("SELECT COUNT(*) AS n FROM saas_webhooks WHERE ambiente=? AND status!='processado'",(environment() or 'sandbox',)).fetchone()['n']
            totals = db.execute("SELECT COALESCE(SUM(valor_centavos),0) AS total FROM saas_cobrancas WHERE ambiente=? AND status IN ('RECEIVED','CONFIRMED')",('production',)).fetchone()['total']
        return {'ambiente':environment() or 'sandbox','eventos_pendentes':pending,'contratos':[contract_view(r)|{'email':r['email'],'slug':r['slug']} for r in rows],
                'receita_real_centavos':totals,'observacao':'Sandbox não libera acesso real. Receita real considera somente pagamentos confirmados de produção; não é MRR.'}

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
