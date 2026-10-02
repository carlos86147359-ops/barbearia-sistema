import os
import importlib.util
import tempfile
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'equipe.db')
    for key in ('DATABASE_URL','RENDER','ADMIN_EMAILS','BILLING_ENABLED'): os.environ.pop(key,None)
    spec=importlib.util.spec_from_file_location('staff_app',Path(__file__).parents[1]/'app.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    owner=TestClient(m.app);other=TestClient(m.app);staff=TestClient(m.app);public=TestClient(m.app)
    def register(c,email,slug):
        r=c.post('/api/cadastro',json={'email':email,'senha':'SenhaTeste!12345','nome':slug,'slug':slug});assert r.status_code==201,r.text
        return {'X-CSRF-Token':r.json()['csrf']}
    oh=register(owner,'owner@example.com','loja-a');xh=register(other,'other@example.com','loja-b')
    config={'nome':'Loja','whatsapp':'','comissao':40,'barbeiros':[{'id':'joao','nome':'João'},{'id':'maria','nome':'Maria'}],'servicos':[{'id':'corte','nome':'Corte','preco':45,'duracao':30}],'dias':list(range(7)),'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    assert owner.put('/api/configuracao',headers=oh,json=config).status_code==200
    assert other.put('/api/configuracao',headers=xh,json=config).status_code==200
    def invite(c,headers,barber,email):
        r=c.post('/api/equipe/'+barber+'/convite',headers=headers,json={'email':email});assert r.status_code==201,r.text
        return r.json()['link'].split('#')[1]
    assert public.get('/api/equipe').status_code==401
    assert owner.post('/api/equipe/joao/convite',json={'email':'joao@example.com'}).status_code==403
    assert owner.post('/api/equipe/desconhecido/convite',headers=oh,json={'email':'joao@example.com'}).status_code==404
    first=invite(owner,oh,'joao','joao@example.com');token=invite(owner,oh,'joao','joao@example.com')
    assert public.post('/api/convite/info',json={'token':first}).status_code==410
    assert public.post('/api/convite/info',json={'token':token}).json()['email']=='joao@example.com'
    def accept(_): return staff.post('/api/convite/aceitar',json={'token':token,'senha':'SenhaBarbeiro!12345'})
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(accept,range(2)))
    assert sorted(r.status_code for r in results)==[201,410]
    sh={'X-CSRF-Token':next(r.json()['csrf'] for r in results if r.status_code==201)}
    assert staff.get('/api/sessao').json()['papel']=='barbeiro'
    assert staff.get('/api/configuracao').status_code==403
    assert staff.put('/api/configuracao',headers=sh,json=config).status_code==403
    assert staff.get('/api/assinatura').status_code==403
    assert staff.get('/api/gestao/barbearias').status_code==403
    assert staff.get('/api/equipe').status_code==403
    assert staff.post('/api/equipe/maria/convite',headers=sh,json={'email':'fake@example.com'}).status_code==403
    assert other.post('/api/equipe/maria/convite',headers=xh,json={'email':'joao@example.com'}).status_code==409
    day=(datetime.now(m.BRASIL)+timedelta(days=1)).date().isoformat()
    body={'cliente_nome':'Teste','cliente_telefone':'11900000000','data':day,'horario':'09:00','servico_id':'corte','barbeiro_id':'joao'}
    ids=[]
    for slug,barber in [('loja-a','joao'),('loja-a','maria'),('loja-b','joao')]:
        r=public.post('/api/publico/'+slug+'/agendamentos',json={**body,'barbeiro_id':barber});assert r.status_code==201,r.text;ids.append(r.json()['agendamento_id'])
    assert [r['id'] for r in staff.get('/api/agendamentos').json()]==[ids[0]]
    for id in ids[1:]: assert staff.patch('/api/agendamentos/'+str(id),headers=sh,json={'status':'concluido'}).status_code==404
    assert staff.patch('/api/agendamentos/'+str(ids[0]),headers=sh,json={'status':'cancelado'}).status_code==403
    assert staff.patch('/api/agendamentos/'+str(ids[0]),headers=sh,json={'status':'concluido'}).status_code==200
    assert staff.patch('/api/agendamentos/'+str(ids[0]),headers=sh,json={'status':'agendado'}).status_code==403
    assert len(owner.get('/api/agendamentos').json())==2
    assert owner.post('/api/equipe/joao/revogar',headers=oh).status_code==200
    assert staff.get('/api/agendamentos').status_code==401
    assert staff.post('/api/login',json={'email':'joao@example.com','senha':'SenhaBarbeiro!12345'}).status_code==401
    token=invite(owner,oh,'joao','joao@example.com')
    r=staff.post('/api/convite/aceitar',json={'token':token,'senha':'NovaSenhaBarbeiro!12345'});assert r.status_code==201
    assert staff.get('/api/agendamentos').status_code==200
    config['barbeiros']=[config['barbeiros'][1]]
    assert owner.put('/api/configuracao',headers=oh,json=config).status_code==200
    assert staff.get('/api/agendamentos').status_code==401
    assert staff.post('/api/login',json={'email':'joao@example.com','senha':'NovaSenhaBarbeiro!12345'}).status_code==401
    expired=invite(owner,oh,'maria','maria@example.com')
    with m.banco() as db: db.execute('UPDATE convites SET expira=0')
    assert public.post('/api/convite/info',json={'token':expired}).status_code==410
    spec.loader.exec_module(m)
    assert owner.get('/api/sessao').json()['papel']=='dono'
    assert len(owner.get('/api/agendamentos').json())==2
    print('OK: convites de uso único e expirados, aceitação concorrente, papéis, isolamento entre profissionais e lojas, CSRF, revogação imediata, remoção e persistência.')
