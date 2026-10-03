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
    os.environ['ADMIN_EMAILS']='ensaio@example.com'
    assert cli.post('/api/gestao/minha-cortesia',headers=headers).status_code==200
    cfg={'nome':'Ensaio','whatsapp':'11900000000','comissao':40,'barbeiros':[{'id':'p','nome':'Fictício'}],'servicos':[{'id':'c','nome':'Corte teste','preco':45,'duracao':30}],'dias':list(range(7)),'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    assert cli.put('/api/configuracao',json=cfg,headers=headers).status_code==200
    day=(datetime.now(source.BRASIL)+timedelta(days=2)).date().isoformat()
    payload={'cliente_nome':'Cliente fictício','cliente_telefone':'11900000000','barbeiro_id':'p','servico_id':'c','data':day,'horario':'09:00'}
    booking=cli.post('/api/publico/ensaio/agendamentos',json=payload);assert booking.status_code==201
    product=cli.post('/api/produtos/catalogo',headers=headers,json={'nome':'Pomada teste','custo_centavos':1200,'preco_centavos':3000,'variantes':[{'quantidade':3}]});assert product.status_code==201,product.text
    variant=cli.get('/api/produtos/catalogo').json()[0]['variantes'][0]['id']
    sale=cli.post('/api/produtos/vendas',headers=headers,json={'itens':[{'variante_id':variant,'quantidade':2}],'pagamento':'pix','idempotencia':'fixture-product-sale-12345'});assert sale.status_code==201,sale.text
    path=Path(tmp)/'fixture.json';path.write_text(json.dumps(source.backup_payload()),encoding='utf-8')
    restore=load(ROOT/'restaurar_backup.py','restore_pg_fixture');tables=restore.ler(path)
    os.environ['RESTORE_DATABASE_URL']=dsn
    assert restore.restaurar(tables,postgres=True)['usuarios']==1
    try:restore.restaurar(tables,postgres=True);raise AssertionError('Aceitou destino ocupado')
    except ValueError:pass
    os.environ['DATABASE_URL']=dsn
    recovered=load(ROOT/'app.py','recovered_postgres');client=TestClient(recovered.app)
    assert client.post('/api/login',json={'email':'ensaio@example.com','senha':password}).status_code==200
    product_rows=client.get('/api/produtos/catalogo').json();assert product_rows[0]['variantes'][0]['quantidade']==1
    assert client.get('/api/produtos/vendas').json()[0]['custo_centavos']==2400
    from concurrent.futures import ThreadPoolExecutor
    import secrets
    h={'X-CSRF-Token':client.get('/api/sessao').json()['csrf']}
    def buy(_):return client.post('/api/produtos/vendas',headers=h,json={'itens':[{'variante_id':variant,'quantidade':1}],'pagamento':'dinheiro','idempotencia':secrets.token_hex(20)})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(buy,range(2)))
    assert sorted(r.status_code for r in results)==[201,409],[(r.status_code,r.text) for r in results]
    assert client.get('/api/produtos/catalogo').json()[0]['variantes'][0]['quantidade']==0
    assert client.get('/api/assinatura').json()['status']=='cortesia'
    assert len(client.get('/api/agendamentos').json())==1
    new=client.post('/api/publico/ensaio/agendamentos',json={**payload,'horario':'10:00'})
    assert new.status_code==201,new.text
    assert new.json()['agendamento_id']>booking.json()['agendamento_id']
print('OK: PostgreSQL restaurado, login, reservas, sequencia de IDs e destino ocupado recusado.')
