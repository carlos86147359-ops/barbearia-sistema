"""Identidade opcional deve persistir por loja sem alterar contas ou reservas."""
import os, tempfile, importlib.util
from pathlib import Path
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'identidade.db')
    for key in ('DATABASE_URL','RENDER','ADMIN_EMAILS','BILLING_ENABLED'): os.environ.pop(key,None)
    spec=importlib.util.spec_from_file_location('identity_app',Path(__file__).parents[1]/'app.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    clients=[TestClient(mod.app),TestClient(mod.app)]
    headers=[]
    for i,c in enumerate(clients):
        r=c.post('/api/cadastro',json={'nome':'Loja '+str(i),'slug':'loja-'+str(i),'email':f'dono{i}@example.com','senha':'SenhaTeste!12345','aceite_termos':True})
        assert r.status_code==201,r.text
        headers.append({'X-CSRF-Token':r.json()['csrf']})
    cfg={'nome':'Loja A','whatsapp':'','comissao':50,'barbeiros':[{'id':'a','nome':'Ana'}],'servicos':[{'id':'c','nome':'Corte','preco':35,'duracao':30}],'dias':[0,1,2,3,4,5],'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    brand={'logo_url':'https://example.com/logo.png','capa_url':'https://example.com/capa.jpg','cor_principal':'#ffffff','endereco':'Rua Teste, 10','instagram':'https://www.instagram.com/loja'}
    a,b=clients
    assert a.put('/api/configuracao',json={**cfg,**brand},headers=headers[0]).status_code==200
    assert b.put('/api/configuracao',json=cfg,headers=headers[1]).status_code==200
    public=TestClient(mod.app)
    data=public.get('/api/publico/loja-0/configuracao').json()
    assert all(data[k]==v for k,v in brand.items())
    assert 'comissao' not in data
    assert public.get('/api/publico/loja-1/configuracao').json()['logo_url']==''
    # Um cliente anterior enviando só os campos antigos não apaga a marca.
    assert a.put('/api/configuracao',json=cfg,headers=headers[0]).status_code==200
    assert a.get('/api/configuracao').json()['logo_url']==brand['logo_url']
    for patch in ({'logo_url':'javascript:alert(1)'},{'capa_url':'http://example.com/capa.jpg'},{'instagram':'https://instagram.com.example.com/loja'},{'logo_url':'https://usuario:senha@example.com/a'},{'cor_principal':'red'}):
        assert a.put('/api/configuracao',json={**cfg,**brand,**patch},headers=headers[0]).status_code==422
    assert a.get('/api/configuracao').json()['cor_principal']=='#ffffff'
    assert a.put('/api/configuracao',json={**cfg,'logo_url':''},headers=headers[0]).status_code==200
    assert a.get('/api/configuracao').json()['logo_url']==''
    assert public.put('/api/configuracao',json=cfg).status_code==401
    assert public.get('/design-system.css').status_code==200
    assert 'text/css' in public.get('/design-system.css').headers['content-type']
    assert public.get('/design-system.js').status_code==200
    print('OK: identidade isolada, links validados, compatibilidade, remoção opcional e assets.')
