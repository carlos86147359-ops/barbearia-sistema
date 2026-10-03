import os,tempfile,importlib.util,secrets,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
with tempfile.TemporaryDirectory() as tmp:
 os.environ['BARBER_DB_PATH']=str(Path(tmp)/'products.db')
 for key in ('DATABASE_URL','RENDER','ADMIN_EMAILS','BILLING_ENABLED'):os.environ.pop(key,None)
 spec=importlib.util.spec_from_file_location('products_app',Path(__file__).parents[1]/'app.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 a,b,guest=TestClient(mod.app),TestClient(mod.app),TestClient(mod.app)
 headers=[]
 for i,c in enumerate((a,b)):
  r=c.post('/api/cadastro',json={'nome':'Loja '+str(i),'slug':'prod-loja-'+str(i),'email':f'dono{i}@example.com','senha':'SenhaTeste!12345','aceite_termos':True});assert r.status_code==201,r.text
  headers.append({'X-CSRF-Token':r.json()['csrf']})
 assert guest.get('/api/produtos/catalogo').status_code==401
 product={'nome':'Pomada','categoria':'Cabelo','custo_centavos':1200,'preco_centavos':3000,'variantes':[{'atributos':{'Tamanho':'100g'},'quantidade':3,'estoque_minimo':1}]}
 r=a.post('/api/produtos/catalogo',json=product,headers=headers[0]);assert r.status_code==201,r.text
 catalog=a.get('/api/produtos/catalogo').json();vid=catalog[0]['variantes'][0]['id'];pid=r.json()['id']
 assert b.get('/api/produtos/catalogo').json()==[]
 sale={'itens':[{'variante_id':vid,'quantidade':2}],'pagamento':'pix','desconto_centavos':500,'idempotencia':secrets.token_hex(20),'total_esperado_centavos':5500}
 r=a.post('/api/produtos/vendas',json=sale,headers=headers[0]);assert r.status_code==201,r.text
 sold=r.json();assert sold['total_centavos']==5500 and sold['custo_centavos']==2400
 assert a.post('/api/produtos/vendas',json=sale,headers=headers[0]).json()['id']==sold['id']
 assert b.post('/api/produtos/vendas',json={**sale,'idempotencia':secrets.token_hex(20)},headers=headers[1]).status_code==404
 assert a.get('/api/produtos/catalogo').json()[0]['variantes'][0]['quantidade']==1
 product['variantes'][0].update(id=vid,quantidade=1);product.update(custo_centavos=1800,preco_centavos=3500)
 assert a.put('/api/produtos/catalogo/'+pid,json=product,headers=headers[0]).status_code==200
 history=a.get('/api/produtos/vendas').json();assert history[0]['custo_centavos']==2400 and history[0]['itens'][0]['preco_unitario_centavos']==3000
 stale={**sale,'idempotencia':secrets.token_hex(20),'itens':[{'variante_id':vid,'quantidade':1}]}
 assert a.post('/api/produtos/vendas',json=stale,headers=headers[0]).status_code==409
 def buy(_):return a.post('/api/produtos/vendas',json={'itens':[{'variante_id':vid,'quantidade':1}],'pagamento':'dinheiro','idempotencia':secrets.token_hex(20)},headers=headers[0])
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(buy,range(2)))
 assert sorted(r.status_code for r in results)==[201,409],[(r.status_code,r.text) for r in results]
 assert a.get('/api/produtos/catalogo').json()[0]['variantes'][0]['quantidade']==0
 cancel={'motivo':'Venda registrada incorretamente','devolver_estoque':True}
 assert a.post('/api/produtos/vendas/'+sold['id']+'/cancelar',json=cancel,headers=headers[0]).status_code==200
 assert a.post('/api/produtos/vendas/'+sold['id']+'/cancelar',json=cancel,headers=headers[0]).status_code==200
 assert a.get('/api/produtos/catalogo').json()[0]['variantes'][0]['quantidade']==2
 assert b.post('/api/produtos/vendas/'+sold['id']+'/cancelar',json=cancel,headers=headers[1]).status_code==404
 assert a.get('/api/produtos/resumo').json()['total_centavos']==3500
 assert a.post('/api/produtos/estoque',json={'variante_id':vid,'tipo':'perda','quantidade':-3,'motivo':'Produto danificado'},headers=headers[0]).status_code==409
 assert a.get('/api/produtos/catalogo').json()[0]['variantes'][0]['quantidade']==2
 # Staff permissions are denied by default and cost fields never leak.
 with mod.banco() as db:
  owner=dict(db.execute('SELECT * FROM usuarios WHERE email=?',('dono0@example.com',)).fetchone())
  cfg=mod.config_da_loja(db,owner['loja_id']);barber='prof-1';cfg['barbeiros']=[{'id':barber,'nome':'Carlos','comissao_pct':0}];db.execute('UPDATE lojas SET configuracao=? WHERE id=?',(json.dumps(cfg),owner['loja_id']))
  db.execute('INSERT INTO funcionarios (id,loja_id,barbeiro_id,email,senha,ativo) VALUES (?,?,?,?,?,1)',('staff-prod',owner['loja_id'],barber,'staff@example.com',owner['senha']))
 staff=TestClient(mod.app);login=staff.post('/api/login',json={'email':'staff@example.com','senha':'SenhaTeste!12345'});assert login.status_code==200,login.text
 hs={'X-CSRF-Token':login.json()['csrf']}
 assert staff.get('/api/produtos/catalogo').status_code==403
 perms={'acessar_pdv':True,'registrar_venda':True,'ver_estoque':True}
 assert a.put('/api/produtos/permissoes/staff-prod',json={'permissoes':perms},headers=headers[0]).status_code==200
 assert 'custo_centavos' not in staff.get('/api/produtos/catalogo').text
 own=staff.post('/api/produtos/vendas',json={'itens':[{'variante_id':vid,'quantidade':1}],'pagamento':'pix','idempotencia':secrets.token_hex(20)},headers=hs);assert own.status_code==201,own.text
 assert 'custo' not in own.text and 'lucro' not in own.text
 assert len(staff.get('/api/produtos/vendas').json())==1
 assert 'custo' not in staff.get('/api/produtos/resumo').text
 assert staff.post('/api/produtos/vendas/'+own.json()['id']+'/cancelar',json=cancel,headers=hs).status_code==403
 assert staff.get('/api/produtos/permissoes').status_code==403

 assert a.post('/api/produtos/estoque',json={'variante_id':vid,'tipo':'reposicao','quantidade':2,'motivo':'Novo lote','custo_reposicao_centavos':2000},headers=headers[0]).status_code==200
 assert a.get('/api/produtos/catalogo').json()[0]['variantes'][0]['custo_centavos']==2000
 assert b.put('/api/produtos/catalogo/'+pid,json=product,headers=headers[1]).status_code==404
 assert a.post('/api/produtos/vendas',json=sale).status_code==403
 assert staff.post('/api/produtos/vendas',json={**sale,'idempotencia':secrets.token_hex(20)},headers=hs).status_code==403
 assert b.put('/api/produtos/permissoes/staff-prod',json={'permissoes':perms},headers=headers[1]).status_code==404
 assert a.put('/api/produtos/permissoes/staff-prod',json={'permissoes':{'acessar_pdv':True,'ver_lucro':True}},headers=headers[0]).status_code==422
 assert 'lucro' not in staff.get('/api/produtos/vendas').text
 assert b.get('/api/produtos/movimentacoes').json()==[]
 # Backup round trip preserves immutable snapshots, audit and all permissions.
 import recursos,restaurar_backup
 with mod.banco() as db:tables={t:[dict(x) for x in db.execute('SELECT '+','.join(cols)+' FROM '+t)] for t,cols in recursos.TABLES.items()}
 payload={'formato':'barbersaas-backup','versao':1,'tabelas':tables};path=Path(tmp)/'backup.json';path.write_text(json.dumps(payload),encoding='utf8')
 recovered=restaurar_backup.ler(path);counts=restaurar_backup.restaurar(recovered,str(Path(tmp)/'restored.db'));assert counts['vendas_produtos']==3
 import sqlite3
 from contextlib import closing
 with closing(sqlite3.connect(Path(tmp)/'restored.db')) as db:assert db.execute('SELECT custo_centavos FROM vendas_produtos WHERE id=?',(sold['id'],)).fetchone()[0]==2400
 for t in list(tables):
  if t in recursos.PRODUCT_TABLES:del tables[t]
 path.write_text(json.dumps(payload),encoding='utf8');old=restaurar_backup.ler(path);assert old['produtos']==[]
 restaurar_backup.restaurar(old,str(Path(tmp)/'old.db'))
 print('Produtos: estoque concorrente, snapshots, cancelamento, isolamento, permissões e backups OK')
