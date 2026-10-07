"""Fluxo completo em bancos descartáveis. Nunca acessa o banco real."""
import os,json,tempfile,importlib.util,sqlite3,secrets
from pathlib import Path
from datetime import datetime,timedelta,date
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
dsn=os.environ.get('MONTHLY_TEST_DATABASE_URL')
schema=None
if dsn:
    assert urlparse(dsn).hostname in ('localhost','127.0.0.1')
    import psycopg
    schema='monthly_test_'+secrets.token_hex(8)
    with psycopg.connect(dsn) as db:db.execute('CREATE SCHEMA '+schema)
    dsn+=('&' if '?' in dsn else '?')+'options=-csearch_path%3D'+schema
with tempfile.TemporaryDirectory() as tmp:
    os.environ.update(BARBER_DB_PATH=str(Path(tmp)/'monthly.db'),BILLING_ENABLED='false',ADMIN_EMAILS='')
    os.environ.pop('RENDER',None)
    if dsn:os.environ['DATABASE_URL']=dsn
    else:os.environ.pop('DATABASE_URL',None)
    spec=importlib.util.spec_from_file_location('monthly_test_app',ROOT/'app.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    a,b,g=TestClient(mod.app),TestClient(mod.app),TestClient(mod.app)
    password='SenhaTeste!12345';hs=[]
    for i,client in enumerate((a,b)):
        r=client.post('/api/cadastro',json={'nome':'Mensal '+str(i),'slug':'mensal-'+str(i),'email':f'mensal{i}@example.com','senha':password,'aceite_termos':True});assert r.status_code==201,r.text
        hs.append({'X-CSRF-Token':r.json()['csrf']})
        cfg=client.get('/api/configuracao').json();cfg.update(whatsapp='11900000000',comissao=40,barbeiros=[{'id':'prof','nome':'Carlos'}],servicos=[{'id':'corte','nome':'Corte','preco':35,'duracao':30},{'id':'barba','nome':'Barba','preco':25,'duracao':30}],dias=list(range(7)),periodos=[{'inicio':'08:00','fim':'20:00'}],intervalo=30)
        r=client.put('/api/configuracao',json=cfg,headers=hs[i]);assert r.status_code==200,r.text
    today=datetime.now(mod.BRASIL).date().isoformat();day=(datetime.now(mod.BRASIL)+timedelta(days=2)).date().isoformat()
    slots=iter(['08:00','08:30','09:00','09:30','10:00','10:30','11:00','11:30','12:00','12:30','13:00','13:30','14:00','14:30','15:00','15:30'])
    def book(phone='11911111111',service='corte',shop='mensal-0'):
        r=g.post('/api/publico/'+shop+'/agendamentos',json={'cliente_nome':'João Silva','cliente_telefone':phone,'barbeiro_id':'prof','servico_id':service,'data':day,'horario':next(slots)})
        assert r.status_code==201,r.text
        return r.json()['agendamento_id']
    first=book()
    path='/api/mensalistas'
    plan={'nome':'Plano Corte Mensal','descricao':'Corte por ciclo','valor_centavos':8990,'servicos':[{'servico_id':'corte','quantidade':1}],'ciclo_unidade':'meses','ciclo_quantidade':1,'status':'ativo','beneficios':'Atendimento com hora marcada'}
    r=a.post(path+'/planos',json=plan,headers=hs[0]);assert r.status_code==201,r.text
    pid=r.json()['id']
    assert g.get(path+'/planos').status_code==401
    assert b.get(path+'/planos').json()==[]
    assert b.put(path+'/planos/'+pid,json=plan,headers=hs[1]).status_code==404
    assert a.post(path+'/planos',json=plan).status_code==403
    assert a.post(path+'/planos',json={**plan,'servicos':[{'servico_id':'foreign','quantidade':1}]},headers=hs[0]).status_code==422
    enrollment={'cliente_telefone':'+55 (11) 91111-1111','plano_id':pid,'inicio':today,'vencimento':today,'pagamento':'pix','desconto_centavos':990,'observacoes':'Cliente atual'}
    assert a.post(path+'/assinantes',json={**enrollment,'cliente_telefone':'11955555555'},headers=hs[0]).status_code==404
    assert b.post(path+'/assinantes',json=enrollment,headers=hs[1]).status_code==404
    r=a.post(path+'/assinantes',json=enrollment,headers=hs[0]);assert r.status_code==201,r.text
    member=r.json();mid=member['id'];cid=member['ciclo']['id']
    assert member['ciclo']['total_centavos']==8000 and not member['ativo']
    assert a.post(path+'/assinantes',json=enrollment,headers=hs[0]).status_code==409
    assert b.get(path+'/assinantes/'+mid).status_code==404
    assert b.get(path+'/cliente/11911111111').json()['assinaturas']==[]
    assert len(a.get(path+'/cliente/5511911111111').json()['assinaturas'])==1
    def finish(rid,use=True,client=a,headers=hs[0]):return client.patch('/api/agendamentos/'+str(rid),json={'status':'concluido','assinatura':use},headers=headers)
    assert finish(first).status_code==409 # Pending invoice does not grant credits.
    assert a.get(path+'/assinantes/'+mid).json()['utilizacoes']==[]
    paid={'confirmado':True,'data_pagamento':today,'pagamento':'pix'}
    assert a.post(path+'/ciclos/'+cid+'/pagamento',json={**paid,'confirmado':False},headers=hs[0]).status_code==422
    assert b.post(path+'/ciclos/'+cid+'/pagamento',json=paid,headers=hs[1]).status_code==404
    def pay(_):return a.post(path+'/ciclos/'+cid+'/pagamento',json=paid,headers=hs[0])
    with ThreadPoolExecutor(max_workers=2) as pool:receipts=list(pool.map(pay,range(2)))
    assert all(r.status_code==200 for r in receipts),[(r.status_code,r.text) for r in receipts]
    assert sum(not r.json()['ja_confirmado'] for r in receipts)==1
    assert a.get('/api/produtos/resumo?inicio='+today+'&fim='+today).json()['assinaturas_centavos']==8000
    row=next(r for r in a.get('/api/agendamentos').json() if r['id']==first)
    assert row['assinatura']['disponivel'] and row['protecao_assinatura']
    assert a.patch('/api/agendamentos/'+str(first),json={'status':'concluido'},headers=hs[0]).status_code==409
    assert finish(first,False).status_code==409
    # Cancel/no-show represented by current cancellation status consumes nothing.
    cancelled=book()
    assert a.patch('/api/agendamentos/'+str(cancelled),json={'status':'cancelado'},headers=hs[0]).status_code==200
    assert a.get(path+'/assinantes/'+mid).json()['utilizacoes']==[]
    assert finish(cancelled).status_code==409
    # Staff grants reuse existing cash permission record and do not expose prices.
    with mod.banco() as db:
        owner=dict(db.execute('SELECT * FROM usuarios WHERE email=?',('mensal0@example.com',)).fetchone())
        db.execute('INSERT INTO funcionarios(id,loja_id,barbeiro_id,email,senha,ativo) VALUES(?,?,?,?,?,1)',('monthly-staff',owner['loja_id'],'prof','monthly-staff@example.com',owner['senha']))
    staff=TestClient(mod.app);r=staff.post('/api/login',json={'email':'monthly-staff@example.com','senha':password});assert r.status_code==200,r.text
    sh={'X-CSRF-Token':r.json()['csrf']}
    assert staff.get(path+'/assinantes').status_code==403
    assert finish(first,True,staff,sh).status_code==403
    grants={'assinaturas_ver':True,'assinaturas_utilizar':True,'assinaturas_historico':True,'assinaturas_cadastrar':True}
    assert a.put(path+'/permissoes/monthly-staff',json={'permissoes':grants},headers=hs[0]).status_code==200
    assert a.put('/api/produtos/permissoes/monthly-staff',json={'permissoes':{'acessar_pdv':True,'registrar_venda':True}},headers=hs[0]).status_code==200
    assert staff.get(path+'/acesso').json()['permissoes']['assinaturas_utilizar']
    assert 'valor_centavos' not in staff.get(path+'/assinantes/'+mid).text
    assert 'total_centavos' not in staff.get(path+'/planos').text
    assert staff.post(path+'/ciclos/'+cid+'/pagamento',json=paid,headers=sh).status_code==403
    assert staff.put(path+'/planos/'+pid,json=plan,headers=sh).status_code==403
    assert staff.post(path+'/assinantes/'+mid+'/acao',json={'acao':'pausar'},headers=sh).status_code==403
    assert b.put(path+'/permissoes/monthly-staff',json={'permissoes':grants},headers=hs[1]).status_code==404
    # Two simultaneous uses against quota 1: exactly one succeeds.
    second=book()
    def compete(rid):return finish(rid,True,staff,sh)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(compete,[first,second]))
    assert sorted(r.status_code for r in results)==[200,409],[(r.status_code,r.text) for r in results]
    accepted=[rid for rid,res in zip([first,second],results) if res.status_code==200][0]
    rejected=second if accepted==first else first
    assert finish(accepted,True,staff,sh).status_code==200
    assert finish(rejected,True).status_code==409
    assert finish(rejected,False).status_code==200
    detail=a.get(path+'/assinantes/'+mid).json();assert len(detail['utilizacoes'])==1 and detail['assinante']['ciclo']['servicos'][0]['restantes']==0
    rows=a.get('/api/agendamentos').json();covered=next(r for r in rows if r['id']==accepted)
    assert covered['preco']==35 and covered['comissao_pct']==40 and covered['incluido_assinatura']
    cash=a.get('/api/produtos/resumo?inicio='+day+'&fim='+day).json();assert cash['servicos_centavos']==3500 and cash['assinaturas_centavos']==0
    assert staff.patch('/api/agendamentos/'+str(accepted),json={'status':'agendado'},headers=sh).status_code==403
    assert a.patch('/api/agendamentos/'+str(accepted),json={'status':'agendado'},headers=hs[0]).status_code==200
    detail=a.get(path+'/assinantes/'+mid).json();assert detail['utilizacoes'][0]['estornada_em'] and detail['assinante']['ciclo']['servicos'][0]['restantes']==1
    assert finish(accepted).status_code==200
    assert len(a.get(path+'/assinantes/'+mid).json()['utilizacoes'])==2
    # Future renewal must not displace the paid cycle that covers today's service.
    end=member['ciclo']['fim']
    assert a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'renovar','data':end},headers=hs[0]).status_code==200
    hist=a.get(path+'/assinantes/'+mid).json();assert len(hist['ciclos'])==2 and hist['assinante']['ativo']
    assert hist['assinante']['ciclo']['id']==cid
    assert hist['ciclos'][0]['servicos'][0]['utilizados']==0 and hist['ciclos'][1]['servicos'][0]['utilizados']==1
    assert a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'renovar','data':today},headers=hs[0]).status_code==409
    # Cancel a concrete future invoice without affecting the current paid cycle.
    future_id=hist['ciclos'][0]['id']
    assert b.post(path+'/assinantes/'+mid+'/acao',json={'acao':'cancelar_cobranca','ciclo_id':future_id},headers=hs[1]).status_code==404
    assert a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'cancelar_cobranca','ciclo_id':future_id},headers=hs[0]).status_code==200
    hist=a.get(path+'/assinantes/'+mid).json();assert hist['assinante']['ativo'] and hist['ciclos'][0]['status']=='cancelado'
    # Plan changes and archiving preserve all snapshots.
    unlimited={**plan,'nome':'Ilimitado','valor_centavos':12990,'servicos':[{'servico_id':'corte','quantidade':None}]}
    r=a.post(path+'/planos',json=unlimited,headers=hs[0]);assert r.status_code==201,r.text
    unlimited_id=r.json()['id']
    assert a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'trocar_plano','plano_id':unlimited_id},headers=hs[0]).status_code==200
    assert a.get(path+'/assinantes/'+mid).json()['assinante']['ciclo']['plano_nome']=='Plano Corte Mensal'
    assert a.put(path+'/planos/'+pid,json={**plan,'nome':'Alterado','status':'arquivado','valor_centavos':99999},headers=hs[0]).status_code==200
    assert a.get(path+'/assinantes/'+mid).json()['ciclos'][-1]['total_centavos']==8000
    assert a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'pausar'},headers=hs[0]).json()['status_visual']=='pausada'
    assert a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'retomar'},headers=hs[0]).status_code==200
    assert b.post(path+'/assinantes/'+mid+'/acao',json={'acao':'cancelar','data':today},headers=hs[1]).status_code==404
    r=a.post(path+'/assinantes/'+mid+'/acao',json={'acao':'cancelar','data':today,'motivo':'Teste'},headers=hs[0]);assert r.status_code==200
    hist=a.get(path+'/assinantes/'+mid).json();assert hist['assinante']['status']=='cancelada' and hist['ciclos'][-1]['status']=='pago' and hist['ciclos'][0]['status']=='cancelado'
    assert a.get('/api/produtos/resumo?inicio='+today+'&fim='+today).json()['assinaturas_centavos']==8000
    # Rejoin same existing customer, unlimited tracking and ordinary service.
    r=a.post(path+'/assinantes',json={**enrollment,'plano_id':unlimited_id,'desconto_centavos':0},headers=hs[0]);assert r.status_code==201,r.text
    new=r.json();newid=new['id']
    assert a.post(path+'/ciclos/'+new['ciclo']['id']+'/pagamento',json=paid,headers=hs[0]).status_code==200
    for _ in range(2):assert finish(book()).status_code==200
    assert finish(book(service='barba'),False).status_code==200
    hist=a.get(path+'/assinantes/'+newid).json();s=hist['assinante']['ciclo']['servicos'][0];assert s['quantidade'] is None and s['utilizados']==2 and s['restantes'] is None
    summary=a.get(path+'/dashboard?inicio='+today+'&fim='+today).json()
    assert summary['pagas']==2 and summary['receita_centavos']==20990 and summary['cancelamentos']==1 and summary['ativos']==1
    assert b.get(path+'/dashboard').json()['receita_centavos']==0
    # Due renewal creates a pending invoice once; old credits/history remain.
    with mod.banco() as db:
        past=(date.fromisoformat(today)-timedelta(days=31)).isoformat()
        db.execute('UPDATE mensal_ciclos SET inicio=?,fim=? WHERE loja_id=? AND id=?',(past,today,owner['loja_id'],new['ciclo']['id']))
    hist=a.get(path+'/assinantes/'+newid).json();assert len(hist['ciclos'])==2 and not hist['assinante']['ativo'] and hist['ciclos'][0]['status']=='pendente' and hist['ciclos'][0]['servicos'][0]['utilizados']==0
    assert len(a.get(path+'/assinantes/'+newid).json()['ciclos'])==2
    assert a.post(path+'/ciclos/'+hist['ciclos'][0]['id']+'/pagamento',json=paid,headers=hs[0]).status_code==200
    assert a.get(path+'/assinantes/'+newid).json()['assinante']['ativo']
    # Ledger is included in backups, and older backups remain restorable.
    import recursos,restaurar_backup
    with mod.banco() as db:tables={t:[dict(x) for x in db.execute('SELECT '+','.join(cols)+' FROM '+t)] for t,cols in recursos.TABLES.items()}
    payload={'formato':'barbersaas-backup','versao':1,'tabelas':tables};pathfile=Path(tmp)/'monthly.json';pathfile.write_text(json.dumps(payload),encoding='utf8')
    recovered=restaurar_backup.ler(pathfile);counts=restaurar_backup.restaurar(recovered,str(Path(tmp)/'restored.db'))
    assert counts['mensal_utilizacoes']==4 and counts['mensal_ciclos']==4
    with sqlite3.connect(Path(tmp)/'restored.db') as db:assert db.execute("SELECT COUNT(*) FROM mensal_ciclos WHERE status='pago'").fetchone()[0]==3
    import mensalistas
    old={t:r for t,r in tables.items() if t not in mensalistas.TABLES};pathfile.write_text(json.dumps({**payload,'tabelas':old}),encoding='utf8')
    restored=restaurar_backup.ler(pathfile);assert restored['mensal_ciclos']==[]
    restaurar_backup.restaurar(restored,str(Path(tmp)/'old.db'))
    print('OK assinaturas: pagamento manual/idempotente, consumo concorrente, limites, ciclos, agenda, caixa, isolamento, permissões e backup', 'PostgreSQL' if dsn else 'SQLite')
if schema:
    clean=os.environ['MONTHLY_TEST_DATABASE_URL']
    with psycopg.connect(clean) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')
