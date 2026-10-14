"""Produção simulada: nenhum acesso à rede e nenhum cartão/chave real."""
import importlib.util
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    for name in ('DATABASE_URL','RENDER'): os.environ.pop(name,None)
    if os.environ.get('TEST_ASAAS_DATABASE_URL'): os.environ['DATABASE_URL']=os.environ['TEST_ASAAS_DATABASE_URL']
    os.environ.update(BARBER_DB_PATH=str(Path(tmp)/'production.db'),BILLING_ENABLED='true',ADMIN_EMAILS='',
        ASAAS_ENV='production',ASAAS_PRODUCTION_API_KEY='fake-production-key',
        ASAAS_PRODUCTION_WEBHOOK_TOKEN='p'*48,ASAAS_PRODUCTION_ENABLED='false',PUBLIC_BASE_URL='https://example.test')
    spec=importlib.util.spec_from_file_location('production_test_app',ROOT/'app.py')
    appmod=importlib.util.module_from_spec(spec);spec.loader.exec_module(appmod)
    import cobranca_saas as billing
    a,b,public=TestClient(appmod.app),TestClient(appmod.app,client=('198.51.100.2',50000)),TestClient(appmod.app)
    headers=[]
    for i,client in enumerate((a,b)):
        r=client.post('/api/cadastro',json={'nome':'Produção '+str(i),'slug':'producao-'+str(i),'email':f'prod{i}@example.test','senha':'SenhaTeste!12345','aceite_termos':True})
        assert r.status_code==201,r.text
        headers.append({'x-csrf-token':r.json()['csrf']})
    consent={'aceite_condicoes':'tres_meses_60_depois_nova_contratacao_90_v1'}
    assert public.get('/api/saas/assinatura').status_code==401
    assert a.post('/api/saas/checkout',json=consent).status_code==403
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==503
    os.environ['ASAAS_PRODUCTION_ENABLED']='true'
    assert a.post('/api/saas/checkout',json={},headers=headers[0]).status_code==422
    calls=[];payments={};checkouts=[];qr_expired=False;qr_payload='00020101021226730014br.gov.bcb.pix2551pix-h.asaas.com/pixqrcode/cobv/pay_76575613967995145204000053039865802BR5905ASAAS6009Joinville61088922827162070503***63045E7A'
    def fake(method,path,body=None):
        from urllib.parse import parse_qs,urlparse
        calls.append((method,path,body))
        if method=='POST' and path=='/checkouts':
            checkouts.append(body);idx=len(checkouts)
            assert body['billingTypes']==['PIX'] and body['chargeTypes']==['DETACHED']
            assert 'subscription' not in body
            pid='pay_pix_'+str(idx);co='checkout_pix_'+str(idx)
            payments[pid]={'id':pid,'checkoutSession':co,'customer':'cus_pix','billingType':'PIX','value':body['items'][0]['value'],'dueDate':datetime.now(appmod.BRASIL).date().isoformat(),'status':'PENDING','invoiceUrl':'https://www.asaas.com/i/pix-test'}
            return {'id':co}
        if path.startswith('/payments?'):
            co=parse_qs(urlparse(path).query)['checkoutSession'][0]
            return {'data':[dict(p) for p in payments.values() if p['checkoutSession']==co and not p.get('omit')],'hasMore':False}
        if path.endswith('/pixQrCode'):
            return {'payload':qr_payload,'expirationDate':'2000-01-01 23:59:59' if qr_expired else '2099-01-01 23:59:59','encodedImage':'IMAGEM_EXTERNA_INVALIDA'}
        if path.startswith('/payments/'):
            p=payments[path.split('/')[2]]
            if method=='DELETE': p['deleted']=True;return {'deleted':True}
            return {'deleted':True} if p.get('deleted') else dict(p)
        if method=='POST' and path.endswith('/cancel'): return {}
        raise AssertionError((method,path))
    billing.api=fake
    pix={**consent,'forma_pagamento':'PIX','aceite_pix':'pix_mensal_sem_debito_automatico_v1'}
    def event(pid,n,kind='PAYMENT_CONFIRMED'):
        return public.post('/api/saas/webhook',json={'id':'evt_pix_'+str(n),'event':kind,'payment':{'id':pid,'status':'CONFIRMED','value':1}},
            headers={'asaas-access-token':'p'*48})
    assert public.post('/api/saas/checkout',json=pix).status_code==401
    assert a.post('/api/saas/checkout',json={**consent,'forma_pagamento':'PIX'},headers=headers[0]).status_code==422
    assert a.post('/api/saas/checkout',json={**consent,'forma_pagamento':'BOLETO'},headers=headers[0]).status_code==422
    assert a.post('/api/saas/checkout',json=pix,headers=headers[0]).status_code==200
    first=a.get('/api/saas/assinatura').json()['contratos'][0]
    assert first['forma_pagamento']=='PIX' and first['condicoes']['oferta']=='pix_60_v1'
    assert a.post('/api/saas/checkout',json=pix,headers=headers[0]).status_code==200 and len(checkouts)==1
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==409
    assert b.post('/api/saas/contratos/'+first['id']+'/cancelar',headers=headers[1]).status_code==404
    qr_url='/api/saas/contratos/'+first['id']+'/pix'
    assert public.get(qr_url).status_code==401
    assert b.get(qr_url).status_code==404
    payments['pay_pix_1']['omit']=True
    assert a.get(qr_url).json()['situacao']=='aguardando_dados'
    payments['pay_pix_1']['omit']=False
    qr_response=a.get(qr_url)
    assert qr_response.status_code==200,qr_response.text
    qr_data=qr_response.json()
    assert qr_response.headers['cache-control']=='no-store'
    assert qr_data['payload']==qr_payload and qr_data['valor_centavos']==6000
    assert all(isinstance(v,bool) for row in qr_data['matriz'] for v in row)
    if os.environ.get('QR_DECODE_TEST'):
        import cv2,numpy as np
        matrix=np.array(qr_data['matriz'],dtype=np.uint8)
        image=cv2.resize((1-matrix)*255,None,fx=8,fy=8,interpolation=cv2.INTER_NEAREST)
        decoded,_,_=cv2.QRCodeDetector().detectAndDecode(image)
        assert decoded==qr_payload
    qr_expired=True
    assert a.get(qr_url).json()['situacao']=='expirado'
    qr_expired=False
    original_payload=qr_payload;qr_payload='INVALIDO'
    assert a.get(qr_url).status_code==502
    qr_payload=original_payload
    assert event('pay_pix_1',1).status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    # Dados financeiros do webhook não concedem acesso.
    payments['pay_pix_1'].update(status='RECEIVED',paymentDate=datetime.now(appmod.BRASIL).date().isoformat(),value=1)
    assert event('pay_pix_1',2).status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    payments['pay_pix_1']['value']=60
    assert event('pay_pix_1',3).status_code==200
    assert event('pay_pix_1',3).status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is True
    assert b.get('/api/assinatura').json()['ativa'] is False
    assert a.get(qr_url).json()['situacao']=='pago'
    summary=a.get('/api/saas/assinatura').json()
    assert summary['contratos'][0]['status']=='quitada' and len(summary['pagamentos'])==1
    assert summary['ciclos_promocionais_restantes']==2
    assert a.post('/api/saas/checkout',json=pix,headers=headers[0]).status_code==409
    # Estorno revoga acesso e não reinicia o benefício promocional.
    os.environ['ASAAS_PRODUCTION_ENABLED']='false'
    payments['pay_pix_1'].update(status='REFUNDED',omit=True)
    assert event('pay_pix_1',4,'PAYMENT_REFUNDED').status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    assert a.get('/api/saas/assinatura').json()['ciclos_promocionais_restantes']==2
    assert a.post('/api/saas/checkout',json=pix,headers=headers[0]).status_code==503
    os.environ['ASAAS_PRODUCTION_ENABLED']='true'
    for cycle in (2,3,4):
        assert a.post('/api/saas/checkout',json=pix,headers=headers[0]).status_code==200
        assert checkouts[-1]['items'][0]['value']==(60 if cycle<=3 else 90)
        pid='pay_pix_'+str(cycle)
        payments[pid].update(status='RECEIVED',paymentDate=datetime.now(appmod.BRASIL).date().isoformat())
        assert event(pid,cycle+10).status_code==200
        assert a.get('/api/assinatura').json()['ativa'] is True
        if cycle<4:
            # Simula fim do período pago sem esperar um mês.
            with appmod.banco() as db:
                db.execute('UPDATE saas_cobrancas SET periodo_fim=? WHERE ambiente=?',(datetime.now(appmod.BRASIL).date().isoformat(),'production'))
    assert a.get('/api/saas/assinatura').json()['valor_centavos']==9000
    payments['pay_pix_4'].update(deleted=True,omit=True)
    assert event('pay_pix_4',30,'PAYMENT_DELETED').status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    # Histórico pode ser sincronizado repetidamente sem duplicar receitas.
    assert a.post('/api/saas/sincronizar',headers=headers[0]).status_code==200
    assert len(a.get('/api/saas/assinatura').json()['pagamentos'])==4
    assert b.get('/api/saas/assinatura').json()['pagamentos']==[]
    # Cancelar PIX pendente invalida cobrança e permite nova contratação.
    assert b.post('/api/saas/checkout',json=pix,headers=headers[1]).status_code==200
    other=b.get('/api/saas/assinatura').json()['contratos'][0]
    assert event('pay_pix_5',40,'PAYMENT_CREATED').status_code==200
    assert b.post('/api/saas/contratos/'+other['id']+'/cancelar',headers=headers[1]).status_code==200
    assert payments['pay_pix_5']['deleted'] is True
    assert b.post('/api/saas/checkout',json=pix,headers=headers[1]).status_code==200
    assert checkouts[-1]['items'][0]['value']==60
    # Estorno recebido antes do evento de pagamento mantém consumo histórico.
    payments['pay_pix_6'].update(status='REFUNDED',paymentDate=datetime.now(appmod.BRASIL).date().isoformat())
    assert event('pay_pix_6',41,'PAYMENT_REFUNDED').status_code==200
    assert b.get('/api/assinatura').json()['ativa'] is False
    assert b.get('/api/saas/assinatura').json()['ciclos_promocionais_restantes']==2
print('OK PIX: checkout avulso, preço no servidor, confirmação, isolamento, deduplicação, três meses, estorno e exclusão.')
