import os, tempfile, importlib.util
from pathlib import Path
from datetime import datetime,timedelta
from urllib.parse import urlparse,parse_qs
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'whatsapp.db')
    for key in ('DATABASE_URL','RENDER','ADMIN_EMAILS','BILLING_ENABLED'): os.environ.pop(key,None)
    spec=importlib.util.spec_from_file_location('wa_app',Path(__file__).parents[1]/'app.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    owner=TestClient(m.app);public=TestClient(m.app)
    r=owner.post('/api/cadastro',json={'nome':'Loja Teste','slug':'loja-teste','email':'owner@example.com','senha':'SenhaTeste!12345'});assert r.status_code==201
    h={'X-CSRF-Token':r.json()['csrf']}
    config={'nome':'Loja Teste','whatsapp':'11999990000','comissao':40,'barbeiros':[{'id':'joao','nome':'João','whatsapp':'(61) 98133-2994'},{'id':'maria','nome':'Maria','whatsapp':'+55 21 99888-0000'},{'id':'sem-numero','nome':'Sem número'}],'servicos':[{'id':'corte','nome':'Corte','preco':45,'duracao':30}],'dias':list(range(7)),'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    saved=owner.put('/api/configuracao',headers=h,json=config);assert saved.status_code==200,saved.text
    assert saved.json()['barbeiros'][0]['whatsapp']=='61981332994'
    assert saved.json()['barbeiros'][2]['whatsapp']==''
    day=(datetime.now(m.BRASIL)+timedelta(days=1)).date().isoformat()
    payload={'cliente_nome':'Cliente & Teste','cliente_telefone':'11900000000','data':day,'horario':'09:00','servico_id':'corte'}
    for barber,number,target in [('joao','5561981332994','barbeiro'),('maria','5521998880000','barbeiro'),('sem-numero','5511999990000','loja')]:
        r=public.post('/api/publico/loja-teste/agendamentos',json={**payload,'barbeiro_id':barber,'whatsapp':'55888888888'})
        assert r.status_code==201,r.text
        url=urlparse(r.json()['link_whatsapp']);assert url.netloc=='wa.me' and url.path=='/'+number
        message=parse_qs(url.query)['text'][0]
        assert 'Cliente & Teste' in message and 'Reserva #' in message
        assert r.json()['whatsapp_destinatario']==target
    config['whatsapp']=''
    assert owner.put('/api/configuracao',headers=h,json=config).status_code==200
    r=public.post('/api/publico/loja-teste/agendamentos',json={**payload,'barbeiro_id':'sem-numero','horario':'10:00'})
    assert r.status_code==201 and r.json()['link_whatsapp'] is None
    config['barbeiros'][0]['whatsapp']='123'
    assert owner.put('/api/configuracao',headers=h,json=config).status_code==422
    config['barbeiros'][0]['whatsapp']='abc'
    assert owner.put('/api/configuracao',headers=h,json=config).status_code==422
    assert owner.get('/api/configuracao').json()['barbeiros'][0]['whatsapp']=='61981332994'
    print('OK: WhatsApp individual, normalização com DDD/55, loja como alternativa, ausência de número, mensagem codificada e rejeição de números inválidos.')
