"""Ensaio com dados fictícios em PostgreSQL LOCAL descartável do GitHub."""
import importlib.util
import json
import os
import tempfile
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urlparse
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
dsn=os.environ['BACKUP_TEST_DATABASE_URL']
assert urlparse(dsn).hostname in ('localhost','127.0.0.1')
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
with tempfile.TemporaryDirectory() as tmp:
    os.environ.pop('DATABASE_URL',None);os.environ.pop('RENDER',None)
    os.environ.update(BARBER_DB_PATH=str(Path(tmp)/'fixture.db'),BILLING_ENABLED='false',ADMIN_EMAILS='')
    source=load(ROOT/'app.py','source_fixture');cli=TestClient(source.app)
    password='SenhaFicticiaTeste!123'
    assert cli.post('/api/cadastro',json={'aceite_termos':True,'email':'ensaio@example.com','senha':password,'nome':'Ensaio','slug':'ensaio'}).status_code==201
    headers={'X-CSRF-Token':cli.get('/api/sessao').json()['csrf']}
    cfg={'nome':'Ensaio','whatsapp':'11900000000','comissao':40,'barbeiros':[{'id':'p','nome':'Fictício'}],'servicos':[{'id':'c','nome':'Corte teste','preco':45,'duracao':30}],'dias':list(range(7)),'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    assert cli.put('/api/configuracao',json=cfg,headers=headers).status_code==200
    day=(datetime.now(source.BRASIL)+timedelta(days=2)).date().isoformat()
    payload={'cliente_nome':'Cliente fictício','cliente_telefone':'11900000000','barbeiro_id':'p','servico_id':'c','data':day,'horario':'09:00'}
    booking=cli.post('/api/publico/ensaio/agendamentos',json=payload);assert booking.status_code==201
    path=Path(tmp)/'fixture.json';path.write_text(json.dumps(source.backup_payload()),encoding='utf-8')
    restore=load(ROOT/'restaurar_backup.py','restore_pg_fixture');tables=restore.ler(path)
    os.environ['RESTORE_DATABASE_URL']=dsn
    assert restore.restaurar(tables,postgres=True)['usuarios']==1
    try:restore.restaurar(tables,postgres=True);raise AssertionError('Aceitou destino ocupado')
    except ValueError:pass
    os.environ['DATABASE_URL']=dsn
    recovered=load(ROOT/'app.py','recovered_postgres');client=TestClient(recovered.app)
    assert client.post('/api/login',json={'email':'ensaio@example.com','senha':password}).status_code==200
    assert len(client.get('/api/agendamentos').json())==1
    new=client.post('/api/publico/ensaio/agendamentos',json={**payload,'horario':'10:00'})
    assert new.status_code==201,new.text
    assert new.json()['agendamento_id']>booking.json()['agendamento_id']
print('OK: PostgreSQL restaurado, login, reservas, sequencia de IDs e destino ocupado recusado.')
