import importlib.util
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'billing.db')
    os.environ.pop('DATABASE_URL',None)
    os.environ.pop('RENDER',None)
    os.environ['BILLING_ENABLED']='true'
    os.environ['ADMIN_EMAILS']=''
    spec=importlib.util.spec_from_file_location('billing_app',Path(__file__).parents[1]/'app.py')
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    admin=TestClient(m.app); owner=TestClient(m.app); public=TestClient(m.app)
    def register(c,email,slug):
        r=c.post('/api/cadastro',json={'aceite_termos':True,'nome':slug,'slug':slug,'email':email,'senha':'SenhaTeste!12345'})
        assert r.status_code==201,r.text
        return {'X-CSRF-Token':r.json()['csrf']}
    ah=register(admin,'admin@example.com','admin-shop')
    os.environ['ADMIN_EMAILS']='admin@example.com'
    assert public.post('/api/cadastro',json={'aceite_termos':True,'nome':'Falso','slug':'falso-admin','email':'admin@example.com','senha':'SenhaTeste!12345'}).status_code==409
    oh=register(owner,'owner@example.com','owner-shop')
    assert public.get('/api/gestao/barbearias').status_code==401
    assert owner.get('/api/gestao/barbearias').status_code==403
    shops=admin.get('/api/gestao/barbearias').json()
    sid=next(s['id'] for s in shops if s['slug']=='owner-shop')
    url='/api/gestao/barbearias/'+sid+'/pagamentos'
    assert owner.post(url,headers=oh,json={'referencia':'PIX-OWNER'}).status_code==403
    assert admin.post(url,json={'referencia':'PIX-001'}).status_code==403
    config={'nome':'Loja','whatsapp':'','comissao':50,'barbeiros':[{'id':'joao','nome':'João'}],'servicos':[{'id':'corte','nome':'Corte','preco':45,'duracao':30}],'dias':list(range(7)),'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    assert owner.put('/api/configuracao',headers=oh,json=config).status_code==200
    payload={'cliente_nome':'Teste','cliente_telefone':'11900000000','barbeiro_id':'joao','servico_id':'corte','data':(datetime.now(m.BRASIL)+timedelta(days=1)).date().isoformat(),'horario':'09:00'}
    booking='/api/publico/owner-shop/agendamentos'
    assert public.get('/api/publico/owner-shop/configuracao').json()['agenda_liberada'] is False
    assert public.post(booking,json=payload).status_code==403
    def confirm(_): return admin.post(url,headers=ah,json={'referencia':'PIX-001'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(confirm,range(2)))==[201,409]
    first=owner.get('/api/assinatura').json()
    assert first['ativa'] and len(first['pagamentos'])==1
    assert public.post(booking,json=payload).status_code==201
    assert admin.post(url,headers=ah,json={'referencia':'PIX-002'}).status_code==201
    second=owner.get('/api/assinatura').json()
    assert datetime.fromisoformat(second['vencimento'])>datetime.fromisoformat(first['vencimento'])
    with m.banco() as db: db.execute('UPDATE assinaturas SET vencimento=? WHERE loja_id=?',((datetime.now(m.BRASIL)-timedelta(days=1)).isoformat(),sid))
    assert owner.get('/api/assinatura').json()['ativa'] is False
    assert owner.get('/api/agendamentos').status_code==200
    assert len(owner.get('/api/agendamentos').json())==1
    assert public.post(booking,json={**payload,'horario':'10:00'}).status_code==403
    assert owner.put('/api/configuracao',headers=oh,json=config).status_code==200
    assert admin.post(url,headers=ah,json={'referencia':'PIX-003'}).status_code==201
    assert owner.get('/api/assinatura').json()['ativa'] is True
    print('OK: administrador, CSRF, bloqueio antes do pagamento, ativação, duplicidade concorrente, renovação e vencimento preservando reservas.')
