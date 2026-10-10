"""Promoções em SQLite descartável: nunca usa o banco de produção."""
import os, tempfile, importlib.util, json, secrets
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
dsn=os.environ.get('PROMO_TEST_DATABASE_URL');schema=None
if dsn:
    assert urlparse(dsn).hostname in ('localhost','127.0.0.1')
    import psycopg
    schema='promo_test_'+secrets.token_hex(8)
    with psycopg.connect(dsn) as db:db.execute('CREATE SCHEMA '+schema)
    clean_dsn=dsn;dsn+=('&' if '?' in dsn else '?')+'options=-csearch_path%3D'+schema
with tempfile.TemporaryDirectory() as tmp:
    os.environ.update(BARBER_DB_PATH=str(Path(tmp)/'promos.db'),BILLING_ENABLED='false',ADMIN_EMAILS='')
    os.environ.pop('RENDER',None)
    if dsn:os.environ['DATABASE_URL']=dsn
    else:os.environ.pop('DATABASE_URL',None)
    spec=importlib.util.spec_from_file_location('promos_app',ROOT/'app.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    a,b,guest=TestClient(mod.app),TestClient(mod.app),TestClient(mod.app)
    headers=[]
    for i,client in enumerate((a,b)):
        r=client.post('/api/cadastro',json={'nome':'Promo '+str(i),'slug':'promo-'+str(i),'email':f'promo{i}@example.com','senha':'SenhaTeste!12345','aceite_termos':True});assert r.status_code==201,r.text
        headers.append({'X-CSRF-Token':r.json()['csrf']})
        cfg=client.get('/api/configuracao').json();cfg.update(whatsapp='11900000000',barbeiros=[{'id':'prof','nome':'Carlos'},{'id':'outro','nome':'Bruno'}],servicos=[{'id':'corte','nome':'Corte','preco':40,'duracao':30}],dias=list(range(7)),periodos=[{'inicio':'08:00','fim':'20:00'}],intervalo=30)
        assert client.put('/api/configuracao',json=cfg,headers=headers[i]).status_code==200
    today=datetime.now(mod.BRASIL).date();day=today+timedelta(days=2)
    offer=dict(nome='Corte especial',desconto_tipo='fixo',valor=2990,servicos=['corte'],barbeiros=['prof'],inicio=today.isoformat(),fim=(today+timedelta(days=8)).isoformat(),dias=list(range(7)),hora_inicio='09:00',hora_fim='12:00',limite=1)
    path='/api/promocoes'
    assert guest.get(path).status_code==401
    assert a.post(path,json=offer).status_code==403
    assert a.post(path,json={**offer,'valor':4100},headers=headers[0]).status_code==422
    assert a.post(path,json={**offer,'servicos':['foreign']},headers=headers[0]).status_code==422
    r=a.post(path,json=offer,headers=headers[0]);assert r.status_code==201,r.text
    pid=r.json()['id']
    assert b.get(path).json()==[]
    assert b.put(path+'/'+pid,json=offer,headers=headers[1]).status_code==404
    assert b.patch(path+'/'+pid,json={'status':'pausada'},headers=headers[1]).status_code==404
    public='/api/publico/promo-0'
    assert guest.get(public+'/promocoes').json()[0]['servicos'][0]['total_centavos']==2990
    def book(hour='09:00',barber='prof',shop='promo-0',promotion=pid):
        return guest.post('/api/publico/'+shop+'/agendamentos',json=dict(cliente_nome='João Silva',cliente_telefone='11911111111',barbeiro_id=barber,servico_id='corte',data=day.isoformat(),horario=hour,promocao_id=promotion))
    assert book(barber='outro').status_code==422
    assert book(hour='08:30').status_code==422
    assert book(hour='12:00').status_code==422
    assert book(shop='promo-1').status_code==404
    with ThreadPoolExecutor(max_workers=2) as pool:rs=list(pool.map(book,['09:00','10:00']))
    assert sorted(r.status_code for r in rs)==[201,409],[(r.status_code,r.text) for r in rs]
    rid=next(r.json()['agendamento_id'] for r in rs if r.status_code==201)
    assert guest.get(public+'/promocoes').json()==[]
    row=next(r for r in a.get('/api/agendamentos').json() if r['id']==rid)
    assert row['preco']==29.9 and row['promocao']['desconto_centavos']==1010
    assert a.put(path+'/'+pid,json={**offer,'valor':2500},headers=headers[0]).status_code==200
    assert next(r for r in a.get('/api/agendamentos').json() if r['id']==rid)['preco']==29.9
    pay=path+'/atendimentos/'+str(rid)+'/pagamento'
    receipt={'valor_centavos':2990,'forma':'pix'}
    assert a.post(pay,json=receipt,headers=headers[0]).status_code==409
    assert a.patch('/api/agendamentos/'+str(rid),json={'status':'concluido'},headers=headers[0]).status_code==200
    summary='/api/produtos/resumo?inicio='+day.isoformat()+'&fim='+day.isoformat()
    assert a.get(summary).json()['servicos_centavos']==0
    assert a.post(pay,json={**receipt,'valor_centavos':1},headers=headers[0]).status_code==422
    assert b.post(pay,json=receipt,headers=headers[1]).status_code==404
    for _ in range(2):
        r=a.post(pay,json=receipt,headers=headers[0]);assert r.status_code==200,r.text
    assert a.get(summary).json()['servicos_centavos']==2990
    assert a.patch('/api/agendamentos/'+str(rid),json={'status':'cancelado'},headers=headers[0]).status_code==409
    report=a.get(path+'/relatorio').json();assert report['receita_centavos']==2990 and len(report['recebimentos'])==1
    assert b.get(path+'/relatorio').json()['receita_centavos']==0
    assert a.patch(path+'/'+pid,json={'status':'arquivada'},headers=headers[0]).status_code==200
    assert guest.get(public+'/promocoes').json()==[]
    assert a.post(path+'/'+pid+'/duplicar',headers=headers[0]).json()['status']=='pausada'
    assert guest.get('/promocoes.js?asset=app.py').text.startswith('/*')
    # Datas, dias, preços e estados são conferidos no servidor.
    assert a.post(path,json={**offer,'imagem_url':'https://example.com:invalid/x'},headers=headers[0]).status_code==422
    for patch in ({'inicio':(today+timedelta(days=3)).isoformat()},{'inicio':(today-timedelta(days=3)).isoformat(),'fim':(today-timedelta(days=1)).isoformat()},{'status':'pausada'}):
        r=a.post(path,json={**offer,**patch},headers=headers[0]);assert r.status_code==201,r.text
        blocked=r.json()['id']
        assert blocked not in [x['id'] for x in guest.get(public+'/promocoes').json()]
        assert book(hour='11:00',promotion=blocked).status_code==409
    r=a.post(path,json={**offer,'dias':[(day.weekday()+1)%7],'limite':None},headers=headers[0]);assert r.status_code==201
    assert book(hour='11:00',promotion=r.json()['id']).status_code==422
    # Cancelamento libera a vaga, sem apagar o histórico.
    r=a.post(path,json={**offer,'desconto_tipo':'percentual','valor':20},headers=headers[0]);pid2=r.json()['id']
    r=book(hour='11:00',promotion=pid2);assert r.status_code==201,r.text
    old=r.json()['agendamento_id'];assert r.json()['preco']==32
    assert a.patch('/api/agendamentos/'+str(old),json={'status':'cancelado'},headers=headers[0]).status_code==200
    r=book(hour='11:30',promotion=pid2);assert r.status_code==201,r.text
    assert a.patch('/api/agendamentos/'+str(old),json={'status':'agendado'},headers=headers[0]).status_code==409
    # Permissão explícita da equipe; receitas continuam restritas ao dono.
    with mod.banco() as db:
        owner=dict(db.execute('SELECT * FROM usuarios WHERE email=?',('promo0@example.com',)).fetchone())
        db.execute('INSERT INTO funcionarios(id,loja_id,barbeiro_id,email,senha,ativo) VALUES(?,?,?,?,?,1)',('promo-staff',owner['loja_id'],'prof','promo-staff@example.com',owner['senha']))
    staff=TestClient(mod.app);r=staff.post('/api/login',json={'email':'promo-staff@example.com','senha':'SenhaTeste!12345'});sh={'X-CSRF-Token':r.json()['csrf']}
    assert staff.get(path).status_code==403
    assert a.put(path+'/permissoes/promo-staff',json={'gerenciar':True},headers=headers[0]).status_code==200
    assert staff.get(path).status_code==200 and staff.get(path+'/relatorio').status_code==403
    assert staff.post(path,json={**offer,'nome':'Oferta da equipe'},headers=sh).status_code==201
    assert b.put(path+'/permissoes/promo-staff',json={'gerenciar':True},headers=headers[1]).status_code==404
    # O envio reutiliza compressão e armazenamento, sem expor segredos ao cliente.
    from unittest.mock import patch
    from PIL import Image
    import io
    buf=io.BytesIO();Image.new('RGB',(120,80),'white').save(buf,format='PNG')
    assert guest.post(path+'/imagem',content=buf.getvalue()).status_code==401
    with patch('imagens.pronto',return_value=True),patch('imagens.enviar',return_value='https://res.cloudinary.com/test/image/upload/promo.webp') as upload:
        assert staff.post(path+'/imagem',content=buf.getvalue(),headers=sh).status_code==200
        assert upload.call_args.args[1]==owner['loja_id']
        assert a.post(path+'/imagem',content=b'invalid-image',headers=headers[0]).status_code==422
    # Serviço incluído em assinatura consome utilização, sem receita avulsa.
    plan={'nome':'Mensal cortes','valor_centavos':8990,'servicos':[{'servico_id':'corte','quantidade':4}],'ciclo_unidade':'meses','ciclo_quantidade':1,'status':'ativo'}
    r=a.post('/api/mensalistas/planos',json=plan,headers=headers[0]);assert r.status_code==201,r.text
    r=a.post('/api/mensalistas/assinantes',json={'cliente_telefone':'11911111111','plano_id':r.json()['id'],'inicio':today.isoformat(),'vencimento':today.isoformat(),'pagamento':'pix'},headers=headers[0]);assert r.status_code==201,r.text
    cid=r.json()['ciclo']['id']
    assert a.post('/api/mensalistas/ciclos/'+cid+'/pagamento',json={'confirmado':True,'data_pagamento':today.isoformat(),'pagamento':'pix'},headers=headers[0]).status_code==200
    current=next(x for x in a.get('/api/agendamentos').json() if x['promocao']['promocao_id']==pid2 and x['status']=='agendado')
    assert a.patch('/api/agendamentos/'+str(current['id']),json={'status':'concluido','assinatura':True},headers=headers[0]).status_code==200
    assert a.post(path+'/atendimentos/'+str(current['id'])+'/pagamento',json={'forma':'pix','valor_centavos':3200},headers=headers[0]).status_code==409
    assert a.get(summary).json()['servicos_centavos']==2990
    # Backup novo inclui snapshots/recebimentos; cópia antiga continua legível.
    import recursos,restaurar_backup,promocoes
    with mod.banco() as db:tables={t:[dict(x) for x in db.execute('SELECT '+','.join(cols)+' FROM '+t)] for t,cols in recursos.TABLES.items()}
    payload={'formato':'barbersaas-backup','versao':1,'tabelas':tables};file=Path(tmp)/'backup.json';file.write_text(json.dumps(payload),encoding='utf8')
    restored=restaurar_backup.ler(file);assert len(restored['promocao_pagamentos'])==1
    counts=restaurar_backup.restaurar(restored,str(Path(tmp)/'restored.db'));assert counts['promocao_reservas']==3
    payload['tabelas']={t:rows for t,rows in tables.items() if t not in promocoes.TABLES};file.write_text(json.dumps(payload),encoding='utf8')
    assert restaurar_backup.ler(file)['promocoes']==[]
print('Promoções: fluxo, concorrência, preço histórico, caixa e isolamento OK')
if schema:
    with psycopg.connect(clean_dsn) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')
