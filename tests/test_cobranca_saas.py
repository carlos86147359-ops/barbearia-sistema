"""Homologação local: API Asaas simulada, sem banco ou cartão real."""
import importlib.util
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    for name in ('DATABASE_URL','RENDER'):os.environ.pop(name,None)
    os.environ.update(BARBER_DB_PATH=str(Path(tmp)/'test.db'),BILLING_ENABLED='true',ADMIN_EMAILS='',
        ASAAS_ENV='sandbox',ASAAS_API_KEY='fake-test-only',ASAAS_WEBHOOK_TOKEN='x'*48,
        PUBLIC_BASE_URL='https://example.test',ASAAS_SANDBOX_TEST_EMAILS='')
    spec=importlib.util.spec_from_file_location('asaas_test_app',ROOT/'app.py')
    appmod=importlib.util.module_from_spec(spec);spec.loader.exec_module(appmod)
    import cobranca_saas as billing
    a,b,public=TestClient(appmod.app),TestClient(appmod.app),TestClient(appmod.app)
    headers=[]
    for i,client in enumerate((a,b)):
        r=client.post('/api/cadastro',json={'nome':'Loja '+str(i),'slug':'asaas-'+str(i),'email':f'owner{i}@example.test','senha':'SenhaTeste!12345','aceite_termos':True})
        assert r.status_code==201,r.text
        headers.append({'x-csrf-token':r.json()['csrf']})
    os.environ['ADMIN_EMAILS']='owner0@example.test'
    assert public.get('/api/saas/assinatura').status_code==401
    assert b.get('/api/saas/assinatura').json()=={'disponivel':False}
    assert b.post('/api/saas/checkout',headers=headers[1]).status_code==403
    assert b.get('/api/gestao/asaas').status_code==403
    assert a.post('/api/saas/checkout').status_code==403
    os.environ['ASAAS_SANDBOX_TEST_EMAILS']='owner1@example.test'
    assert b.get('/api/saas/assinatura').json()['disponivel'] is True
    assert b.get('/api/gestao/asaas').status_code==403
    os.environ['ASAAS_SANDBOX_TEST_EMAILS']=''
    before=a.get('/api/assinatura').json()
    calls=[];payment={'id':'pay_1','subscription':'sub_1','customer':'cus_1','value':90,'billingType':'CREDIT_CARD',
        'dueDate':date.today().isoformat(),'status':'PENDING','checkoutSession':'checkout_1','invoiceUrl':'https://sandbox.asaas.com/i/test'}
    sub={'id':'sub_1','customer':'cus_1','value':90,'billingType':'CREDIT_CARD','cycle':'MONTHLY','status':'ACTIVE','nextDueDate':billing.month_end(date.today().isoformat())}
    visible=False; fail=False
    def fake(method,path,body=None):
        global fail
        calls.append((method,path,body))
        if method=='POST' and path=='/checkouts':
            assert len(body['items'][0]['name'])<=30
            assert body['items'][0]['value']==90 and body['chargeTypes']==['RECURRENT']
            assert body['callback']['successUrl']=='https://example.test/painel#plano'
            if fail:raise HTTPException(502,'timeout')
            return {'id':'checkout_1'}
        if method=='PUT' and path=='/subscriptions/sub_1':sub['status']='INACTIVE';return sub.copy()
        if path.startswith('/payments?'):return {'data':[payment.copy()] if visible else []}
        if path=='/subscriptions/sub_1':return sub.copy()
        if path.startswith('/subscriptions/sub_1/payments?'):return {'data':[payment.copy()] if visible else [],'hasMore':False}
        if path=='/payments/pay_1':return payment.copy()
        if path=='/subscriptions/sub_foreign':return {**sub,'id':'sub_foreign','customer':'cus_foreign'}
        raise AssertionError((method,path,body))
    billing.api=fake
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:a.post('/api/saas/checkout',headers=headers[0]),range(2)))
    assert all(r.status_code in (200,409) for r in responses),[(r.status_code,r.text) for r in responses]
    assert len([x for x in calls if x[:2]==('POST','/checkouts')])==1
    data=a.get('/api/saas/assinatura').json();cid=data['contratos'][0]['id']
    assert data['contratos'][0]['checkout_url'].startswith('https://sandbox.asaas.com/')
    assert a.get('/api/assinatura').json()==before
    assert b.post('/api/saas/contratos/'+cid+'/cancelar',headers=headers[1]).status_code==403
    # Outro dono autorizado à homologação continua sem acesso ao contrato alheio.
    os.environ['ADMIN_EMAILS']+=' ,owner1@example.test'
    assert b.post('/api/saas/contratos/'+cid+'/cancelar',headers=headers[1]).status_code==404
    os.environ['ADMIN_EMAILS']='owner0@example.test'
    wh={'asaas-access-token':'x'*48}
    payload={'id':'evt_1','event':'CHECKOUT_PAID','checkout':{'id':'checkout_1'}}
    assert public.post('/api/saas/webhook',json=payload).status_code==401
    assert public.post('/api/saas/webhook',content=b'x'*128001,headers=wh).status_code==413
    assert public.post('/api/saas/webhook',json={'id':'e','event':'PAYMENT_CREATED','payment':{'id':'../../customers'}},headers=wh).status_code==422
    visible=True
    assert public.post('/api/saas/webhook',json=payload,headers=wh).status_code==200
    assert a.get('/api/saas/assinatura').json()['contratos'][0]['status']=='aguardando_pagamento'
    # Webhook não decide valor ou quitação: lê o estado financeiro da API.
    payload={'id':'evt_2','event':'PAYMENT_CONFIRMED','payment':{**payment,'value':1,'status':'CONFIRMED'}}
    assert public.post('/api/saas/webhook',json=payload,headers=wh).status_code==200
    assert a.get('/api/saas/assinatura').json()['contratos'][0]['pago_ate'] is None
    payment.update(status='CONFIRMED',paymentDate=date.today().isoformat())
    payload['id']='evt_3'
    for _ in range(2):assert public.post('/api/saas/webhook',json=payload,headers=wh).status_code==200
    result=a.get('/api/saas/assinatura').json();paid_until=result['contratos'][0]['pago_ate']
    assert paid_until and len(result['pagamentos'])==1 and result['contratos'][0]['status']=='ativa'
    assert a.get('/api/assinatura').json()==before,'Sandbox alterou o acesso real!'
    with appmod.banco() as db:
        assert db.execute('SELECT COUNT(*) AS n FROM saas_webhooks').fetchone()['n']==3
        assert db.execute('SELECT COUNT(*) AS n FROM pagamentos').fetchone()['n']==0
    # Evento antigo de atraso não reverte pagamento que já está confirmado.
    payload['id']='evt_4';payload['event']='PAYMENT_OVERDUE'
    assert public.post('/api/saas/webhook',json=payload,headers=wh).status_code==200
    assert a.get('/api/saas/assinatura').json()['contratos'][0]['pago_ate']==paid_until
    payment['status']='REFUNDED';payload['id']='evt_5';payload['event']='PAYMENT_REFUNDED'
    assert public.post('/api/saas/webhook',json=payload,headers=wh).status_code==200
    assert a.get('/api/saas/assinatura').json()['contratos'][0]['pago_ate'] is None
    # Erros externos mantêm a fila recuperável, sem esconder ou apagar eventos.
    payment['value']=1;payload['id']='evt_6'
    assert public.post('/api/saas/webhook',json=payload,headers=wh).status_code==200
    with appmod.banco() as db:assert db.execute('SELECT status FROM saas_webhooks WHERE id=?',('sandbox:evt_6',)).fetchone()['status']=='pendente'
    payment['value']=90
    assert a.post('/api/saas/contratos/'+cid+'/cancelar',headers=headers[0]).status_code==200
    assert sub['status']=='INACTIVE'
    assert len(a.get('/api/saas/assinatura').json()['pagamentos'])==1
    # Timeout na contratação não permite repetir a cobrança inadvertidamente.
    fail=True
    assert a.post('/api/saas/checkout',headers=headers[0]).status_code==502
    count=len(calls)
    assert a.post('/api/saas/checkout',headers=headers[0]).status_code==409
    assert len(calls)==count
    assert any(r['status']=='incerta' for r in a.get('/api/saas/assinatura').json()['contratos'])
    uncertain=next(r['id'] for r in a.get('/api/saas/assinatura').json()['contratos'] if r['status']=='incerta')
    recovery='/api/gestao/asaas/'+uncertain+'/encerrar-rejeitada'
    assert b.post(recovery,headers=headers[1]).status_code==403
    assert a.post(recovery).status_code==403
    assert a.post('/api/gestao/asaas/'+cid+'/encerrar-rejeitada',headers=headers[0]).status_code==409
    assert a.post(recovery,headers=headers[0]).status_code==200
    assert a.post(recovery,headers=headers[0]).status_code==200
    previous_fake=billing.api
    def rejected(method,path,body=None):
        if method=='POST' and path=='/checkouts': raise billing.CheckoutRejected()
        return previous_fake(method,path,body)
    billing.api=rejected
    assert a.post('/api/saas/checkout',headers=headers[0]).status_code==422
    assert not any(r['status']=='incerta' for r in a.get('/api/saas/assinatura').json()['contratos'])
    billing.api=previous_fake
    os.environ['ASAAS_ENV']='production'
    assert a.get('/api/saas/assinatura').json()=={'disponivel':False}
    assert a.post('/api/saas/checkout',headers=headers[0]).status_code==503
    os.environ['ASAAS_ENV']='sandbox'
    # Round-trip da cópia, incluindo tabelas novas e versão anterior sem Asaas.
    import recursos,restaurar_backup
    with appmod.banco() as db:
        tables={t:[dict(r) for r in db.execute('SELECT '+','.join(cols)+' FROM '+t).fetchall()] for t,cols in recursos.TABLES.items()}
    document={'formato':'barbersaas-backup','versao':1,'tabelas':tables}
    backup=Path(tmp)/'backup.json';backup.write_text(json.dumps(document),encoding='utf-8')
    restored=restaurar_backup.ler(backup,None)
    counts=restaurar_backup.restaurar(restored,Path(tmp)/'restore.db')
    assert counts['saas_contratos']==3 and counts['saas_cobrancas']==1
    document['tabelas']={t:rows for t,rows in tables.items() if t not in billing.TABLES}
    backup.write_text(json.dumps(document),encoding='utf-8')
    assert restaurar_backup.ler(backup,None)['saas_contratos']==[]
print('OK: checkout concorrente, webhook, deduplicação, isolamento, pagamentos, cancelamento, timeout e backup.')
