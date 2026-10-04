"""Vendas presenciais: centavos inteiros, estoque transacional e isolamento por loja."""
import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict

PERMISSIONS=('acessar_pdv','registrar_venda','ver_estoque','ver_custo','ver_lucro','alterar_estoque','cancelar_venda','aplicar_desconto')
TABLES={
 'produtos':['id','loja_id','nome','categoria','descricao','sku','codigo_barras','imagem_url','custo_centavos','preco_centavos','ativo','criado_em'],
 'variantes_produto':['id','loja_id','produto_id','atributos','sku','codigo_barras','custo_centavos','preco_centavos','quantidade','estoque_minimo','ativo'],
 'permissoes_caixa':['id','loja_id','funcionario_id','permissoes','atualizado_por','atualizado_em'],
 'vendas_produtos':['id','loja_id','vendedor_id','vendedor_nome','criado_em','pagamento','bruto_centavos','desconto_centavos','total_centavos','custo_centavos','status','idempotencia','pedido_hash','cancelado_por','cancelado_em','motivo_cancelamento','devolver_estoque'],
 'itens_venda':['id','loja_id','venda_id','produto_id','variante_id','nome_snapshot','variante_snapshot','quantidade','preco_unitario_centavos','custo_unitario_centavos','desconto_centavos','subtotal_centavos'],
 'movimentacoes_estoque':['id','loja_id','produto_id','variante_id','tipo','quantidade','anterior','posterior','motivo','usuario_id','usuario_nome','criado_em','venda_id','custo_reposicao_centavos'],
}
DDL={
 'produtos':'''id TEXT PRIMARY KEY,loja_id TEXT NOT NULL REFERENCES lojas(id),nome TEXT NOT NULL,categoria TEXT NOT NULL,descricao TEXT NOT NULL,sku TEXT NOT NULL,codigo_barras TEXT NOT NULL,imagem_url TEXT NOT NULL,custo_centavos BIGINT NOT NULL CHECK(custo_centavos>=0),preco_centavos BIGINT NOT NULL CHECK(preco_centavos>=0),ativo INTEGER NOT NULL CHECK(ativo IN (0,1)),criado_em TEXT NOT NULL,UNIQUE(loja_id,id)''',
 'variantes_produto':'''id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,produto_id TEXT NOT NULL,atributos TEXT NOT NULL,sku TEXT NOT NULL,codigo_barras TEXT NOT NULL,custo_centavos BIGINT CHECK(custo_centavos>=0),preco_centavos BIGINT CHECK(preco_centavos>=0),quantidade INTEGER NOT NULL CHECK(quantidade>=0),estoque_minimo INTEGER NOT NULL CHECK(estoque_minimo>=0),ativo INTEGER NOT NULL CHECK(ativo IN (0,1)),UNIQUE(loja_id,id),UNIQUE(loja_id,produto_id,atributos),FOREIGN KEY(loja_id,produto_id) REFERENCES produtos(loja_id,id)''',
 'permissoes_caixa':'''id TEXT PRIMARY KEY,loja_id TEXT NOT NULL REFERENCES lojas(id),funcionario_id TEXT NOT NULL REFERENCES funcionarios(id),permissoes TEXT NOT NULL,atualizado_por TEXT NOT NULL,atualizado_em TEXT NOT NULL,UNIQUE(loja_id,funcionario_id)''',
 'vendas_produtos':'''id TEXT PRIMARY KEY,loja_id TEXT NOT NULL REFERENCES lojas(id),vendedor_id TEXT NOT NULL,vendedor_nome TEXT NOT NULL,criado_em TEXT NOT NULL,pagamento TEXT NOT NULL,bruto_centavos BIGINT NOT NULL CHECK(bruto_centavos>=0),desconto_centavos BIGINT NOT NULL CHECK(desconto_centavos>=0 AND desconto_centavos<=bruto_centavos),total_centavos BIGINT NOT NULL CHECK(total_centavos=bruto_centavos-desconto_centavos),custo_centavos BIGINT NOT NULL CHECK(custo_centavos>=0),status TEXT NOT NULL CHECK(status IN ('confirmada','cancelada')),idempotencia TEXT NOT NULL,pedido_hash TEXT NOT NULL,cancelado_por TEXT,cancelado_em TEXT,motivo_cancelamento TEXT,devolver_estoque INTEGER NOT NULL DEFAULT 0 CHECK(devolver_estoque IN (0,1)),UNIQUE(loja_id,id),UNIQUE(loja_id,idempotencia)''',
 'itens_venda':'''id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,venda_id TEXT NOT NULL,produto_id TEXT NOT NULL,variante_id TEXT NOT NULL,nome_snapshot TEXT NOT NULL,variante_snapshot TEXT NOT NULL,quantidade INTEGER NOT NULL CHECK(quantidade>0),preco_unitario_centavos BIGINT NOT NULL CHECK(preco_unitario_centavos>=0),custo_unitario_centavos BIGINT NOT NULL CHECK(custo_unitario_centavos>=0),desconto_centavos BIGINT NOT NULL CHECK(desconto_centavos>=0),subtotal_centavos BIGINT NOT NULL CHECK(subtotal_centavos=quantidade*preco_unitario_centavos-desconto_centavos AND subtotal_centavos>=0),FOREIGN KEY(loja_id,venda_id) REFERENCES vendas_produtos(loja_id,id),FOREIGN KEY(loja_id,produto_id) REFERENCES produtos(loja_id,id),FOREIGN KEY(loja_id,variante_id) REFERENCES variantes_produto(loja_id,id)''',
 'movimentacoes_estoque':'''id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,produto_id TEXT NOT NULL,variante_id TEXT NOT NULL,tipo TEXT NOT NULL,quantidade INTEGER NOT NULL,anterior INTEGER NOT NULL CHECK(anterior>=0),posterior INTEGER NOT NULL CHECK(posterior>=0 AND posterior=anterior+quantidade),motivo TEXT NOT NULL,usuario_id TEXT NOT NULL,usuario_nome TEXT NOT NULL,criado_em TEXT NOT NULL,venda_id TEXT,custo_reposicao_centavos BIGINT CHECK(custo_reposicao_centavos>=0),FOREIGN KEY(loja_id,produto_id) REFERENCES produtos(loja_id,id),FOREIGN KEY(loja_id,variante_id) REFERENCES variantes_produto(loja_id,id),FOREIGN KEY(loja_id,venda_id) REFERENCES vendas_produtos(loja_id,id)''',
}
INTEGER_COLUMNS={'custo_centavos','preco_centavos','ativo','quantidade','estoque_minimo','bruto_centavos','desconto_centavos','total_centavos','devolver_estoque','preco_unitario_centavos','custo_unitario_centavos','subtotal_centavos','anterior','posterior','custo_reposicao_centavos'}
INDEXES=[
 "CREATE UNIQUE INDEX IF NOT EXISTS produto_sku_loja ON produtos(loja_id,sku) WHERE sku<>''",
 "CREATE UNIQUE INDEX IF NOT EXISTS variante_sku_loja ON variantes_produto(loja_id,sku) WHERE sku<>''",
 'CREATE INDEX IF NOT EXISTS produto_loja_nome ON produtos(loja_id,nome)',
 'CREATE INDEX IF NOT EXISTS venda_loja_data ON vendas_produtos(loja_id,criado_em)',
 'CREATE INDEX IF NOT EXISTS venda_vendedor ON vendas_produtos(loja_id,vendedor_id,criado_em)',
 'CREATE INDEX IF NOT EXISTS movimento_loja_data ON movimentacoes_estoque(loja_id,criado_em)',
 'CREATE INDEX IF NOT EXISTS itens_venda_loja ON itens_venda(loja_id,venda_id)',
]
def criar_tabelas(db):
    for name,ddl in DDL.items(): db.execute('CREATE TABLE IF NOT EXISTS '+name+' ('+ddl+')')
    for sql in INDEXES: db.execute(sql)

