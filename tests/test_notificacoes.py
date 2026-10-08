"""Push em banco descartável: nunca envia notificações reais nem acessa produção."""
import os,tempfile,importlib.util,json,secrets,hashlib
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64
ROOT=Path(__file__).resolve().parents[1]
enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
key=ec.generate_private_key(ec.SECP256R1())
private=enc(key.private_numbers().private_value.to_bytes(32,'big'))
public=enc(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))
os.environ.update(WEB_PUSH_VAPID_PRIVATE_KEY=private,WEB_PUSH_VAPID_PUBLIC_KEY=public,WEB_PUSH_VAPID_SUBJECT='mailto:test@example.com',BILLING_ENABLED='false')
dsn=os.environ.get('PUSH_TEST_DATABASE_URL');schema=None
if dsn:
    assert urlsplit(dsn).hostname in ('127.0.0.1','localhost')
    import psycopg
    schema='push_test_'+secrets.token_hex(6)
    with psycopg.connect(dsn) as db:db.execute('CREATE SCHEMA '+schema)
    dsn+=('&' if '?' in dsn else '?')+'options=-csearch_path%3D'+schema
with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'push.db')
    for n in ('RENDER','ADMIN_EMAILS','BREVO_API_KEY','RESEND_API_KEY'):os.environ.pop(n,None)
    if dsn:os.environ['DATABASE_URL']=dsn
    else:os.environ.pop('DATABASE_URL',None)
    spec=importlib.util.spec_from_file_location('push_test_app',ROOT/'app.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    from notificacoes import validar,DDL,TABLES
    assert all(TABLES[t] and len(TABLES[t])==len(set(TABLES[t])) for t in DDL)
    owner,other,staff,staff2,guest=[TestClient(m.app) for _ in range(5)]
    password='SenhaTeste!12345'
    def create(c,n):
        r=c.post('/api/cadastro',json={'aceite_termos':True,'email':n+'@example.com','nome':n,'slug':n,'senha':password});assert r.status_code==201,r.text
        h={'X-CSRF-Token':r.json()['csrf']}
        cfg=c.get('/api/configuracao').json()
        cfg.update(barbeiros=[{'id':'prof','nome':'Carlos'},{'id':'outro','nome':'Bruno'}],servicos=[{'id':'corte','nome':'Corte + Barba','duracao':30,'preco':40}],dias=list(range(7)),periodos=[{'inicio':'08:00','fim':'20:00'}],intervalo=30)
        assert c.put('/api/configuracao',json=cfg,headers=h).status_code==200
        return h
    oh=create(owner,'push-a');xh=create(other,'push-b')
    def invite(c,b,email):
        r=owner.post('/api/equipe/'+b+'/convite',headers=oh,json={'email':email});assert r.status_code==201,r.text
        r=c.post('/api/convite/aceitar',json={'token':r.json()['link'].split('#')[1],'senha':password});assert r.status_code==201,r.text
        return {'X-CSRF-Token':r.json()['csrf']}
    sh=invite(staff,'prof','staff@example.com');s2h=invite(staff2,'outro','staff2@example.com')
    settings=owner.get('/api/notificacoes/config').json()
    assert settings['public_key']==public and not settings['equipe']
    assert 'PRIVATE' not in json.dumps(settings)
    pref={x:settings[x] for x in ('novos','cancelamentos','reagendamentos','lembretes','equipe','minutos')}
    assert staff.put('/api/notificacoes/config',headers=sh,json={**pref,'equipe':True}).status_code==403
    assert owner.put('/api/notificacoes/config',json=pref).status_code==403
    pref['equipe']=True
    assert owner.put('/api/notificacoes/config',headers=oh,json=pref).status_code==200
    sub=lambda n:{'endpoint':'https://fcm.googleapis.com/fcm/send/'+n,'keys':{'p256dh':public,'auth':enc(b'a'*16)},'expirationTime':None}
    assert guest.post('/api/notificacoes/dispositivos',json=sub('g')).status_code==401
    assert staff.post('/api/notificacoes/dispositivos',json=sub('s')).status_code==403
    for bad in ('http://fcm.googleapis.com/x','https://127.0.0.1/x','https://fcm.googleapis.com.evil.test/x','https://evil.test/x','https://fcm.googleapis.com@evil.test/x'):
        assert staff.post('/api/notificacoes/dispositivos',headers=sh,json={**sub('s'),'endpoint':bad}).status_code==422
    assert staff.post('/api/notificacoes/dispositivos',headers=sh,json={**sub('s'),'keys':{'p256dh':'bad','auth':'bad'}}).status_code==422
    sent=[]
    def send(s,p):
        # The booking and its internal notification are already committed.
        with m.banco() as db:
            assert db.execute('SELECT id FROM agendamentos WHERE id=?',(p['agendamento_id'],)).fetchone()
            assert db.execute('SELECT id FROM notificacoes WHERE id=?',(p['id'],)).fetchone()
        sent.append((s['endpoint'],p))
    # Exercise actual encryption/VAPID and transport without network or live credentials.
    real_send=m.push_enviar
    from unittest.mock import patch
    import requests
    captured=[]
    def transport(self,method,url,**kwargs):
        captured.append((method,url,kwargs))
        response=requests.Response();response.status_code=201;return response
    with patch.object(requests.Session,'request',transport):
        real_send(sub('crypto'),{'id':'a'*64,'mensagem':'Texto privado'})
    assert captured and captured[0][2]['allow_redirects'] is False
    assert captured[0][2]['headers']['content-encoding']=='aes128gcm'
    assert b'Texto privado' not in captured[0][2]['data']
    assert captured[0][2]['timeout']==8
    m.push_enviar=send
    for c,h,n in ((owner,oh,'owner'),(other,xh,'other'),(staff,sh,'s1'),(staff2,s2h,'s2')):
        assert c.post('/api/notificacoes/dispositivos',headers=h,json=sub(n)).status_code==200
    assert other.post('/api/notificacoes/dispositivos',headers=xh,json=sub('s1')).status_code==409
    device2=TestClient(m.app)
    r=device2.post('/api/login',json={'email':'staff@example.com','senha':password});assert r.status_code==200
    d2h={'X-CSRF-Token':r.json()['csrf']}
    assert device2.post('/api/notificacoes/dispositivos',headers=d2h,json=sub('s3')).status_code==200
    day=(datetime.now(m.BRASIL)+timedelta(days=1)).date().isoformat()
    body={'cliente_nome':'João','cliente_telefone':'11900000000','barbeiro_id':'prof','servico_id':'corte','data':day,'horario':'09:00'}
    r=guest.post('/api/publico/push-a/agendamentos',json=body);assert r.status_code==201,r.text
    booking=r.json();aid=booking['agendamento_id']
    assert {e.rsplit('/',1)[-1] for e,p in sent}=={'owner','s1','s3'},sent
    assert all(p['agendamento_id']==aid for e,p in sent)
    assert staff2.get('/api/notificacoes').json()['itens']==[]
    assert other.get('/api/notificacoes').json()['itens']==[]
    central=staff.get('/api/notificacoes').json();assert central['nao_lidas']==1
    nid=central['itens'][0]['id']
    assert other.post('/api/notificacoes/'+nid+'/lida',headers=xh).status_code==404
    assert staff2.post('/api/notificacoes/'+nid+'/lida',headers=s2h).status_code==404
    assert staff.post('/api/notificacoes/'+nid+'/lida',headers=sh).status_code==200
    assert staff.get('/api/notificacoes').json()['nao_lidas']==0
    assert guest.post('/api/publico/push-a/agendamentos',json=body).status_code==409
    m.push_dispatch();assert len(sent)==3
    token=booking['link_gerenciar'].split('#')[1]
    change={'token':token,'acao':'reagendar','data':day,'horario':'10:00'}
    assert guest.post('/api/cliente/alterar',json=change).status_code==200
    assert len(sent)==6
    assert guest.post('/api/cliente/alterar',json=change).status_code==200
    assert len(sent)==6 # A no-op move is not an event.
    assert guest.post('/api/cliente/alterar',json={'token':token,'acao':'cancelar'}).status_code==200
    assert len(sent)==9 and sent[-1][1]['titulo']=='Agendamento cancelado'
    assert guest.post('/api/cliente/alterar',json={'token':token,'acao':'cancelar'}).status_code==200
    assert len(sent)==9
    assert staff.post('/api/notificacoes/lidas',headers=sh).status_code==200
    assert staff.get('/api/notificacoes').json()['nao_lidas']==0
    # Network/provider failures are isolated and retryable.
    def broken(*_):raise RuntimeError('network unavailable')
    m.push_enviar=broken
    r=guest.post('/api/publico/push-a/agendamentos',json={**body,'horario':'11:00'});assert r.status_code==201,r.text
    assert len(staff.get('/api/notificacoes').json()['itens'])==4
    with m.banco() as db:db.execute("UPDATE push_entregas SET proxima=0 WHERE status='pendente'")
    from pywebpush import WebPushException
    import requests
    response=requests.Response();response.status_code=410
    m.push_enviar=lambda *_:(_ for _ in ()).throw(WebPushException('expired',response=response))
    m.push_dispatch()
    assert not staff.get('/api/notificacoes/config').json()['dispositivo_ativo']
    assert len(owner.get('/api/agendamentos').json())==2
    # Concurrent retries claim each delivery once; both devices remain independent.
    for c,h,n in ((owner,oh,'owner'),(staff,sh,'s1'),(device2,d2h,'s3')):
        assert c.post('/api/notificacoes/dispositivos',headers=h,json=sub(n)).status_code==200
    m.push_enviar=send
    os.environ.pop('WEB_PUSH_VAPID_PRIVATE_KEY')
    r=guest.post('/api/publico/push-a/agendamentos',json={**body,'horario':'12:00'});assert r.status_code==201
    before=len(sent);os.environ['WEB_PUSH_VAPID_PRIVATE_KEY']=private
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(lambda _:m.push_dispatch(),range(3)))
    assert len(sent)==before+3
    pref['equipe']=False
    assert owner.put('/api/notificacoes/config',headers=oh,json=pref).status_code==200
    before=len(sent)
    assert guest.post('/api/publico/push-a/agendamentos',json={**body,'horario':'13:00'}).status_code==201
    assert len(sent)==before+2 and all(not e.endswith('/owner') for e,p in sent[before:])
    # Logout disables this browser only, not the account's other device.
    assert staff.post('/api/logout',headers=sh).status_code==200
    assert staff.get('/api/notificacoes').status_code==401
    assert device2.get('/api/notificacoes/config').json()['dispositivo_ativo']
    before=len(sent)
    assert guest.post('/api/publico/push-a/agendamentos',json={**body,'horario':'14:00'}).status_code==201
    assert len(sent)==before+1 and sent[-1][0].endswith('/s3')
    # Reminders use backend time, never consume a booking; repeat ticks deduplicate.
    sconf=device2.get('/api/notificacoes/config').json()
    sp={x:sconf[x] for x in ('novos','cancelamentos','reagendamentos','lembretes','equipe','minutos')};sp['lembretes']=True
    assert device2.put('/api/notificacoes/config',headers=d2h,json=sp).status_code==200
    upcoming=datetime.now(m.BRASIL)+timedelta(minutes=30)
    with m.banco() as db:db.execute('UPDATE agendamentos SET inicio=? WHERE id=?',(upcoming.isoformat(timespec='minutes'),r.json()['agendamento_id']))
    before=len(sent);m.push_tick();m.push_tick()
    assert len(sent)==before+1 and sent[-1][1]['titulo']=='Próximo atendimento ⏰'
    # Revoked staff never receives a queued delivery.
    os.environ.pop('WEB_PUSH_VAPID_PRIVATE_KEY')
    assert guest.post('/api/publico/push-a/agendamentos',json={**body,'horario':'15:00'}).status_code==201
    assert owner.post('/api/equipe/prof/revogar',headers=oh).status_code==200
    os.environ['WEB_PUSH_VAPID_PRIVATE_KEY']=private
    before=len(sent);m.push_dispatch();assert len(sent)==before
    # Backup includes new data and restores with unique constraints.
    with m.banco() as db:
        tables={t:[dict(row) for row in db.execute('SELECT '+','.join(cols)+' FROM '+t)] for t,cols in m._recursos.TABLES.items()}
    backup=Path(tmp)/'backup.json';backup.write_text(json.dumps({'formato':'barbersaas-backup','versao':1,'tabelas':tables}),encoding='utf8')
    from restaurar_backup import ler,restaurar
    counts=restaurar(ler(backup),sqlite_path=str(Path(tmp)/'restore.db'))
    assert counts['notificacoes']>0 and counts['push_dispositivos']==5
    print('OK: SQLite/PostgreSQL, tenants, professional routing, owner opt-in, commit before delivery, multi-device, CSRF, SSRF, read/unread, rebooking, cancellation, reminders, retries, deduplication, expired subscriptions, logout, revocation and backup.')
if schema:
    with psycopg.connect(os.environ['PUSH_TEST_DATABASE_URL']) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')
