"""Central e Web Push: eventos transacionais, dispositivos e fila com leases."""
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from fastapi import BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

DDL = {
 'notificacao_preferencias': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,usuario_id TEXT NOT NULL,novos INTEGER NOT NULL,cancelamentos INTEGER NOT NULL,reagendamentos INTEGER NOT NULL,lembretes INTEGER NOT NULL,equipe INTEGER NOT NULL,minutos INTEGER NOT NULL,UNIQUE(loja_id,usuario_id)',
 'notificacao_eventos': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,agendamento_id BIGINT NOT NULL,tipo TEXT NOT NULL,revisao BIGINT NOT NULL,criado_em BIGINT NOT NULL,UNIQUE(loja_id,agendamento_id,tipo,revisao)',
 'notificacao_revisoes': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,agendamento_id BIGINT NOT NULL,revisao BIGINT NOT NULL,UNIQUE(loja_id,agendamento_id)',
 'notificacoes': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,usuario_id TEXT NOT NULL,agendamento_id BIGINT NOT NULL,evento_id TEXT NOT NULL,tipo TEXT NOT NULL,dados TEXT NOT NULL,criado_em BIGINT NOT NULL,lida_em BIGINT,UNIQUE(evento_id,usuario_id)',
 'push_dispositivos': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,usuario_id TEXT NOT NULL,endpoint_hash TEXT UNIQUE NOT NULL,assinatura TEXT NOT NULL,ativo INTEGER NOT NULL,criado_em BIGINT NOT NULL,atualizado_em BIGINT NOT NULL',
 'push_entregas': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,usuario_id TEXT NOT NULL,notificacao_id TEXT NOT NULL,dispositivo_id TEXT NOT NULL,status TEXT NOT NULL,tentativas INTEGER NOT NULL,proxima BIGINT NOT NULL,lease TEXT,UNIQUE(notificacao_id,dispositivo_id)'
}
TABLES={name:[part.strip().split()[0] for part in ddl.split(',') if not part.strip().startswith('UNIQUE') and ')' not in part] for name,ddl in DDL.items()}
INDEXES=[
 'CREATE INDEX IF NOT EXISTS notificacoes_conta ON notificacoes(loja_id,usuario_id,criado_em)',
 'CREATE INDEX IF NOT EXISTS push_fila ON push_entregas(status,proxima)',
 'CREATE INDEX IF NOT EXISTS push_conta ON push_dispositivos(loja_id,usuario_id,ativo)',
 'CREATE INDEX IF NOT EXISTS agenda_lembretes ON agendamentos(status,inicio)'
]
DEVICE_COOKIE='barber_push_device'
FLAGS={'novo':'novos','cancelado':'cancelamentos','reagendado':'reagendamentos','lembrete':'lembretes'}
TITLES={'novo':'Novo agendamento ✂️','cancelado':'Agendamento cancelado','reagendado':'Horário reagendado 🔄','lembrete':'Próximo atendimento ⏰'}

class Preferencias(BaseModel):
    novos: bool = Field(default=True,strict=True)
    cancelamentos: bool = Field(default=True,strict=True)
    reagendamentos: bool = Field(default=True,strict=True)
    lembretes: bool = Field(default=False,strict=True)
    equipe: bool = Field(default=False,strict=True)
    minutos: int = Field(default=30,ge=5,le=120,strict=True)

class Dispositivo(BaseModel):
    endpoint: str = Field(min_length=10,max_length=2048)
    keys: dict[str,str]
    expirationTime: int | None = None

def decode(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',value): raise ValueError('base64')
    return base64.urlsafe_b64decode(value+'='*((-len(value))%4))

def validar(data):
    u=urlsplit(data['endpoint'])
    host=(u.hostname or '').lower()
    trusted=host=='fcm.googleapis.com' or host=='updates.push.services.mozilla.com' or host.endswith('.push.services.mozilla.com') or host=='web.push.apple.com' or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
    if u.scheme!='https' or not trusted or u.username or u.password or u.port not in (None,443) or u.fragment: raise ValueError('endpoint')
    if set(data['keys'])!={'p256dh','auth'}: raise ValueError('keys')
    if any(len(v)>100 for v in data['keys'].values()): raise ValueError('keys')
    point=decode(data['keys']['p256dh'])
    if len(point)!=65 or len(decode(data['keys']['auth']))!=16: raise ValueError('keys')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),point)
    if data.get('expirationTime') is not None and data['expirationTime']<time.time()*1000: raise ValueError('expired')
    return data

