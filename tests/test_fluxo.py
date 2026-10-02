import os
import sys
import tempfile
import importlib.util
import sqlite3
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor


from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'teste.db')
    os.environ.pop('DATABASE_URL',None)
    os.environ.pop('RENDER',None)
    # Um registro da versão anterior deve continuar preservado, sem ficar acessível a novos donos.
    with sqlite3.connect(os.environ['BARBER_DB_PATH']) as db:
        db.execute('CREATE TABLE agendamentos(id INTEGER PRIMARY KEY,cliente_nome TEXT,cliente_telefone TEXT,barbeiro_nome TEXT,servico_nome TEXT,data_hora TEXT,preco REAL,criado_em TEXT)')
        db.execute("INSERT INTO agendamentos VALUES(1,'Antigo','11900000000','Carlos Henrique','Corte Cabelo Fade','2026-11-01 às 09:00',65,NULL)")
    db.close()
    spec=importlib.util.spec_from_file_location('barber_app',Path(__file__).resolve().parents[1] / 'app.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    a,b,public=TestClient(mod.app),TestClient(mod.app),TestClient(mod.app)
    assert public.get('/api/agendamentos').status_code==401
    assert public.get('/api/configuracao').status_code==401
    for client,email,slug in [(a,'dono-a@example.com','loja-a'),(b,'dono-b@example.com','loja-b')]:
        r=client.post('/api/cadastro',json={'nome':slug,'slug':slug,'email':email,'senha':'SenhaTeste!12345'})
        assert r.status_code==201,r.text
        assert 'httponly' in r.headers['set-cookie'].lower()
    ah={'X-CSRF-Token':a.get('/api/sessao').json()['csrf']}
    bh={'X-CSRF-Token':b.get('/api/sessao').json()['csrf']}
    cfg={'nome':'Barbearia A','whatsapp':'11900000000','comissao':40,'barbeiros':[{'id':'prof','nome':'Profissional'}], 'servicos':[{'id':'corte','nome':'Corte','preco':'45.50','duracao':60}], 'dias':list(range(7)), 'periodos':[{'inicio':'09:00','fim':'19:00'}], 'intervalo':30}
    assert a.put('/api/configuracao',json=cfg).status_code==403
    assert a.put('/api/configuracao',json=cfg,headers={**ah,'Origin':'https://intruso.example'}).status_code==403
    assert a.put('/api/configuracao',json=cfg,headers=ah).status_code==200
    assert b.put('/api/configuracao',json={**cfg,'nome':'Barbearia B'},headers=bh).status_code==200
    tomorrow=(datetime.now(mod.BRASIL)+timedelta(days=1)).date().isoformat()
    payload={'cliente_nome':'Cliente Teste','cliente_telefone':'11900000000','barbeiro_id':'prof','servico_id':'corte','data':tomorrow,'horario':'09:00'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(lambda _:TestClient(mod.app).post('/api/publico/loja-a/agendamentos',json=payload).status_code,range(2)))
    assert sorted(codes)==[201,409],codes
    rows=a.get('/api/agendamentos').json();assert len(rows)==1,rows
    reservation=rows[0]['id'];assert rows[0]['preco']==45.5 and rows[0]['comissao_pct']==40
    assert b.get('/api/agendamentos').json()==[]
    assert b.patch(f'/api/agendamentos/{reservation}',json={'status':'cancelado'},headers=bh).status_code==404
    assert public.patch(f'/api/agendamentos/{reservation}',json={'status':'cancelado'}).status_code==401
    assert public.post('/api/publico/loja-b/agendamentos',json=payload).status_code==201
    assert public.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'09:30'}).status_code==409
    assert a.patch(f'/api/agendamentos/{reservation}',json={'status':'cancelado'},headers=ah).status_code==200
    assert public.post('/api/publico/loja-a/agendamentos',json=payload).status_code==201
    assert a.patch(f'/api/agendamentos/{reservation}',json={'status':'agendado'},headers=ah).status_code==409
    cfg['servicos'][0]['preco']='80.00';cfg['comissao']=50
    assert a.put('/api/configuracao',json=cfg,headers=ah).status_code==200
    assert a.get('/api/agendamentos').json()[0]['preco']==45.5
    assert a.get('/api/agendamentos').json()[0]['comissao_pct']==40
    assert public.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'18:30'}).status_code==422
    assert public.post('/api/publico/loja-a/agendamentos',json={**payload,'data':'2020-01-01'}).status_code==422
    assert public.post('/api/publico/loja-a/agendamentos',json={**payload,'horario':'12:00','servico_id':'outro'}).status_code==422
    assert 'comissao' not in public.get('/api/publico/loja-a/configuracao').json()
    assert a.post('/api/logout',headers=ah).status_code==200
    assert a.get('/api/agendamentos').status_code==401
    assert a.post('/api/login',json={'email':'dono-a@example.com','senha':'SenhaErrada123'}).status_code==401
    assert a.post('/api/login',json={'email':'dono-a@example.com','senha':'SenhaTeste!12345'}).status_code==200
    spec.loader.exec_module(mod)
    assert len(a.get('/api/agendamentos').json())==2
    assert public.get('/health').json()['status']=='ok'
    assert public.get('/api/agendamentos').headers['cache-control']=='no-store'
    print('OK: cadastro/login, sessão/CSRF, isolamento, migração, concorrência, preços, cancelamento, disponibilidade e persistência.')