class Entrada(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Variante(Entrada):
    id: str | None=Field(default=None,max_length=64)
    atributos: dict[str,str]=Field(default_factory=dict,max_length=8)
    sku: str=Field(default='',max_length=80)
    codigo_barras: str=Field(default='',max_length=80)
    custo_centavos: int | None=Field(default=None,ge=0,le=100_000_000,strict=True)
    preco_centavos: int | None=Field(default=None,ge=0,le=100_000_000,strict=True)
    quantidade: int=Field(default=0,ge=0,le=1_000_000,strict=True)
    quantidade_anterior: int | None=Field(default=None,ge=0,le=1_000_000,strict=True)
    estoque_minimo: int=Field(default=0,ge=0,le=1_000_000,strict=True)
    ativo: bool=True
class Produto(Entrada):
    nome: str=Field(min_length=2,max_length=120)
    categoria: str=Field(default='',max_length=80)
    descricao: str=Field(default='',max_length=1000)
    sku: str=Field(default='',max_length=80)
    codigo_barras: str=Field(default='',max_length=80)
    imagem_url: str=Field(default='',max_length=1000)
    custo_centavos: int=Field(ge=0,le=100_000_000,strict=True)
    preco_centavos: int=Field(ge=0,le=100_000_000,strict=True)
    ativo: bool=True
    motivo: str=Field(default='',max_length=250)
    variantes: list[Variante]=Field(min_length=1,max_length=100)
class Item(Entrada):
    variante_id: str=Field(min_length=1,max_length=64)
    quantidade: int=Field(ge=1,le=1_000_000,strict=True)
class Venda(Entrada):
    itens: list[Item]=Field(min_length=1,max_length=100)
    pagamento: str=Field(pattern=r'^(dinheiro|pix|debito|credito|outro)$')
    desconto_centavos: int=Field(default=0,ge=0,le=10_000_000_000,strict=True)
    idempotencia: str=Field(min_length=20,max_length=100)
    total_esperado_centavos: int | None=Field(default=None,ge=0,strict=True)
class Movimento(Entrada):
    variante_id: str=Field(min_length=1,max_length=64)
    tipo: str=Field(pattern=r'^(reposicao|perda|devolucao|ajuste)$')
    quantidade: int=Field(ge=-1_000_000,le=1_000_000,strict=True)
    motivo: str=Field(min_length=2,max_length=250)
    custo_reposicao_centavos: int | None=Field(default=None,ge=0,le=100_000_000,strict=True)
    idempotencia: str | None=Field(default=None,min_length=20,max_length=100)
class Cancelamento(Entrada):
    motivo: str=Field(min_length=2,max_length=250)
    devolver_estoque: bool=True
class Permissoes(Entrada):
    permissoes: dict[str,bool]

def instalar(app,c):
    banco=c['banco'];br=c['BRASIL']
    def now():return datetime.now(br).isoformat(timespec='seconds')
    def ident():return secrets.token_hex(16)
    def lock(db,tenant):
        if c['DATABASE_URL']:db.execute('SELECT pg_advisory_xact_lock(?)',(int.from_bytes(hashlib.sha256(('produtos:'+tenant).encode()).digest()[:8],'big',signed=True),))
        else:db.execute('BEGIN IMMEDIATE')
    with banco() as db:
        if c['DATABASE_URL']:db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        criar_tabelas(db)
    def permissions(db,user):
        if user['papel']=='dono':return dict.fromkeys(PERMISSIONS,True)
        row=db.execute('SELECT permissoes FROM permissoes_caixa WHERE loja_id=? AND funcionario_id=?',(user['loja_id'],user['id'])).fetchone()
        data=json.loads(row['permissoes']) if row else {}
        return {k:bool(data.get(k,False)) for k in PERMISSIONS}
    def auth(db,request,permission='acessar_pdv',change=False,owner=False):
        user=c['usuario'](request,db,change);p=permissions(db,user)
        if (owner and user['papel']!='dono') or not p['acessar_pdv'] or not p.get(permission,False):raise HTTPException(403,'Você não tem permissão para esta ação em Produtos e Caixa.')
        return user,p
    def seller(db,user):
        cfg=c['config_da_loja'](db,user['loja_id'])
        return next((b['nome'] for b in cfg['barbeiros'] if b['id']==user['barbeiro_id']),user['email']) if user['papel']=='barbeiro' else user['email']
    def insert(db,table,data):
        cols=list(data);db.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(data.values()))
    def variant(db,tenant,vid):
        row=db.execute('SELECT v.*,p.nome,p.custo_centavos AS custo_padrao,p.preco_centavos AS preco_padrao,p.ativo AS produto_ativo FROM variantes_produto v JOIN produtos p ON p.loja_id=v.loja_id AND p.id=v.produto_id WHERE v.loja_id=? AND v.id=?',(tenant,vid)).fetchone()
        if not row:raise HTTPException(404,'Produto ou variante não encontrado.')
        return dict(row)
    def movement(db,user,v,delta,kind,reason,sale=None,cost=None,mid=None):
        after=v['quantidade']+delta
        if not 0<=after<=1_000_000:raise HTTPException(409,'Estoque insuficiente ou quantidade acima do limite.')
        db.execute('UPDATE variantes_produto SET quantidade=? WHERE loja_id=? AND id=?',(after,user['loja_id'],v['id']))
        insert(db,'movimentacoes_estoque',dict(id=mid or ident(),loja_id=user['loja_id'],produto_id=v['produto_id'],variante_id=v['id'],tipo=kind,quantidade=delta,anterior=v['quantidade'],posterior=after,motivo=reason,usuario_id=user['id'],usuario_nome=seller(db,user),criado_em=now(),venda_id=sale,custo_reposicao_centavos=cost))
    def sale_view(db,user,p,row):
        result=dict(row);items=[dict(r) for r in db.execute('SELECT * FROM itens_venda WHERE loja_id=? AND venda_id=?',(user['loja_id'],result['id']))]
        result.pop('pedido_hash',None);result.pop('idempotencia',None)
        if not p['ver_custo']:result.pop('custo_centavos',None)
        if p['ver_lucro']:result['lucro_bruto_centavos']=row['total_centavos']-row['custo_centavos'] if row['status']=='confirmada' else 0
        for item in items:
            if p['ver_lucro']:item['lucro_bruto_centavos']=item['subtotal_centavos']-item['custo_unitario_centavos']*item['quantidade'] if row['status']=='confirmada' else 0
            if not p['ver_custo']:item.pop('custo_unitario_centavos',None)
            item['variante_snapshot']=json.loads(item['variante_snapshot'])
        result['itens']=items;return result

    @app.get('/api/produtos/acesso')
    def acesso(request:Request):
        with banco() as db:
            u=c['usuario'](request,db);p=permissions(db,u)
            cfg=c['config_da_loja'](db,u['loja_id'])
            return {'papel':u['papel'],'usuario_id':u['id'],'permissoes':p,'cor_principal':cfg.get('cor_principal','#dfa94d'),'barbearia':cfg['nome']}

    @app.get('/api/produtos/permissoes')
    def lista_permissoes(request:Request):
        with banco() as db:
            u=c['dono'](request,db);cfg=c['config_da_loja'](db,u['loja_id']);names={b['id']:b['nome'] for b in cfg['barbeiros']}
            return [dict(id=r['id'],nome=names.get(r['barbeiro_id'],r['email']),email=r['email'],permissoes=permissions(db,dict(r,papel='barbeiro'))) for r in db.execute('SELECT * FROM funcionarios WHERE loja_id=? AND ativo=1',(u['loja_id'],)) if r['barbeiro_id'] in names]

    @app.put('/api/produtos/permissoes/{uid}')
    def autorizar(uid:str,data:Permissoes,request:Request):
        if set(data.permissoes)-set(PERMISSIONS):raise HTTPException(422,'Permissão não reconhecida.')
        p=dict.fromkeys(PERMISSIONS,False);p.update(data.permissoes)
        if p['ver_lucro'] and not p['ver_custo']:raise HTTPException(422,'Visualizar lucro também requer visualizar custo.')
        if any(v for k,v in p.items() if k!='acessar_pdv') and not p['acessar_pdv']:raise HTTPException(422,'Ative o acesso ao módulo antes de conceder outras permissões.')
        with banco() as db:
            u=c['dono'](request,db,True);lock(db,u['loja_id']);u=c['dono'](request,db,True)
            if not db.execute('SELECT id FROM funcionarios WHERE loja_id=? AND id=? AND ativo=1',(u['loja_id'],uid)).fetchone():raise HTTPException(404,'Profissional não encontrado.')
            db.execute('INSERT INTO permissoes_caixa(id,loja_id,funcionario_id,permissoes,atualizado_por,atualizado_em) VALUES(?,?,?,?,?,?) ON CONFLICT(loja_id,funcionario_id) DO UPDATE SET permissoes=excluded.permissoes,atualizado_por=excluded.atualizado_por,atualizado_em=excluded.atualizado_em',(ident(),u['loja_id'],uid,json.dumps(p),u['id'],now()))
        return p

    @app.get('/api/produtos/catalogo')
    def catalogo(request:Request):
        with banco() as db:
            u,p=auth(db,request);result=[]
            for row in db.execute('SELECT * FROM produtos WHERE loja_id=? ORDER BY nome,id LIMIT 2000',(u['loja_id'],)):
                product=dict(row);variants=[]
                for r in db.execute('SELECT * FROM variantes_produto WHERE loja_id=? AND produto_id=? ORDER BY atributos,id',(u['loja_id'],row['id'])):
                    v=dict(r);v['atributos']=json.loads(v['atributos']);v['preco_centavos']=v['preco_centavos'] if v['preco_centavos'] is not None else product['preco_centavos'];v['custo_centavos']=v['custo_centavos'] if v['custo_centavos'] is not None else product['custo_centavos']
                    v['preco_especifico_centavos']=r['preco_centavos']
                    if p['ver_custo']:v['custo_especifico_centavos']=r['custo_centavos']
                    else:v.pop('custo_centavos',None)
                    if not p['ver_estoque']:v.pop('quantidade',None);v.pop('estoque_minimo',None)
                    variants.append(v)
                product['variantes']=variants
                if not p['ver_custo']:product.pop('custo_centavos',None)
                result.append(product)
            return result

    def save_product(pid,data,request):
        payload=data.model_dump();payload['nome']=payload['nome'].strip()
        if len(payload['nome'])<2:raise HTTPException(422,'Informe o nome do produto.')
        if payload['imagem_url']:
            try:
                url=urlsplit(payload['imagem_url']);valid=url.scheme=='https' and bool(url.hostname) and not url.username and not url.password and not any(c.isspace() for c in payload['imagem_url'])
            except ValueError:valid=False
            if not valid:raise HTTPException(422,'Use um link HTTPS válido para a imagem do produto.')
        attrs=[]
        for v in payload['variantes']:
            a={k.strip():val.strip() for k,val in v['atributos'].items()}
            if any(not k or not val or len(k)>40 or len(val)>80 for k,val in a.items()):raise HTTPException(422,'Confira os atributos das variantes.')
            attrs.append(json.dumps(a,ensure_ascii=False,sort_keys=True))
        if len(set(attrs))!=len(attrs):raise HTTPException(422,'Não repita a mesma combinação de variante.')
        try:
            with banco() as db:
                u,p=auth(db,request,change=True,owner=True);lock(db,u['loja_id']);u,p=auth(db,request,change=True,owner=True)
                existing=db.execute('SELECT * FROM produtos WHERE loja_id=? AND id=?',(u['loja_id'],pid)).fetchone() if pid else None
                if pid and not existing:raise HTTPException(404,'Produto não encontrado.')
                product_id=pid or ident();old={r['id']:dict(r) for r in db.execute('SELECT * FROM variantes_produto WHERE loja_id=? AND produto_id=?',(u['loja_id'],product_id))}
                kept={v['id'] for v in payload['variantes'] if v['id']}
                if len(kept)!=sum(bool(v['id']) for v in payload['variantes']):raise HTTPException(422,'Não repita a mesma variante.')
                if kept-set(old):raise HTTPException(404,'Variante não encontrada neste produto.')
                if any(v['quantidade'] for vid,v in old.items() if vid not in kept):raise HTTPException(422,'Uma variante com estoque não pode ser removida. Ajuste o estoque ou desative o produto.')
                for v in payload['variantes']:
                    previous=old.get(v['id'])
                    if not previous:continue
                    observed=v['quantidade_anterior']
                    if observed is not None and v['quantidade']==observed:
                        # Edição de nome/preço não deve desfazer vendas ou reposições recentes.
                        v['quantidade']=previous['quantidade']
                    elif observed!=previous['quantidade'] and v['quantidade']!=previous['quantidade']:
                        raise HTTPException(409,'O estoque mudou enquanto você editava. Feche e abra o produto novamente antes de alterar a quantidade.')
                product={k:payload[k] for k in ('nome','categoria','descricao','sku','codigo_barras','imagem_url','custo_centavos','preco_centavos','ativo')};product['ativo']=int(product['ativo'])
                if existing:db.execute('UPDATE produtos SET '+','.join(k+'=?' for k in product)+' WHERE loja_id=? AND id=?',(*product.values(),u['loja_id'],product_id))
                else:insert(db,'produtos',dict(id=product_id,loja_id=u['loja_id'],**product,criado_em=now()))
                for vid,v in old.items():
                    if vid not in kept:db.execute('UPDATE variantes_produto SET ativo=0 WHERE loja_id=? AND id=?',(u['loja_id'],vid))
                for v,a in zip(payload['variantes'],attrs):
                    vid=v['id'] or ident();previous=old.get(vid);quantity=v['quantidade'];values={k:v[k] for k in ('sku','codigo_barras','custo_centavos','preco_centavos','estoque_minimo','ativo')};values['ativo']=int(values['ativo']);values['atributos']=a
                    if previous:
                        if previous['atributos']!=a and db.execute('SELECT id FROM itens_venda WHERE loja_id=? AND variante_id=? LIMIT 1',(u['loja_id'],vid)).fetchone():raise HTTPException(422,'Crie uma nova variante para alterar os atributos de uma variante já vendida.')
                        db.execute('UPDATE variantes_produto SET '+','.join(k+'=?' for k in values)+' WHERE loja_id=? AND id=?',(*values.values(),u['loja_id'],vid))
                    else:insert(db,'variantes_produto',dict(id=vid,loja_id=u['loja_id'],produto_id=product_id,quantidade=0,**values))
                    before=previous['quantidade'] if previous else 0
                    if quantity!=before:
                        if previous and len(data.motivo.strip())<2:raise HTTPException(422,'Informe o motivo da alteração de estoque.')
                        movement(db,u,variant(db,u['loja_id'],vid),quantity-before,'ajuste' if previous else 'inicial',data.motivo.strip() or 'Cadastro inicial')
        except HTTPException:raise
        except Exception as exc:
            if 'unique' in str(exc).lower():raise HTTPException(409,'SKU ou combinação de variante já cadastrado nesta barbearia.')
            raise
        return {'id':product_id}
    @app.post('/api/produtos/catalogo',status_code=201)
    def criar(data:Produto,request:Request):return save_product(None,data,request)
    @app.put('/api/produtos/catalogo/{pid}')
    def editar(pid:str,data:Produto,request:Request):return save_product(pid,data,request)

    @app.post('/api/produtos/estoque')
    def estoque(data:Movimento,request:Request):
        if not data.quantidade or len(data.motivo.strip())<2:raise HTTPException(422,'Informe quantidade e motivo.')
        if data.tipo in ('reposicao','devolucao') and data.quantidade<0 or data.tipo=='perda' and data.quantidade>0:raise HTTPException(422,'Confira o sinal da quantidade: perdas retiram e reposições acrescentam estoque.')
        if data.custo_reposicao_centavos is not None and data.tipo!='reposicao':raise HTTPException(422,'Custo da reposição só se aplica a uma entrada.')
        with banco() as db:
            u,p=auth(db,request,'alterar_estoque',True);lock(db,u['loja_id']);u,p=auth(db,request,'alterar_estoque',True)
            if data.custo_reposicao_centavos is not None and not p['ver_custo']:raise HTTPException(403,'Você não pode alterar custos.')
            mid=hashlib.sha256(('estoque:'+u['loja_id']+':'+data.idempotencia).encode()).hexdigest()[:32] if data.idempotencia else None
            if mid:
                existing=db.execute('SELECT * FROM movimentacoes_estoque WHERE loja_id=? AND id=?',(u['loja_id'],mid)).fetchone()
                if existing:
                    expected=(data.variante_id,data.tipo,data.quantidade,data.motivo.strip(),u['id'],data.custo_reposicao_centavos)
                    actual=tuple(existing[k] for k in ('variante_id','tipo','quantidade','motivo','usuario_id','custo_reposicao_centavos'))
                    if actual!=expected:raise HTTPException(409,'Identificador de movimentação já utilizado. Confira o histórico.')
                    return {'salvo':True}
            v=variant(db,u['loja_id'],data.variante_id);movement(db,u,v,data.quantidade,data.tipo,data.motivo.strip(),cost=data.custo_reposicao_centavos,mid=mid)
            if data.custo_reposicao_centavos is not None:db.execute('UPDATE variantes_produto SET custo_centavos=? WHERE loja_id=? AND id=?',(data.custo_reposicao_centavos,u['loja_id'],v['id']))
        return {'salvo':True}

    @app.post('/api/produtos/vendas',status_code=201)
    def vender(data:Venda,request:Request):
        fingerprint=hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        with banco() as db:
            u,p=auth(db,request,'registrar_venda',True);lock(db,u['loja_id']);u,p=auth(db,request,'registrar_venda',True)
            if data.desconto_centavos and not p['aplicar_desconto']:raise HTTPException(403,'Você não pode aplicar desconto.')
            existing=db.execute('SELECT * FROM vendas_produtos WHERE loja_id=? AND idempotencia=?',(u['loja_id'],data.idempotencia)).fetchone()
            if existing:
                if existing['vendedor_id']!=u['id'] or existing['pedido_hash']!=fingerprint:raise HTTPException(409,'Identificador de venda já utilizado. Confira o histórico antes de tentar novamente.')
                return sale_view(db,u,p,existing)
            quantities={}
            for item in data.itens:quantities[item.variante_id]=quantities.get(item.variante_id,0)+item.quantidade
            items=[];gross=0;cost=0
            for vid,q in quantities.items():
                v=variant(db,u['loja_id'],vid)
                if not v['ativo'] or not v['produto_ativo']:raise HTTPException(422,'Um produto do carrinho está inativo.')
                if q>v['quantidade']:raise HTTPException(409,'Estoque insuficiente para '+v['nome']+'. Confira o carrinho.')
                price=v['preco_centavos'] if v['preco_centavos'] is not None else v['preco_padrao'];unit_cost=v['custo_centavos'] if v['custo_centavos'] is not None else v['custo_padrao']
                items.append((v,q,price,unit_cost));gross+=q*price;cost+=q*unit_cost
            if data.desconto_centavos>gross:raise HTTPException(422,'O desconto não pode superar o subtotal.')
            if data.total_esperado_centavos is not None and data.total_esperado_centavos!=gross-data.desconto_centavos:raise HTTPException(409,'Os preços mudaram. Atualize o catálogo e revise a venda.')
            sale=dict(id=ident(),loja_id=u['loja_id'],vendedor_id=u['id'],vendedor_nome=seller(db,u),criado_em=now(),pagamento=data.pagamento,bruto_centavos=gross,desconto_centavos=data.desconto_centavos,total_centavos=gross-data.desconto_centavos,custo_centavos=cost,status='confirmada',idempotencia=data.idempotencia,pedido_hash=fingerprint,cancelado_por=None,cancelado_em=None,motivo_cancelamento=None,devolver_estoque=0)
            insert(db,'vendas_produtos',sale);remaining=data.desconto_centavos;remaining_gross=gross
            for i,(v,q,price,unit_cost) in enumerate(items):
                discount=remaining*q*price//remaining_gross if remaining_gross else 0;remaining-=discount;remaining_gross-=q*price
                insert(db,'itens_venda',dict(id=ident(),loja_id=u['loja_id'],venda_id=sale['id'],produto_id=v['produto_id'],variante_id=v['id'],nome_snapshot=v['nome'],variante_snapshot=v['atributos'],quantidade=q,preco_unitario_centavos=price,custo_unitario_centavos=unit_cost,desconto_centavos=discount,subtotal_centavos=q*price-discount))
                movement(db,u,v,-q,'venda','Venda presencial',sale['id'])
            return sale_view(db,u,p,sale)

    def period(inicio,fim):
        end=fim or datetime.now(br).date();start=inicio or end
        if start>end or (end-start).days>366:raise HTTPException(422,'Escolha um período de até 366 dias, com início antes do fim.')
        return start.isoformat(),(end+timedelta(days=1)).isoformat()
    @app.get('/api/produtos/vendas')
    def vendas(request:Request,inicio:date|None=None,fim:date|None=None,offset:int=0):
        start,end=period(inicio,fim)
        if not 0<=offset<=1_000_000:raise HTTPException(422,'Página inválida.')
        with banco() as db:
            u,p=auth(db,request);where='loja_id=? AND criado_em>=? AND criado_em<?';params=[u['loja_id'],start,end]
            if u['papel']!='dono':where+=' AND vendedor_id=?';params.append(u['id'])
            return [sale_view(db,u,p,r) for r in db.execute('SELECT * FROM vendas_produtos WHERE '+where+' ORDER BY criado_em DESC,id DESC LIMIT 100 OFFSET ?',(*params,offset))]
    @app.post('/api/produtos/vendas/{sid}/cancelar')
    def cancelar(sid:str,data:Cancelamento,request:Request):
        if len(data.motivo.strip())<2:raise HTTPException(422,'Informe o motivo do cancelamento.')
        with banco() as db:
            u,p=auth(db,request,'cancelar_venda',True);lock(db,u['loja_id']);u,p=auth(db,request,'cancelar_venda',True)
            row=db.execute('SELECT * FROM vendas_produtos WHERE loja_id=? AND id=?',(u['loja_id'],sid)).fetchone()
            if not row or u['papel']!='dono' and row['vendedor_id']!=u['id']:raise HTTPException(404,'Venda não encontrada.')
            if row['status']=='cancelada':return sale_view(db,u,p,row)
            if data.devolver_estoque:
                for item in db.execute('SELECT * FROM itens_venda WHERE loja_id=? AND venda_id=?',(u['loja_id'],sid)).fetchall():movement(db,u,variant(db,u['loja_id'],item['variante_id']),item['quantidade'],'cancelamento',data.motivo.strip(),sid)
            db.execute("UPDATE vendas_produtos SET status='cancelada',cancelado_por=?,cancelado_em=?,motivo_cancelamento=?,devolver_estoque=? WHERE loja_id=? AND id=?",(u['id'],now(),data.motivo.strip(),int(data.devolver_estoque),u['loja_id'],sid))
            return sale_view(db,u,p,db.execute('SELECT * FROM vendas_produtos WHERE loja_id=? AND id=?',(u['loja_id'],sid)).fetchone())
    @app.get('/api/produtos/movimentacoes')
    def movimentacoes(request:Request,produto_id:str='',inicio:date|None=None,fim:date|None=None,offset:int=0):
        start,end=period(inicio,fim)
        if not 0<=offset<=1_000_000:raise HTTPException(422,'Página inválida.')
        with banco() as db:
            u,p=auth(db,request,'ver_estoque',owner=True);where='m.loja_id=? AND m.criado_em>=? AND m.criado_em<?';params=[u['loja_id'],start,end]
            if produto_id:where+=' AND m.produto_id=?';params.append(produto_id)
            result=[dict(r) for r in db.execute('SELECT m.*,p.nome,v.atributos FROM movimentacoes_estoque m JOIN produtos p ON p.loja_id=m.loja_id AND p.id=m.produto_id JOIN variantes_produto v ON v.loja_id=m.loja_id AND v.id=m.variante_id WHERE '+where+' ORDER BY m.criado_em DESC,m.id DESC LIMIT 100 OFFSET ?',(*params,offset))]
            return result
    @app.get('/api/produtos/resumo')
    def resumo(request:Request,inicio:date|None=None,fim:date|None=None):
        start,end=period(inicio,fim)
        with banco() as db:
            u,p=auth(db,request);where="loja_id=? AND criado_em>=? AND criado_em<? AND status='confirmada'";params=[u['loja_id'],start,end]
            if u['papel']!='dono':where+=' AND vendedor_id=?';params.append(u['id'])
            r=dict(db.execute('SELECT COUNT(*) AS vendas,COALESCE(SUM(bruto_centavos),0) AS bruto_centavos,COALESCE(SUM(desconto_centavos),0) AS desconto_centavos,COALESCE(SUM(total_centavos),0) AS total_centavos,COALESCE(SUM(custo_centavos),0) AS custo_centavos FROM vendas_produtos WHERE '+where,params).fetchone())
            r['itens_vendidos']=db.execute('SELECT COALESCE(SUM(i.quantidade),0) AS total FROM itens_venda i JOIN vendas_produtos s ON s.loja_id=i.loja_id AND s.id=i.venda_id WHERE '+where.replace('loja_id=','s.loja_id=').replace('criado_em','s.criado_em').replace('status=','s.status=').replace('vendedor_id=','s.vendedor_id='),params).fetchone()['total']
            if p['ver_lucro']:r['lucro_bruto_centavos']=r['total_centavos']-r['custo_centavos']
            if not p['ver_custo']:r.pop('custo_centavos',None)
            if p['ver_estoque']:
                r['estoque_baixo']=[dict(x) for x in db.execute('SELECT v.id,v.produto_id,p.nome,v.atributos,v.quantidade,v.estoque_minimo FROM variantes_produto v JOIN produtos p ON p.loja_id=v.loja_id AND p.id=v.produto_id WHERE v.loja_id=? AND v.ativo=1 AND p.ativo=1 AND v.quantidade<=v.estoque_minimo ORDER BY v.quantidade,p.nome LIMIT 2000',(u['loja_id'],))]
            if u['papel']=='dono':
                service=db.execute("SELECT COALESCE(SUM(preco),0) AS total FROM agendamentos WHERE loja_id=? AND status='concluido' AND inicio>=? AND inicio<?",(u['loja_id'],start,end)).fetchone()['total']
                r['servicos_centavos']=round(service*100);r['faturamento_total_centavos']=r['servicos_centavos']+r['total_centavos']
            return r
    @app.get('/produtos',response_class=FileResponse)
    def pagina_produtos():return FileResponse(c['ROOT']/'produtos.html',media_type='text/html')
    @app.get('/produtos.js')
    def script_produtos():return FileResponse(c['ROOT']/'produtos.js',media_type='application/javascript')
    @app.get('/produtos.css')
    def css_produtos():return FileResponse(c['ROOT']/'produtos.css',media_type='text/css')