def vapid():
    private=os.environ.get('WEB_PUSH_VAPID_PRIVATE_KEY','')
    public=os.environ.get('WEB_PUSH_VAPID_PUBLIC_KEY','')
    subject=os.environ.get('WEB_PUSH_VAPID_SUBJECT','')
    try:
        raw=decode(private)
        if len(raw)!=32: return None
        key=ec.derive_private_key(int.from_bytes(raw,'big'),ec.SECP256R1())
        actual=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        if decode(public)!=actual or not subject.startswith('mailto:') or '@' not in subject: return None
        return private,public,subject
    except Exception: return None

def instalar(app,c):
    banco=c['banco']
    with banco() as db:
        for name,ddl in DDL.items(): db.execute('CREATE TABLE IF NOT EXISTS '+name+' ('+ddl+')')
        for sql in INDEXES: db.execute(sql)

    def lock(db):
        if c['DATABASE_URL']: db.execute('SELECT pg_advisory_xact_lock(?)',(7821649,))
        else: db.execute('BEGIN IMMEDIATE')

    def prefs(db,u):
        row=db.execute('SELECT * FROM notificacao_preferencias WHERE loja_id=? AND usuario_id=?',(u['loja_id'],u['id'])).fetchone()
        return dict(row) if row else dict(novos=1,cancelamentos=1,reagendamentos=1,lembretes=0,equipe=0,minutos=30)

    def conta(db,shop,uid):
        r=db.execute("SELECT id,loja_id,'' AS barbeiro_id,'dono' AS papel FROM usuarios WHERE loja_id=? AND id=?",(shop,uid)).fetchone()
        if not r:
            r=db.execute("SELECT id,loja_id,barbeiro_id,'barbeiro' AS papel FROM funcionarios WHERE loja_id=? AND id=? AND ativo=1",(shop,uid)).fetchone()
            if r and not any(b['id']==r['barbeiro_id'] for b in c['config_da_loja'](db,shop)['barbeiros']): return None
        return dict(r) if r else None

    def permite(db,u,a,tipo):
        if not u or u['loja_id']!=a['loja_id']: return False
        p=prefs(db,u)
        return bool(p[FLAGS[tipo]] and ((u['papel']=='barbeiro' and u['barbeiro_id']==a['barbeiro_id']) or (u['papel']=='dono' and p['equipe'])))

    def dados(a,tipo,minutos=30):
        start=datetime.fromisoformat(a['inicio'])
        if start.tzinfo is None: start=start.replace(tzinfo=c['BRASIL'])
        days=(start.date()-datetime.now(c['BRASIL']).date()).days
        day='hoje' if days==0 else 'amanhã' if days==1 else start.strftime('%d/%m/%Y')
        when=day+' às '+start.strftime('%H:%M')
        name=a['cliente_nome'];service=a['servico_nome']
        body={'novo':f'{name} agendou {service} para {when}.','cancelado':f'O horário de {service} com {name}, {when}, foi cancelado.','reagendado':f'O agendamento de {name} foi alterado para {when}.','lembrete':f'Seu atendimento com {name} começa em {minutos} minutos.'}[tipo]
        return dict(titulo=TITLES[tipo],mensagem=body,cliente=name,servico=service,profissional=a['barbeiro_nome'],inicio=a['inicio'])

    def emitir(db,a,tipo,revisao=None,somente=None):
        a=dict(a);shop=a['loja_id'];aid=a['id'];now=int(time.time())
        if revisao is None:
            rid=shop+':'+str(aid)
            db.execute('INSERT INTO notificacao_revisoes(id,loja_id,agendamento_id,revisao) VALUES(?,?,?,0) ON CONFLICT(id) DO NOTHING',(rid,shop,aid))
            db.execute('UPDATE notificacao_revisoes SET revisao=revisao+1 WHERE id=?',(rid,))
            revisao=db.execute('SELECT revisao FROM notificacao_revisoes WHERE id=?',(rid,)).fetchone()['revisao']
        eid=hashlib.sha256(f'{shop}:{aid}:{tipo}:{revisao}:{somente or ""}'.encode()).hexdigest()
        created=db.execute('INSERT INTO notificacao_eventos(id,loja_id,agendamento_id,tipo,revisao,criado_em) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',(eid,shop,aid,tipo,revisao,now))
        if not created.rowcount: return
        accounts=[dict(r) for r in db.execute("SELECT id,loja_id,'' AS barbeiro_id,'dono' AS papel FROM usuarios WHERE loja_id=? UNION ALL SELECT id,loja_id,barbeiro_id,'barbeiro' AS papel FROM funcionarios WHERE loja_id=? AND barbeiro_id=? AND ativo=1",(shop,shop,a['barbeiro_id'])).fetchall()]
        for u in accounts:
            if somente and u['id']!=somente: continue
            if not permite(db,conta(db,shop,u['id']),a,tipo): continue
            nid=hashlib.sha256((eid+':'+u['id']).encode()).hexdigest()
            payload=dados(a,tipo,prefs(db,u)['minutos'])
            db.execute('INSERT INTO notificacoes(id,loja_id,usuario_id,agendamento_id,evento_id,tipo,dados,criado_em,lida_em) VALUES(?,?,?,?,?,?,?,?,NULL) ON CONFLICT(id) DO NOTHING',(nid,shop,u['id'],aid,eid,tipo,json.dumps(payload,ensure_ascii=False),now))
            for d in db.execute('SELECT id FROM push_dispositivos WHERE loja_id=? AND usuario_id=? AND ativo=1',(shop,u['id'])).fetchall():
                did=hashlib.sha256((nid+':'+d['id']).encode()).hexdigest()
                db.execute("INSERT INTO push_entregas(id,loja_id,usuario_id,notificacao_id,dispositivo_id,status,tentativas,proxima,lease) VALUES(?,?,?,?,?,'pendente',0,?,NULL) ON CONFLICT(id) DO NOTHING",(did,shop,u['id'],nid,d['id'],now))

    def enviar(subscription,payload):
        from pywebpush import webpush
        import requests
        class Session(requests.Session):
            def request(self,*args,**kwargs):
                kwargs['allow_redirects']=False
                return super().request(*args,**kwargs)
        keys=vapid()
        with Session() as session:
            r=webpush(subscription_info=validar(subscription),data=json.dumps(payload,ensure_ascii=False),vapid_private_key=keys[0],vapid_claims={'sub':keys[2]},ttl=3600,timeout=8,requests_session=session,headers={'Urgency':'high'})
            if not 200<=r.status_code<300: raise RuntimeError('provider')
    c['push_enviar']=enviar

    def dispatch():
        if not vapid(): return
        # Bounded batch; no network I/O occurs in a booking transaction.
        for _ in range(25):
            now=int(time.time());lease=secrets.token_hex(16)
            with banco() as db:
                lock(db)
                r=db.execute("SELECT * FROM push_entregas WHERE status IN ('pendente','enviando') AND proxima<=? ORDER BY proxima,id LIMIT 1",(now,)).fetchone()
                if not r: return
                j=dict(r)
                db.execute("UPDATE push_entregas SET status='enviando',lease=?,tentativas=tentativas+1,proxima=? WHERE id=?",(lease,now+300,j['id']))
                d=db.execute('SELECT * FROM push_dispositivos WHERE id=? AND loja_id=? AND usuario_id=? AND ativo=1',(j['dispositivo_id'],j['loja_id'],j['usuario_id'])).fetchone()
                n=db.execute('SELECT * FROM notificacoes WHERE id=? AND loja_id=? AND usuario_id=?',(j['notificacao_id'],j['loja_id'],j['usuario_id'])).fetchone()
                a=db.execute('SELECT * FROM agendamentos WHERE id=? AND loja_id=?',(n['agendamento_id'],j['loja_id'])).fetchone() if n else None
                valid=bool(d and n and a and permite(db,conta(db,j['loja_id'],j['usuario_id']),a,n['tipo']))
                if valid and n['tipo']=='lembrete':
                    valid=a['status']=='agendado' and a['inicio']==json.loads(n['dados'])['inicio']
                if not valid:
                    db.execute("UPDATE push_entregas SET status='descartada',lease=NULL WHERE id=?",(j['id'],))
                    continue
                d=dict(d);n=dict(n)
            status='enviada';expired=False
            try:
                payload=json.loads(n['dados'])
                payload.update(id=n['id'],agendamento_id=n['agendamento_id'],conta=j['loja_id']+':'+j['usuario_id'])
                c['push_enviar'](json.loads(d['assinatura']),payload)
            except Exception as e:
                response=getattr(e,'response',None)
                code=getattr(response,'status_code',None)
                expired=code in (404,410)
                status='invalida' if expired else 'falhou' if j['tentativas']+1>=8 else 'pendente'
            with banco() as db:
                if expired: db.execute('UPDATE push_dispositivos SET ativo=0 WHERE id=? AND loja_id=? AND usuario_id=?',(d['id'],j['loja_id'],j['usuario_id']))
                delay=min(3600,30*2**j['tentativas'])
                db.execute('UPDATE push_entregas SET status=?,proxima=?,lease=NULL WHERE id=? AND lease=?',(status,int(time.time())+delay,j['id'],lease))

    def tick():
        # Backend scan, once per minute, only appointments in the next two hours.
        now=datetime.now(c['BRASIL']);end=now+timedelta(minutes=120)
        with banco() as db:
            lock(db)
            candidates=db.execute("SELECT * FROM agendamentos WHERE status='agendado' AND inicio>=? AND inicio<=? ORDER BY inicio LIMIT 500",(now.isoformat(timespec='minutes'),end.isoformat(timespec='minutes'))).fetchall()
            for a in candidates:
                accounts=db.execute('SELECT usuario_id,minutos FROM notificacao_preferencias WHERE loja_id=? AND lembretes=1',(a['loja_id'],)).fetchall()
                for p in accounts:
                    start=datetime.fromisoformat(a['inicio'])
                    if start.tzinfo is None:start=start.replace(tzinfo=c['BRASIL'])
                    seconds=(start-now).total_seconds()
                    if not p['minutos']*60-90<=seconds<=p['minutos']*60: continue
                    key=int.from_bytes(hashlib.sha256((a['inicio']+':'+p['usuario_id']+':'+str(p['minutos'])).encode()).digest()[:7],'big')
                    emitir(db,a,'lembrete',revisao=key,somente=p['usuario_id'])
        dispatch()

    async def worker():
        while True:
            try: await asyncio.to_thread(tick)
            except Exception: pass # No credentials/endpoint/personal data in logs.
            await asyncio.sleep(60)

    @app.on_event('startup')
    async def start_worker():
        app.state.push_worker=asyncio.create_task(worker())

    @app.on_event('shutdown')
    async def stop_worker():
        task=getattr(app.state,'push_worker',None)
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass

    c['notificar_evento']=emitir;c['push_dispatch']=dispatch;c['push_tick']=tick
    def logout_device(db,request,u):
        db.execute('UPDATE push_dispositivos SET ativo=0 WHERE id=? AND loja_id=? AND usuario_id=?',(request.cookies.get(DEVICE_COOKIE,''),u['loja_id'],u['id']))
    c['push_logout']=logout_device

    @app.get('/notifications.js')
    def script():return FileResponse(c['ROOT']/'notifications.js',media_type='application/javascript')

    @app.get('/api/notificacoes/config')
    def configurar(request:Request):
        with banco() as db:
            u=c['usuario'](request,db)
            p=prefs(db,u)
            d=db.execute('SELECT id FROM push_dispositivos WHERE id=? AND loja_id=? AND usuario_id=? AND ativo=1',(request.cookies.get(DEVICE_COOKIE,''),u['loja_id'],u['id'])).fetchone()
            k=vapid()
            return {**{x:bool(p[x]) for x in ('novos','cancelamentos','reagendamentos','lembretes','equipe')},'minutos':p['minutos'],'gestor':u['papel']=='dono','public_key':k[1] if k else None,'conta':u['loja_id']+':'+u['id'],'dispositivo_ativo':bool(d),'lembretes_continuos':os.environ.get('PUSH_ALWAYS_ON','').lower()=='true'}

    @app.put('/api/notificacoes/config')
    def salvar(data:Preferencias,request:Request):
        with banco() as db:
            u=c['usuario'](request,db,True)
            if u['papel']!='dono' and data.equipe:raise HTTPException(403,'Apenas o dono pode receber avisos de toda a equipe.')
            values=[u['loja_id']+':'+u['id'],u['loja_id'],u['id']]+[int(getattr(data,x)) for x in ('novos','cancelamentos','reagendamentos','lembretes','equipe','minutos')]
            db.execute('INSERT INTO notificacao_preferencias(id,loja_id,usuario_id,novos,cancelamentos,reagendamentos,lembretes,equipe,minutos) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET novos=excluded.novos,cancelamentos=excluded.cancelamentos,reagendamentos=excluded.reagendamentos,lembretes=excluded.lembretes,equipe=excluded.equipe,minutos=excluded.minutos',values)
        return {'status':'ok'}

    @app.post('/api/notificacoes/dispositivos')
    def registrar(data:Dispositivo,request:Request,response:Response):
        c['limitar'](request,'push-dispositivo',30,3600)
        try: subscription=validar(data.model_dump())
        except Exception:raise HTTPException(422,'Assinatura de notificações inválida.')
        with banco() as db:
            lock(db);u=c['usuario'](request,db,True)
            if not vapid():raise HTTPException(503,'O envio de notificações ainda precisa ser configurado pelo administrador.')
            digest=hashlib.sha256(data.endpoint.encode()).hexdigest()
            old=db.execute('SELECT * FROM push_dispositivos WHERE endpoint_hash=?',(digest,)).fetchone()
            if old and (old['loja_id']!=u['loja_id'] or old['usuario_id']!=u['id']):raise HTTPException(409,'Desative a assinatura antiga deste navegador e tente novamente.')
            if old and old['assinatura']!=json.dumps(subscription):raise HTTPException(409,'Assinatura alterada. Reative as notificações neste navegador.')
            if not old and db.execute('SELECT COUNT(*) AS n FROM push_dispositivos WHERE loja_id=? AND usuario_id=? AND ativo=1',(u['loja_id'],u['id'])).fetchone()['n']>=10:raise HTTPException(409,'Limite de 10 dispositivos. Desative um dispositivo antigo.')
            did=old['id'] if old else secrets.token_hex(24);now=int(time.time())
            db.execute('INSERT INTO push_dispositivos(id,loja_id,usuario_id,endpoint_hash,assinatura,ativo,criado_em,atualizado_em) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(id) DO UPDATE SET ativo=1,atualizado_em=excluded.atualizado_em',(did,u['loja_id'],u['id'],digest,json.dumps(subscription),now,now))
            response.set_cookie(DEVICE_COOKIE,did,httponly=True,secure=c['CLOUD'],samesite='lax',max_age=31536000,path='/')
        return {'status':'ativado'}

    @app.delete('/api/notificacoes/dispositivos/atual')
    def remover(request:Request,response:Response):
        with banco() as db:
            u=c['usuario'](request,db,True);logout_device(db,request,u)
        response.delete_cookie(DEVICE_COOKIE,path='/')
        return {'status':'desativado'}

    @app.get('/api/notificacoes')
    def listar(request:Request,offset:int=0):
        if offset<0 or offset>100000:raise HTTPException(422,'Página inválida.')
        with banco() as db:
            u=c['usuario'](request,db);args=(u['loja_id'],u['id'])
            count=db.execute('SELECT COUNT(*) AS n FROM notificacoes WHERE loja_id=? AND usuario_id=? AND lida_em IS NULL',args).fetchone()['n']
            rows=db.execute('SELECT * FROM notificacoes WHERE loja_id=? AND usuario_id=? ORDER BY criado_em DESC,id DESC LIMIT 50 OFFSET ?',(*args,offset)).fetchall()
        return {'conta':u['loja_id']+':'+u['id'],'nao_lidas':count,'itens':[{k:r[k] for k in ('id','tipo','agendamento_id','criado_em','lida_em')}|json.loads(r['dados']) for r in rows]}

    @app.post('/api/notificacoes/lidas')
    def ler_todas(request:Request):
        with banco() as db:
            u=c['usuario'](request,db,True)
            db.execute('UPDATE notificacoes SET lida_em=? WHERE loja_id=? AND usuario_id=? AND lida_em IS NULL',(int(time.time()),u['loja_id'],u['id']))
        return {'status':'ok'}

    @app.post('/api/notificacoes/{nid}/lida')
    def ler(nid:str,request:Request):
        with banco() as db:
            u=c['usuario'](request,db,True)
            r=db.execute('UPDATE notificacoes SET lida_em=COALESCE(lida_em,?) WHERE id=? AND loja_id=? AND usuario_id=?',(int(time.time()),nid,u['loja_id'],u['id']))
            if not r.rowcount:raise HTTPException(404,'Notificação não encontrada.')
        return {'status':'ok'}
