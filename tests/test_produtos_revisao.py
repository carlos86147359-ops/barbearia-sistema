"""Regressões reais: edição concorrente, repetição de estoque e reconciliação financeira."""
import os,tempfile,importlib.util,secrets,copy
from pathlib import Path
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
 os.environ['BARBER_DB_PATH']=str(Path(tmp)/'review.db')
 for key in ('DATABASE_URL','RENDER','ADMIN_EMAILS','BILLING_ENABLED'):os.environ.pop(key,None)
 spec=importlib.util.spec_from_file_location('review_app',Path(__file__).parents[1]/'app.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 client=TestClient(mod.app)
 r=client.post('/api/cadastro',json={'nome':'Loja de teste','slug':'revisao-caixa','email':'revisao@example.com','senha':'SenhaTeste!12345','aceite_termos':True});assert r.status_code==201,r.text
 headers={'X-CSRF-Token':r.json()['csrf']}
 def post(url,data,code=201):
  r=client.post('/api/produtos/'+url,json=data,headers=headers);assert r.status_code==code,r.text;return r.json()
 def catalog():return client.get('/api/produtos/catalogo').json()
 product={'nome':'Pomada','categoria':'Cabelo','custo_centavos':1200,'preco_centavos':3000,'variantes':[{'atributos':{},'quantidade':5}]}
 pid=post('catalogo',product)['id'];vid=catalog()[0]['variantes'][0]['id']
 draft=copy.deepcopy(product);draft['variantes'][0].update(id=vid,quantidade_anterior=5)
 sale=post('vendas',{'itens':[{'variante_id':vid,'quantidade':2}],'pagamento':'pix','idempotencia':secrets.token_hex(20)})
 assert catalog()[0]['variantes'][0]['quantidade']==3
 # A price edit from a stale form preserves the two units already sold.
 draft.update(nome='Pomada renovada',preco_centavos=3500)
 r=client.put('/api/produtos/catalogo/'+pid,json=draft,headers=headers);assert r.status_code==200,r.text
 assert catalog()[0]['variantes'][0]['quantidade']==3
 # An intentional stock change from that same stale form is refused atomically.
 stale=copy.deepcopy(draft);stale['nome']='Não deve ser salvo';stale['motivo']='Inventário';stale['variantes'][0]['quantidade']=8
 r=client.put('/api/produtos/catalogo/'+pid,json=stale,headers=headers);assert r.status_code==409,r.text
 assert catalog()[0]['nome']=='Pomada renovada' and catalog()[0]['variantes'][0]['quantidade']==3
 stale['variantes'][0]['quantidade_anterior']=3
 r=client.put('/api/produtos/catalogo/'+pid,json=stale,headers=headers);assert r.status_code==200,r.text
 assert catalog()[0]['variantes'][0]['quantidade']==8
 movement={'variante_id':vid,'tipo':'reposicao','quantidade':2,'motivo':'Novo lote','custo_reposicao_centavos':1800,'idempotencia':secrets.token_hex(20)}
 post('estoque',movement,200);post('estoque',movement,200)
 assert catalog()[0]['variantes'][0]['quantidade']==10
 altered={**movement,'quantidade':3};post('estoque',altered,409)
 assert catalog()[0]['variantes'][0]['quantidade']==10
 # Retrying an older stock request must not undo a newer unit cost.
 post('estoque',{**movement,'quantidade':1,'custo_reposicao_centavos':2000,'idempotencia':secrets.token_hex(20)},200)
 post('estoque',movement,200)
 assert catalog()[0]['variantes'][0]['quantidade']==11 and catalog()[0]['variantes'][0]['custo_centavos']==2000
 losses={'variante_id':vid,'tipo':'perda','quantidade':-1,'motivo':'Embalagem danificada','idempotencia':secrets.token_hex(20)}
 post('estoque',losses,200);post('estoque',losses,200)
 assert catalog()[0]['variantes'][0]['quantidade']==10
 summary=client.get('/api/produtos/resumo').json()
 assert (summary['total_centavos'],summary['custo_centavos'],summary['lucro_bruto_centavos'],summary['itens_vendidos'])==(6000,2400,3600,2)
 canceled=post('vendas/'+sale['id']+'/cancelar',{'motivo':'Registro incorreto','devolver_estoque':True},200)
 assert canceled['lucro_bruto_centavos']==0 and all(i['lucro_bruto_centavos']==0 for i in canceled['itens'])
 assert catalog()[0]['variantes'][0]['quantidade']==12
 post('vendas/'+sale['id']+'/cancelar',{'motivo':'Registro incorreto','devolver_estoque':True},200)
 assert catalog()[0]['variantes'][0]['quantidade']==12
 # Discount cents reconcile exactly across products, including a free item.
 vids=[]
 for name,price,cost in [('Camisa',1999,700),('Minoxidil',3491,1600),('Brinde',0,100)]:
  id=post('catalogo',{'nome':name,'custo_centavos':cost,'preco_centavos':price,'variantes':[{'atributos':{},'quantidade':4}]})['id']
  vids.append(next(p for p in catalog() if p['id']==id)['variantes'][0]['id'])
 mixed=post('vendas',{'itens':[{'variante_id':v,'quantidade':1} for v in vids],'pagamento':'credito','desconto_centavos':137,'total_esperado_centavos':5353,'idempotencia':secrets.token_hex(20)})
 assert sum(i['subtotal_centavos'] for i in mixed['itens'])==mixed['total_centavos']==5353
 assert sum(i['desconto_centavos'] for i in mixed['itens'])==137
 assert sum(i['lucro_bruto_centavos'] for i in mixed['itens'])==mixed['lucro_bruto_centavos']==2953
 # A completed service enters only the service origin, not product revenue.
 with mod.banco() as db:
  loja=db.execute('SELECT loja_id FROM usuarios WHERE email=?',('revisao@example.com',)).fetchone()['loja_id']
  day=mod.datetime.now(mod.BRASIL).date().isoformat()
  db.execute('INSERT INTO agendamentos(cliente_nome,cliente_telefone,barbeiro_nome,servico_nome,data_hora,preco,status,inicio,loja_id) VALUES(?,?,?,?,?,?,?,?,?)',('Teste','61999990000','Teste','Corte',day+' às 10:00',35.90,'concluido',day+'T10:00',loja))
 summary=client.get('/api/produtos/resumo').json()
 assert (summary['vendas'],summary['total_centavos'],summary['custo_centavos'],summary['lucro_bruto_centavos'],summary['servicos_centavos'],summary['faturamento_total_centavos'])==(1,5353,2400,2953,3590,8943)
 post('vendas/'+mixed['id']+'/cancelar',{'motivo':'Sem devolução','devolver_estoque':False},200)
 summary=client.get('/api/produtos/resumo').json()
 assert summary['total_centavos']==summary['lucro_bruto_centavos']==0 and summary['faturamento_total_centavos']==3590
 assert all(next(v for p in catalog() for v in p['variantes'] if v['id']==id)['quantidade']==3 for id in vids)
 print('Revisão: edição concorrente, estoque idempotente, descontos, cancelamentos e totais por origem OK')
