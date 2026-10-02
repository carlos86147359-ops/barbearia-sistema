import importlib.util,json,os,tempfile
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
with tempfile.TemporaryDirectory() as tmp:
    os.environ.pop('DATABASE_URL',None);os.environ.pop('RENDER',None)
    os.environ.update(BARBER_DB_PATH=str(Path(tmp)/'db'),BILLING_ENABLED='true',ADMIN_EMAILS='')
    m=load(ROOT/'app.py','courtesy_test');a=TestClient(m.app);b=TestClient(m.app)
    for cli,email,slug in ((a,'admin@example.com','admin-loja'),(b,'outra@example.com','outra-loja')):
        assert cli.post('/api/cadastro',json={'aceite_termos':True,'email':email,'senha':'SenhaTeste!12345','nome':slug,'slug':slug}).status_code==201
    ah={'X-CSRF-Token':a.get('/api/sessao').json()['csrf']};bh={'X-CSRF-Token':b.get('/api/sessao').json()['csrf']}
    os.environ['ADMIN_EMAILS']='admin@example.com'
    assert not a.get('/api/assinatura').json()['ativa']
    assert b.post('/api/gestao/minha-cortesia',headers=bh).status_code==403
    assert a.post('/api/gestao/minha-cortesia').status_code==403
    for _ in range(2):assert a.post('/api/gestao/minha-cortesia',headers=ah).json()['status']=='cortesia'
    assert a.get('/api/assinatura').json()['valor']==0
    assert not b.get('/api/assinatura').json()['ativa']
    assert a.get('/api/gestao/pagamentos').json()==[]
    raw=m.backup_payload();assert len(raw['tabelas']['cortesias'])==1
    p=Path(tmp)/'backup.json';p.write_text(json.dumps(raw));r=load(ROOT/'restaurar_backup.py','courtesy_restore')
    restored=Path(tmp)/'restored.db';r.restaurar(r.ler(p),str(restored))
    old=json.loads(json.dumps(raw));del old['tabelas']['cortesias'];p.write_text(json.dumps(old));assert r.ler(p)['cortesias']==[]
    os.environ['BARBER_DB_PATH']=str(restored);m2=load(ROOT/'app.py','courtesy_restored_app');c=TestClient(m2.app)
    assert c.post('/api/login',json={'email':'admin@example.com','senha':'SenhaTeste!12345'}).status_code==200
    assert c.get('/api/assinatura').json()['status']=='cortesia'
print('OK: cortesia somente para administrador próprio, CSRF, isolamento, idempotência, sem Pix e restauração compatível.')
