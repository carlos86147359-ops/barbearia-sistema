import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

with tempfile.TemporaryDirectory() as tmp:
    os.environ.pop('DATABASE_URL',None);os.environ.pop('RENDER',None)
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'live.db');os.environ['BILLING_ENABLED']='false';os.environ['ADMIN_EMAILS']='admin@example.com'
    for key in ('RESEND_API_KEY','EMAIL_FROM','PUBLIC_BASE_URL'):os.environ.pop(key,None)
    m=load(ROOT/'app.py','new_features');pub=TestClient(m.app);a=TestClient(m.app);b=TestClient(m.app)
    assert a.post('/api/cadastro',json={'email':'a@example.com','senha':'SenhaTeste!12345','nome':'Loja A','slug':'loja-a'}).status_code==422
    for cli,email,slug in ((a,'a@example.com','loja-a'),(b,'b@example.com','loja-b')):
        assert cli.post('/api/cadastro',json={'aceite_termos':True,'email':email,'senha':'SenhaTeste!12345','nome':slug,'slug':slug}).status_code==201
    ah={'X-CSRF-Token':a.get('/api/sessao').json()['csrf']};bh={'X-CSRF-Token':b.get('/api/sessao').json()['csrf']}
    cfg={'nome':'Loja A','whatsapp':'11900000000','comissao':40,'barbeiros':[{'id':'p','nome':'Paulo'},{'id':'q','nome':'Pedro'}],'servicos':[{'id':'c','nome':'Corte','preco':45,'duracao':60}],'dias':list(range(7)),'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    assert a.put('/api/configuracao',json=cfg,headers=ah).status_code==200
    assert b.put('/api/configuracao',json=cfg,headers=bh).status_code==200
    day=(datetime.now(m.BRASIL)+timedelta(days=2)).date().isoformat()
    payload={'cliente_nome':'Teste','cliente_telefone':'11900000000','barbeiro_id':'p','servico_id':'c','data':day,'horario':'09:00'}
    booking=pub.post('/api/publico/loja-a/agendamentos',json=payload);assert booking.status_code==201,booking.text
    token=booking.json()['link_gerenciar'].split('#')[1];rid=booking.json()['agendamento_id']
    assert pub.post('/api/cliente/reserva',json={'token':'x'*43}).status_code==404
    assert b.post(f'/api/agendamentos/{rid}/link-cliente',headers=bh).status_code==404
    info=pub.post('/api/cliente/reserva',json={'token':token}).json();assert info['cliente_nome']=='Teste' and 'cliente_telefone' not in info
    block={'barbeiro_id':'p','inicio':day+'T09:30','fim':day+'T11:00','motivo':'Férias'}
    assert a.post('/api/bloqueios',json=block,headers=ah).status_code==409
    assert a.post('/api/bloqueios',json={**block,'inicio':day+'T11:00'},headers=ah).status_code==422
    block={**block,'inicio':day+'T11:00','fim':day+'T12:00'}
    assert a.post('/api/bloqueios',json=block).status_code==403
    created=a.post('/api/bloqueios',json=block,headers=ah);assert created.status_code==201,created.text
    assert b.get('/api/bloqueios').json()==[]
    assert pub.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'11:00'}).status_code==409
    assert pub.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'11:00','barbeiro_id':'q'}).status_code==201
    assert a.post('/api/bloqueios',json={**block,'barbeiro_id':'','inicio':day+'T14:00','fim':day+'T15:00'},headers=ah).status_code==201
    for barber in ('p','q'):
        assert pub.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'14:00','barbeiro_id':barber}).status_code==409
    hours=pub.post('/api/cliente/horarios',json={'token':token,'data':day}).json()['horarios'];assert '09:00' in hours and '11:00' not in hours and '14:00' not in hours
    cfg['servicos'][0].update(preco=99,duracao=30);assert a.put('/api/configuracao',json=cfg,headers=ah).status_code==200
    assert pub.post('/api/cliente/alterar',json={'token':token,'acao':'reagendar','data':day,'horario':'13:30'}).status_code==409
    assert pub.post('/api/cliente/alterar',json={'token':token,'acao':'reagendar','data':day,'horario':'16:00'}).status_code==200
    info=pub.post('/api/cliente/reserva',json={'token':token}).json();assert info['preco']==45 and info['duracao_minutos']==60 and info['inicio'].endswith('16:00')
    second=pub.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'10:00'}).json()['link_gerenciar'].split('#')[1]
    def move(tok):return TestClient(m.app).post('/api/cliente/alterar',json={'token':tok,'acao':'reagendar','data':day,'horario':'17:00'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(move,[token,second]))==[200,409]
    os.environ['BILLING_ENABLED']='true'
    assert pub.post('/api/cliente/horarios',json={'token':token,'data':day}).status_code==403
    assert pub.post('/api/cliente/alterar',json={'token':token,'acao':'cancelar'}).status_code==200
    os.environ['BILLING_ENABLED']='false'
    assert pub.post('/api/cliente/alterar',json={'token':token,'acao':'cancelar'}).status_code==200
    assert pub.post('/api/cliente/alterar',json={'token':token,'acao':'reagendar','data':day,'horario':'18:00'}).status_code==409
    assert a.post('/api/bloqueios/'+created.json()['id']+'/remover',headers=ah).status_code==200
    assert pub.post('/api/conta/recuperar',json={'email':'a@example.com'}).status_code==503
    os.environ.update(RESEND_API_KEY='local-test-key',EMAIL_FROM='Teste <test@example.com>',PUBLIC_BASE_URL='https://example.com')
    mails=[];m.enviar_email=lambda to,subject,text,uid,acao:mails.append((to,subject,text))
    assert a.post('/api/conta/email/enviar',headers=ah).status_code==200
    verify=re.search(r'#([\w-]+)',mails[-1][2])[1];assert a.get('/api/sessao').json()['email_confirmado'] is False
    assert pub.post('/api/conta/redefinir',json={'token':verify,'senha':'NovaSenhaTeste!123'}).status_code==410
    assert pub.post('/api/conta/email/confirmar',json={'token':verify}).status_code==200
    assert a.get('/api/sessao').json()['email_confirmado'] is True
    assert pub.post('/api/conta/email/confirmar',json={'token':verify}).status_code==410
    assert a.post('/api/conta/email/enviar',headers=ah).status_code==200
    expired=re.search(r'#([\w-]+)',mails[-1][2])[1]
    with m.banco() as db:db.execute('UPDATE tokens_email SET expira=0 WHERE token=?',(hashlib.sha256(expired.encode()).hexdigest(),))
    assert pub.post('/api/conta/email/confirmar',json={'token':expired}).status_code==410
    known=pub.post('/api/conta/recuperar',json={'email':'a@example.com'});raw=re.search(r'#([\w-]+)',mails[-1][2])[1]
    unknown=pub.post('/api/conta/recuperar',json={'email':'none@example.com'});assert known.json()==unknown.json() and raw not in known.text
    assert pub.post('/api/conta/redefinir',json={'token':raw,'senha':'NovaSenhaTeste!123'}).status_code==200
    assert a.get('/api/sessao').status_code==401
    assert pub.post('/api/conta/redefinir',json={'token':raw,'senha':'NovaSenhaTeste!123'}).status_code==410
    assert pub.post('/api/conta/recuperar',json={'email':'b@example.com'}).status_code==200
    concurrent=re.search(r'#([\w-]+)',mails[-1][2])[1]
    def reset_once(_):return TestClient(m.app).post('/api/conta/redefinir',json={'token':concurrent,'senha':'OutraSenhaTeste!123'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(reset_once,range(2)))==[200,410]
    def fail(*args):raise RuntimeError('Simulação de indisponibilidade do provedor')
    m.enviar_email=fail
    assert pub.post('/api/conta/recuperar',json={'email':'b@example.com'}).status_code==200
    with m.banco() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM eventos_email WHERE status='falhou'").fetchone()['n']==1
        assert db.execute("SELECT COUNT(*) AS n FROM tokens_email WHERE acao='senha'").fetchone()['n']==0
    assert a.post('/api/login',json={'email':'a@example.com','senha':'SenhaTeste!12345'}).status_code==401
    assert a.post('/api/login',json={'email':'a@example.com','senha':'NovaSenhaTeste!123'}).status_code==200
    ah={'X-CSRF-Token':a.get('/api/sessao').json()['csrf']}
    assert a.get('/api/gestao/pagamentos').status_code==403
    with m.banco() as db:db.execute("UPDATE usuarios SET email='admin@example.com' WHERE email='a@example.com'")
    assert a.get('/api/gestao/pagamentos').status_code==200
    shops=a.get('/api/gestao/barbearias').json();sid=next(r['id'] for r in shops if r['slug']=='loja-b')
    assert a.post('/api/gestao/barbearias/'+sid+'/pagamentos',json={'referencia':'PIX-FICTICIO-TESTE-001'},headers=ah).status_code==201
    history=a.get('/api/gestao/pagamentos').json();assert history[0]['referencia']=='PIX-FICTICIO-TESTE-001' and history[0]['valor_centavos']==9000 and history[0]['confirmado_por_email']=='admin@example.com'
    assert a.post('/api/gestao/backup',json={'senha':'NovaSenhaTeste!123'}).status_code==403
    assert a.post('/api/gestao/backup',json={'senha':'ErradaSenha!12345'},headers=ah).status_code==401
    copy=a.post('/api/gestao/backup',json={'senha':'NovaSenhaTeste!123'},headers=ah);assert copy.status_code==200,copy.text
    assert 'sessoes' not in copy.json()['tabelas'] and 'tokens_email' not in copy.json()['tabelas']
    assert a.get('/api/gestao/operacao').json()['ultima_copia']
    path=Path(tmp)/'copy.json';path.write_bytes(copy.content);restore=load(ROOT/'restaurar_backup.py','restore_test')
    tables=restore.ler(path,copy.headers['X-Backup-SHA256']);dest=Path(tmp)/'restored.db';counts=restore.restaurar(tables,str(dest));assert counts['usuarios']==2
    try:restore.restaurar(tables,str(dest));raise AssertionError('Não deve sobrescrever')
    except FileExistsError:pass
    path.write_bytes(copy.content+b' ')
    try:restore.ler(path,copy.headers['X-Backup-SHA256']);raise AssertionError('Deve identificar alteração')
    except ValueError:pass
    os.environ['BARBER_DB_PATH']=str(dest);restored=load(ROOT/'app.py','restored_app');rc=TestClient(restored.app)
    assert rc.post('/api/login',json={'email':'admin@example.com','senha':'NovaSenhaTeste!123'}).status_code==200
    assert len(rc.get('/api/agendamentos').json())==len(a.get('/api/agendamentos').json())
    created_again=rc.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'18:30'})
    assert created_again.status_code==201 and isinstance(created_again.json()['agendamento_id'],int)
    for page in ('termos','privacidade','suporte','recuperar-senha','minha-reserva'):assert pub.get('/'+page).status_code==200
print('OK: links privados, conflitos simultâneos, folgas, isolamento, e-mail de uso único, invalidação de sessões, cópia e restauração com login preservado.')
