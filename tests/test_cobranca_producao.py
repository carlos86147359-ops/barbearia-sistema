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
    a,b,public=TestClient(appmod.app),TestClient(appmod.app),TestClient(appmod.app)
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
    calls=[];subscriptions={};payments={};checkouts=[]
    def fake(method,path,body=None):
        calls.append((method,path,body))
        if method=='POST' and path=='/checkouts':
            n=len(checkouts)+1;cid='checkout_'+str(n);checkouts.append(body)
            sid='sub_'+str(n);cus='cus_'+str(n)
            subscriptions[sid]={'id':sid,'customer':cus,'value':body['items'][0]['value'],'cycle':'MONTHLY','billingType':'CREDIT_CARD','status':'ACTIVE',
                'endDate':body['subscription'].get('endDate'),'nextDueDate':body['subscription']['nextDueDate'][:10]}
            payments['pay_'+str(n)]={'id':'pay_'+str(n),'subscription':sid,'customer':cus,'value':body['items'][0]['value'],'billingType':'CREDIT_CARD',
                'checkoutSession':cid,'dueDate':body['subscription']['nextDueDate'][:10],'status':'PENDING','invoiceUrl':'https://www.asaas.com/i/test'}
            return {'id':cid}
        if path.startswith('/payments?'):
            return {'data':[]} # Webhook recupera cobrança canônica.
        if path.startswith('/payments/'):
            return {'deleted':True} if payments[path.split('/')[2]].get('deleted') else dict(payments[path.split('/')[2]])
        if path.startswith('/subscriptions/'):
            sid=path.split('/')[2]
            if method=='PUT':
                subscriptions[sid]['status']='INACTIVE';return dict(subscriptions[sid])
            if '/payments?' in path:
                return {'data':[dict(p) for p in payments.values() if p['subscription']==sid and not p.get('omit')],'hasMore':False}
            return dict(subscriptions[sid])
        raise AssertionError((method,path))
    billing.api=fake
    def event(pid,n,kind='PAYMENT_CONFIRMED',token='p'*48):
        return public.post('/api/saas/webhook',json={'id':'evt_'+str(n),'event':kind,'payment':{'id':pid,'status':'CONFIRMED','value':1}},
            headers={'asaas-access-token':token})
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==200
    first=a.get('/api/saas/assinatura').json()['contratos'][0];cid=first['id']
    assert first['checkout_url'].startswith('https://www.asaas.com/')
    body=checkouts[0];start=body['subscription']['nextDueDate'][:10]
    assert body['items'][0]['value']==60 and body['subscription']['endDate'][:10]==billing.add_months(start,2)
    assert first['condicoes']['oferta']=='tres_meses_60_v1'
    assert len(checkouts)==1
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==200 and len(checkouts)==1
    assert b.post('/api/saas/contratos/'+cid+'/cancelar',headers=headers[1]).status_code==404
    assert a.get('/api/assinatura').json()['ativa'] is False
    assert event('pay_1',1,token='x'*48).status_code==401
    assert event('pay_1',1).status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    payments['pay_1']['status']='CONFIRMED';payments['pay_1']['paymentDate']=start
    assert event('pay_1',2).status_code==200
    assert event('pay_1',2).status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is True
    assert b.get('/api/assinatura').json()['ativa'] is False
    assert len(a.get('/api/saas/assinatura').json()['pagamentos'])==1
    # Kill switch impede novas contratações, mas continua processando estornos.
    os.environ['ASAAS_PRODUCTION_ENABLED']='false'
    payments['pay_1'].update(status='REFUNDED',omit=True)
    assert event('pay_1',3,'PAYMENT_REFUNDED').status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    payments['pay_1'].update(status='CONFIRMED',omit=False)
    assert event('pay_1',4).status_code==200
    # Cortesia e período Pix prévio sobrevivem a estornos.
    with appmod.banco() as db:
        shop=db.execute('SELECT loja_id FROM saas_contratos WHERE id=?',(cid,)).fetchone()['loja_id']
        due=(datetime.now(appmod.BRASIL)+timedelta(days=80)).isoformat()
        db.execute('INSERT INTO assinaturas(loja_id,vencimento) VALUES(?,?) ON CONFLICT(loja_id) DO UPDATE SET vencimento=excluded.vencimento',(shop,due))
    payments['pay_1']['status']='REFUNDED'
    assert event('pay_1',5,'PAYMENT_REFUNDED').status_code==200
    assert a.get('/api/assinatura').json()['vencimento']==due
    with appmod.banco() as db: db.execute('DELETE FROM assinaturas WHERE loja_id=?',(shop,))
    # Cancelar preserva histórico e não reinicia a promoção.
    os.environ['ASAAS_PRODUCTION_ENABLED']='true'
    assert a.post('/api/saas/contratos/'+cid+'/cancelar',headers=headers[0]).status_code==200
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==200
    assert checkouts[1]['items'][0]['value']==90 and 'endDate' not in checkouts[1]['subscription']
    second=next(c for c in a.get('/api/saas/assinatura').json()['contratos'] if c['id']!=cid)
    assert second['condicoes']['oferta']=='mensal_90_v1'
    assert event('pay_2',6).status_code==200
    payments['pay_2'].update(status='CONFIRMED',paymentDate=start)
    assert event('pay_2',7).status_code==200
    assert a.post('/api/saas/contratos/'+second['id']+'/cancelar',headers=headers[0]).status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is True
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==409
    # Exclusão canônica de pagamento também revoga o acesso.
    payments['pay_2'].update(deleted=True,omit=True)
    assert event('pay_2',8,'PAYMENT_DELETED').status_code==200
    assert a.get('/api/assinatura').json()['ativa'] is False
    # Calendário ancorado no dia original: fevereiro não desloca março.
    assert b.post('/api/saas/checkout',json=consent,headers=headers[1]).status_code==200
    third=b.get('/api/saas/assinatura').json()['contratos'][0]
    with appmod.banco() as db:
        db.execute('UPDATE saas_condicoes SET primeiro_vencimento=?,ultimo_vencimento=? WHERE id=?',('2028-01-31','2028-03-31',third['id']))
    subscriptions['sub_3']['endDate']='2028-03-31'
    payments['pay_3'].update(dueDate='2028-02-29',status='CONFIRMED',paymentDate='2028-02-29')
    assert event('pay_3',9).status_code==200
    assert b.get('/api/saas/assinatura').json()['contratos'][0]['pago_ate']=='2028-03-31'
    payments['pay_fourth']={**payments['pay_3'],'id':'pay_fourth','dueDate':'2028-04-30'}
    assert event('pay_fourth',10).status_code==200
    with appmod.banco() as db:
        assert db.execute('SELECT status FROM saas_webhooks WHERE id=?',('production:evt_10',)).fetchone()['status']=='pendente'
        assert not db.execute('SELECT id FROM saas_cobrancas WHERE provedor_id=?',('pay_fourth',)).fetchone()
    payments.pop('pay_fourth')
    # Simula terceiro ciclo e confirma ausência de quarto ciclo promocional.
    assert billing.add_months('2028-01-31',2)=='2028-03-31'
    assert billing.add_months('2028-01-31',1)=='2028-02-29'
    assert billing.add_months('2026-12-31',2)=='2027-02-28'
    with appmod.banco() as db:
        today=date.today().isoformat()
        db.execute('UPDATE saas_cobrancas SET status=?,periodo_fim=? WHERE contrato_id=?',('CONFIRMED',today,second['id']))
        assert billing.production_access(db,shop,today) is None
        user=db.execute('SELECT usuario_id FROM saas_contratos WHERE id=?',(cid,)).fetchone()['usuario_id']
        db.execute('INSERT INTO cortesias(loja_id,administrador_id,criado_em,motivo) VALUES(?,?,?,?)',(shop,user,start,'Teste'))
    assert a.get('/api/assinatura').json()['status']=='cortesia'
    assert a.get('/api/saas/assinatura').json()=={'disponivel':False}
    assert a.post('/api/saas/checkout',json=consent,headers=headers[0]).status_code==409
    assert a.get('/api/gestao/asaas').status_code==403
    os.environ['ADMIN_EMAILS']='prod0@example.test'
    assert a.get('/api/gestao/asaas').json()['ambiente']=='production'
    assert a.post('/api/gestao/asaas/'+cid+'/encerrar-rejeitada',headers=headers[0]).status_code==503
    # Backup produção e cópia antiga sem condições continuam válidos.
    import recursos,restaurar_backup
    with appmod.banco() as db:
        tables={t:[dict(r) for r in db.execute('SELECT '+','.join(cols)+' FROM '+t).fetchall()] for t,cols in recursos.TABLES.items()}
    document={'formato':'barbersaas-backup','versao':1,'tabelas':tables}
    backup=Path(tmp)/'backup.json';backup.write_text(json.dumps(document),encoding='utf-8')
    restored=restaurar_backup.ler(backup,None)
    counts=restaurar_backup.restaurar(restored,Path(tmp)/'restore.db')
    assert counts['saas_condicoes']==3
    document['tabelas'].pop('saas_condicoes')
    backup.write_text(json.dumps(document),encoding='utf-8')
    assert restaurar_backup.ler(backup,None)['saas_condicoes']==[]
print('OK produção simulada: oferta, consentimento, isolamento, pagamento, estorno, cancelamento, cortesia, Pix e backup.')
