"""Planos dos clientes: ciclos imutáveis, caixa por pagamento confirmado e créditos na conclusão."""
import calendar
import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Literal
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict

PERMISSIONS=('assinaturas_ver','assinaturas_utilizar','assinaturas_cadastrar','assinaturas_historico','assinaturas_financeiro')
TABLES={
 'mensal_planos':['id','loja_id','nome','descricao','valor_centavos','servicos','ciclo_unidade','ciclo_quantidade','vencimento','status','beneficios','observacoes','criado_em','atualizado_em'],
 'mensal_assinantes':['id','loja_id','cliente_telefone','cliente_nome','plano_id','inicio','status','renovacao','observacoes','criado_por','criado_em','cancelado_em','motivo_cancelamento'],
 'mensal_ciclos':['id','loja_id','assinante_id','plano_id','plano_nome','servicos','inicio','fim','vencimento','valor_centavos','desconto_centavos','acrescimo_centavos','total_centavos','pagamento','status','pago_em','confirmado_por','observacoes','provedor','referencia_externa'],
 'mensal_utilizacoes':['id','loja_id','assinante_id','ciclo_id','agendamento_id','servico_id','servico_nome','barbeiro_id','barbeiro_nome','cliente_nome','plano_nome','criado_em','registrado_por','estornada_em','estornado_por'],
 'mensal_eventos':['id','loja_id','assinante_id','tipo','usuario_id','usuario_nome','criado_em','detalhes'],
}
DDL={
 'mensal_planos':"id TEXT PRIMARY KEY,loja_id TEXT NOT NULL REFERENCES lojas(id),nome TEXT NOT NULL,descricao TEXT NOT NULL,valor_centavos BIGINT NOT NULL CHECK(valor_centavos>=0),servicos TEXT NOT NULL,ciclo_unidade TEXT NOT NULL CHECK(ciclo_unidade IN ('meses','dias')),ciclo_quantidade INTEGER NOT NULL CHECK(ciclo_quantidade>0),vencimento TEXT,status TEXT NOT NULL CHECK(status IN ('ativo','inativo','arquivado')),beneficios TEXT NOT NULL,observacoes TEXT NOT NULL,criado_em TEXT NOT NULL,atualizado_em TEXT NOT NULL,UNIQUE(loja_id,id)",
 'mensal_assinantes':"id TEXT PRIMARY KEY,loja_id TEXT NOT NULL REFERENCES lojas(id),cliente_telefone TEXT NOT NULL,cliente_nome TEXT NOT NULL,plano_id TEXT NOT NULL,inicio TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('ativa','pausada','cancelada')),renovacao INTEGER NOT NULL CHECK(renovacao IN (0,1)),observacoes TEXT NOT NULL,criado_por TEXT NOT NULL,criado_em TEXT NOT NULL,cancelado_em TEXT,motivo_cancelamento TEXT,UNIQUE(loja_id,id),FOREIGN KEY(loja_id,plano_id) REFERENCES mensal_planos(loja_id,id)",
 'mensal_ciclos':"id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,assinante_id TEXT NOT NULL,plano_id TEXT NOT NULL,plano_nome TEXT NOT NULL,servicos TEXT NOT NULL,inicio TEXT NOT NULL,fim TEXT NOT NULL CHECK(fim>inicio),vencimento TEXT NOT NULL,valor_centavos BIGINT NOT NULL CHECK(valor_centavos>=0),desconto_centavos BIGINT NOT NULL CHECK(desconto_centavos>=0 AND desconto_centavos<=valor_centavos),acrescimo_centavos BIGINT NOT NULL CHECK(acrescimo_centavos>=0),total_centavos BIGINT NOT NULL CHECK(total_centavos=valor_centavos-desconto_centavos+acrescimo_centavos),pagamento TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pendente','pago','cancelado')),pago_em TEXT,confirmado_por TEXT,observacoes TEXT NOT NULL,provedor TEXT NOT NULL,referencia_externa TEXT,UNIQUE(loja_id,id),UNIQUE(loja_id,assinante_id,inicio),FOREIGN KEY(loja_id,assinante_id) REFERENCES mensal_assinantes(loja_id,id),FOREIGN KEY(loja_id,plano_id) REFERENCES mensal_planos(loja_id,id)",
 'mensal_utilizacoes':"id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,assinante_id TEXT NOT NULL,ciclo_id TEXT NOT NULL,agendamento_id BIGINT NOT NULL REFERENCES agendamentos(id),servico_id TEXT NOT NULL,servico_nome TEXT NOT NULL,barbeiro_id TEXT NOT NULL,barbeiro_nome TEXT NOT NULL,cliente_nome TEXT NOT NULL,plano_nome TEXT NOT NULL,criado_em TEXT NOT NULL,registrado_por TEXT NOT NULL,estornada_em TEXT,estornado_por TEXT,FOREIGN KEY(loja_id,assinante_id) REFERENCES mensal_assinantes(loja_id,id),FOREIGN KEY(loja_id,ciclo_id) REFERENCES mensal_ciclos(loja_id,id)",
 'mensal_eventos':"id TEXT PRIMARY KEY,loja_id TEXT NOT NULL REFERENCES lojas(id),assinante_id TEXT,tipo TEXT NOT NULL,usuario_id TEXT NOT NULL,usuario_nome TEXT NOT NULL,criado_em TEXT NOT NULL,detalhes TEXT NOT NULL",
}
INDEXES=[
 "CREATE UNIQUE INDEX IF NOT EXISTS mensal_cliente_atual ON mensal_assinantes(loja_id,cliente_telefone) WHERE status<>'cancelada'",
 "CREATE UNIQUE INDEX IF NOT EXISTS mensal_uso_unico ON mensal_utilizacoes(loja_id,agendamento_id) WHERE estornada_em IS NULL",
 "CREATE INDEX IF NOT EXISTS mensal_ciclo_cliente ON mensal_ciclos(loja_id,assinante_id,inicio)",
 "CREATE INDEX IF NOT EXISTS mensal_uso_ciclo ON mensal_utilizacoes(loja_id,ciclo_id,servico_id)",
 "CREATE INDEX IF NOT EXISTS mensal_evento_cliente ON mensal_eventos(loja_id,assinante_id,criado_em)",
]
def criar_tabelas(db):
    for name,ddl in DDL.items():db.execute('CREATE TABLE IF NOT EXISTS '+name+' ('+ddl+')')
    for sql in INDEXES:db.execute(sql)
def telefone(value):
    number=re.sub(r'\D','',str(value))
    if len(number) in (12,13) and number.startswith('55'):number=number[2:]
    if len(number) not in (10,11):raise HTTPException(422,'Informe o WhatsApp do cliente com DDD.')
    return number
def proximo(inicio,unidade,quantidade):
    if unidade=='dias':return inicio+timedelta(days=quantidade)
    month=inicio.year*12+inicio.month-1+quantidade
    year,m=divmod(month,12);m+=1
    return date(year,m,min(inicio.day,calendar.monthrange(year,m)[1]))
class Entrada(BaseModel):
    model_config=ConfigDict(extra='forbid')
class ServicoPlano(Entrada):
    servico_id:str=Field(min_length=1,max_length=50)
    quantidade:int|None=Field(default=None,ge=1,le=10000,strict=True)
class Plano(Entrada):
    nome:str=Field(min_length=2,max_length=100)
    descricao:str=Field(default='',max_length=1000)
    valor_centavos:int=Field(ge=0,le=100_000_000,strict=True)
    servicos:list[ServicoPlano]=Field(min_length=1,max_length=60)
    ciclo_unidade:Literal['meses','dias']='meses'
    ciclo_quantidade:int=Field(default=1,ge=1,le=366,strict=True)
    vencimento:date|None=None
    status:Literal['ativo','inativo','arquivado']='ativo'
    beneficios:str=Field(default='',max_length=2000)
    observacoes:str=Field(default='',max_length=2000)
class Adesao(Entrada):
    cliente_telefone:str=Field(min_length=10,max_length=25)
    plano_id:str=Field(min_length=1,max_length=64)
    inicio:date
    fim:date|None=None
    vencimento:date|None=None
    pagamento:Literal['pix','dinheiro','debito','credito','outro']='pix'
    valor_centavos:int|None=Field(default=None,ge=0,le=100_000_000,strict=True)
    desconto_centavos:int=Field(default=0,ge=0,le=100_000_000,strict=True)
    acrescimo_centavos:int=Field(default=0,ge=0,le=100_000_000,strict=True)
    renovacao:bool=True
    observacoes:str=Field(default='',max_length=2000)
class Cobranca(Entrada):
    valor_centavos:int=Field(ge=0,le=100_000_000,strict=True)
    desconto_centavos:int=Field(default=0,ge=0,le=100_000_000,strict=True)
    acrescimo_centavos:int=Field(default=0,ge=0,le=100_000_000,strict=True)
    vencimento:date
    pagamento:Literal['pix','dinheiro','debito','credito','outro']='pix'
    observacoes:str=Field(default='',max_length=2000)
class Pago(Entrada):
    confirmado:bool=False
    data_pagamento:date
    pagamento:Literal['pix','dinheiro','debito','credito','outro']='pix'
class Acao(Entrada):
    acao:Literal['pausar','retomar','cancelar','trocar_plano','renovar','cancelar_cobranca']
    plano_id:str|None=Field(default=None,max_length=64)
    data:date|None=None
    fim:date|None=None
    motivo:str=Field(default='',max_length=2000)
class Permissoes(Entrada):
    permissoes:dict[str,bool]

def instalar(app,c):
    banco=c['banco'];br=c['BRASIL']
    def now():return datetime.now(br).isoformat(timespec='seconds')
    def today():return datetime.now(br).date()
    def ident():return secrets.token_hex(16)
    def lock(db,tenant):
        if c['DATABASE_URL']:db.execute('SELECT pg_advisory_xact_lock(?)',(int.from_bytes(hashlib.sha256(('mensal:'+tenant).encode()).digest()[:8],'big',signed=True),))
        elif not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    with banco() as db:
        if c['DATABASE_URL']:db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        criar_tabelas(db)
    def perms(db,user):
        if user['papel']=='dono':return dict.fromkeys(PERMISSIONS,True)
        row=db.execute('SELECT permissoes FROM permissoes_caixa WHERE loja_id=? AND funcionario_id=?',(user['loja_id'],user['id'])).fetchone()
        values=json.loads(row['permissoes']) if row else {}
        return {key:bool(values.get(key,False)) for key in PERMISSIONS}
    def auth(db,request,key='assinaturas_ver',change=False,owner=False):
        user=c['usuario'](request,db,change);p=perms(db,user)
        if (owner and user['papel']!='dono') or not p.get(key,False):raise HTTPException(403,'Peça ao dono para autorizar esta função em Assinaturas.')
        return user,p
    def insert(db,table,data):
        cols=list(data);db.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(data.values()))
    def audit(db,user,kind,details,member=None):
        insert(db,'mensal_eventos',dict(id=ident(),loja_id=user['loja_id'],assinante_id=member,tipo=kind,usuario_id=user['id'],usuario_nome=user['email'],criado_em=now(),detalhes=json.dumps(details,ensure_ascii=False)))
    def get(db,table,user,rid):
        row=db.execute('SELECT * FROM '+table+' WHERE loja_id=? AND id=?',(user['loja_id'],rid)).fetchone()
        if not row:raise HTTPException(404,'Registro de assinatura não encontrado.')
        return dict(row)
    def plan_json(row,financial=True):
        r=dict(row);r['servicos']=json.loads(r['servicos'])
        if not financial:r.pop('valor_centavos',None);r.pop('observacoes',None)
        return r
    def plan_data(db,user,data):
        cfg=c['config_da_loja'](db,user['loja_id']);services={s['id']:s['nome'] for s in cfg['servicos']}
        if len({s.servico_id for s in data.servicos})!=len(data.servicos):raise HTTPException(422,'Não repita serviços no plano.')
        if data.ciclo_unidade=='meses' and data.ciclo_quantidade>36:raise HTTPException(422,'Use um ciclo de até 36 meses.')
        items=[]
        for s in data.servicos:
            if s.servico_id not in services:raise HTTPException(422,'Escolha serviços da sua barbearia.')
            items.append({'servico_id':s.servico_id,'nome':services[s.servico_id],'quantidade':s.quantidade})
        values=data.model_dump(mode='json');values['nome']=data.nome.strip();values['servicos']=json.dumps(items,ensure_ascii=False)
        if len(values['nome'])<2:raise HTTPException(422,'Informe o nome do plano.')
        return values
    def latest(db,user,member):
        row=db.execute('SELECT * FROM mensal_ciclos WHERE loja_id=? AND assinante_id=? ORDER BY inicio DESC,id DESC LIMIT 1',(user['loja_id'],member['id'])).fetchone()
        return dict(row) if row else None
    def current_cycle(db,user,member):
        row=db.execute("SELECT * FROM mensal_ciclos WHERE loja_id=? AND assinante_id=? AND inicio<=? AND fim>? ORDER BY inicio DESC,id DESC LIMIT 1",(user['loja_id'],member['id'],today().isoformat(),today().isoformat())).fetchone()
        return dict(row) if row else latest(db,user,member)
    def new_cycle(db,user,member,plan,start,end=None,billing=None):
        if end is None:
            try:
                end=proximo(start,plan['ciclo_unidade'],plan['ciclo_quantidade'])
                if plan['ciclo_unidade']=='meses':
                    anchor=date.fromisoformat(member['inicio']).day
                    end=end.replace(day=min(anchor,calendar.monthrange(end.year,end.month)[1]))
            except (ValueError,OverflowError):raise HTTPException(422,'Confira as datas do ciclo.')
        if not start<end or (end-start).days>1100:raise HTTPException(422,'Confira o período do ciclo.')
        old=latest(db,user,member)
        if old and start.isoformat()<old['fim']:raise HTTPException(409,'O novo ciclo não pode sobrepor o anterior.')
        price=plan['valor_centavos'] if billing is None or billing.valor_centavos is None else billing.valor_centavos
        discount=billing.desconto_centavos if billing else 0;extra=billing.acrescimo_centavos if billing else 0
        if discount>price:raise HTTPException(422,'O desconto não pode ultrapassar o valor.')
        rid=ident()
        insert(db,'mensal_ciclos',dict(id=rid,loja_id=user['loja_id'],assinante_id=member['id'],plano_id=plan['id'],plano_nome=plan['nome'],servicos=plan['servicos'],inicio=start.isoformat(),fim=end.isoformat(),vencimento=(billing.vencimento if billing and billing.vencimento else start).isoformat(),valor_centavos=price,desconto_centavos=discount,acrescimo_centavos=extra,total_centavos=price-discount+extra,pagamento=billing.pagamento if billing else 'pix',status='pendente',pago_em=None,confirmado_por=None,observacoes=billing.observacoes if billing else '',provedor='manual',referencia_externa=None))
        audit(db,user,'renovacao',{'ciclo_id':rid,'inicio':start.isoformat(),'fim':end.isoformat(),'plano':plan['nome']},member['id'])
        return get(db,'mensal_ciclos',user,rid)
    def ensure_cycle(db,user,member):
        last=latest(db,user,member)
        # Renovação cria cobrança pendente, nunca confirma pagamento nem altera o ciclo antigo.
        if last and member['status']=='ativa' and member['renovacao'] and last['status']=='pago' and last['fim']<=today().isoformat():
            plan=get(db,'mensal_planos',user,member['plano_id'])
            return new_cycle(db,user,member,plan,date.fromisoformat(last['fim']))
        return last
    def balances(db,user,cycle):
        counts={r['servico_id']:r['total'] for r in db.execute('SELECT servico_id,COUNT(*) AS total FROM mensal_utilizacoes WHERE loja_id=? AND ciclo_id=? AND estornada_em IS NULL GROUP BY servico_id',(user['loja_id'],cycle['id']))}
        return [{**s,'utilizados':counts.get(s['servico_id'],0),'restantes':None if s['quantidade'] is None else max(0,s['quantidade']-counts.get(s['servico_id'],0))} for s in json.loads(cycle['servicos'])]
    def member_json(db,user,member,p):
        cycle=current_cycle(db,user,member);r=dict(member);r['ciclo']=None
        r['status_visual']=member['status'];r['ativo']=False
        if cycle:
            paid=cycle['status']=='pago';inside=cycle['inicio']<=today().isoformat()<cycle['fim']
            if member['status']=='ativa':
                r['ativo']=paid and inside
                r['status_visual']='vencimento_proximo' if r['ativo'] and (date.fromisoformat(cycle['fim'])-today()).days<=3 else 'ativa' if r['ativo'] else 'pagamento_atrasado' if cycle['status']=='pendente' and cycle['vencimento']<today().isoformat() else 'pendente' if not paid else 'vencida'
            safe={k:cycle[k] for k in ('id','plano_id','plano_nome','inicio','fim','status')}
            safe['servicos']=balances(db,user,cycle)
            if p['assinaturas_financeiro']:safe.update({k:cycle[k] for k in ('vencimento','valor_centavos','desconto_centavos','acrescimo_centavos','total_centavos','pagamento','pago_em','observacoes')})
            r['ciclo']=safe
        if not p['assinaturas_financeiro']:r.pop('observacoes',None)
        return r

    @app.get('/api/mensalistas/acesso')
    def acesso(request:Request):
        with banco() as db:
            user=c['usuario'](request,db)
            return {'permissoes':perms(db,user),'dono':user['papel']=='dono'}
    @app.get('/api/mensalistas/planos')
    def planos(request:Request):
        with banco() as db:
            user,p=auth(db,request)
            return [plan_json(r,p['assinaturas_financeiro']) for r in db.execute('SELECT * FROM mensal_planos WHERE loja_id=? ORDER BY criado_em DESC,id',(user['loja_id'],))]
    @app.post('/api/mensalistas/planos',status_code=201)
    def criar_plano(data:Plano,request:Request):
        with banco() as db:
            user,p=auth(db,request,change=True,owner=True);lock(db,user['loja_id'])
            values=plan_data(db,user,data);rid=ident()
            insert(db,'mensal_planos',{'id':rid,'loja_id':user['loja_id'],**values,'criado_em':now(),'atualizado_em':now()})
            audit(db,user,'plano_criado',{'plano_id':rid,'dados':values})
            return plan_json(get(db,'mensal_planos',user,rid))
    @app.put('/api/mensalistas/planos/{rid}')
    def editar_plano(rid:str,data:Plano,request:Request):
        with banco() as db:
            user,p=auth(db,request,change=True,owner=True);lock(db,user['loja_id'])
            old=get(db,'mensal_planos',user,rid);values=plan_data(db,user,data)
            db.execute('UPDATE mensal_planos SET '+','.join(k+'=?' for k in values)+',atualizado_em=? WHERE loja_id=? AND id=?',(*values.values(),now(),user['loja_id'],rid))
            audit(db,user,'plano_alterado',{'plano_id':rid,'antes':old,'depois':values})
            return plan_json(get(db,'mensal_planos',user,rid))
    def cliente(db,user,phone):
        where='loja_id=?';params=[user['loja_id']]
        if user['papel']=='barbeiro':where+=' AND barbeiro_id=?';params.append(user['barbeiro_id'])
        for r in db.execute('SELECT cliente_nome,cliente_telefone FROM agendamentos WHERE '+where+' ORDER BY inicio DESC,id DESC',params):
            if telefone(r['cliente_telefone'])==phone:return r['cliente_nome']
        raise HTTPException(404,'Use um cliente já cadastrado pelos agendamentos permitidos.')
    @app.post('/api/mensalistas/assinantes',status_code=201)
    def adesao(data:Adesao,request:Request):
        phone=telefone(data.cliente_telefone)
        with banco() as db:
            user,p=auth(db,request,'assinaturas_cadastrar',True);lock(db,user['loja_id'])
            if user['papel']!='dono' and (data.valor_centavos is not None or data.desconto_centavos or data.acrescimo_centavos):raise HTTPException(403,'Somente o dono pode alterar valores da adesão.')
            name=cliente(db,user,phone);plan=get(db,'mensal_planos',user,data.plano_id)
            if plan['status']!='ativo' or (plan['vencimento'] and plan['vencimento']<today().isoformat()):raise HTTPException(409,'Este plano não está disponível para novas adesões.')
            if db.execute("SELECT id FROM mensal_assinantes WHERE loja_id=? AND cliente_telefone=? AND status<>'cancelada'",(user['loja_id'],phone)).fetchone():raise HTTPException(409,'O cliente já tem uma assinatura. Use trocar plano ou renovar.')
            rid=ident();member=dict(id=rid,loja_id=user['loja_id'],cliente_telefone=phone,cliente_nome=name,plano_id=plan['id'],inicio=data.inicio.isoformat(),status='ativa',renovacao=int(data.renovacao),observacoes=data.observacoes,criado_por=user['id'],criado_em=now(),cancelado_em=None,motivo_cancelamento=None)
            insert(db,'mensal_assinantes',member)
            audit(db,user,'adesao',{'plano':plan['nome'],'inicio':member['inicio']},rid)
            new_cycle(db,user,member,plan,data.inicio,data.fim,data)
            return member_json(db,user,member,p)
    @app.get('/api/mensalistas/assinantes')
    def assinantes(request:Request,busca:str='',plano_id:str='',status:str='',vencimento:date|None=None,barbeiro_id:str='',ativo:bool|None=None,offset:int=0):
        if len(busca)>100 or offset<0:raise HTTPException(422,'Confira a pesquisa.')
        with banco() as db:
            user,p=auth(db,request);lock(db,user['loja_id'])
            rows=[dict(r) for r in db.execute('SELECT * FROM mensal_assinantes WHERE loja_id=? ORDER BY criado_em DESC,id DESC',(user['loja_id'],))]
            result=[]
            for row in rows:
                if busca.lower() not in (row['cliente_nome']+' '+row['cliente_telefone']).lower() or (plano_id and row['plano_id']!=plano_id):continue
                ensure_cycle(db,user,row);item=member_json(db,user,row,p)
                if status and item['status_visual']!=status:continue
                if ativo is not None and item['ativo']!=ativo:continue
                if vencimento and (not item['ciclo'] or item['ciclo']['fim']!=vencimento.isoformat()):continue
                if barbeiro_id and not db.execute('SELECT id FROM mensal_utilizacoes WHERE loja_id=? AND assinante_id=? AND barbeiro_id=? LIMIT 1',(user['loja_id'],row['id'],barbeiro_id)).fetchone():continue
                result.append(item)
            return {'items':result[offset:offset+100],'total':len(result),'offset':offset}
    @app.get('/api/mensalistas/cliente/{phone}')
    def consultar_cliente(phone:str,request:Request):
        phone=telefone(phone)
        with banco() as db:
            user,p=auth(db,request);lock(db,user['loja_id'])
            rows=[dict(r) for r in db.execute('SELECT * FROM mensal_assinantes WHERE loja_id=? AND cliente_telefone=? ORDER BY criado_em DESC,id DESC',(user['loja_id'],phone))]
            for row in rows:ensure_cycle(db,user,row)
            return {'assinaturas':[member_json(db,user,row,p) for row in rows],'pode_cadastrar':p['assinaturas_cadastrar']}
    @app.get('/api/mensalistas/assinantes/{rid}')
    def historico(rid:str,request:Request):
        with banco() as db:
            user,p=auth(db,request,'assinaturas_historico');lock(db,user['loja_id'])
            member=get(db,'mensal_assinantes',user,rid);ensure_cycle(db,user,member)
            cycles=[dict(r) for r in db.execute('SELECT * FROM mensal_ciclos WHERE loja_id=? AND assinante_id=? ORDER BY inicio DESC',(user['loja_id'],rid))]
            for cycle in cycles:
                cycle['servicos']=balances(db,user,cycle)
                if not p['assinaturas_financeiro']:
                    for k in ('valor_centavos','total_centavos','desconto_centavos','acrescimo_centavos','pagamento','pago_em','confirmado_por','observacoes','provedor','referencia_externa'):cycle.pop(k,None)
            uses=[dict(r) for r in db.execute('SELECT * FROM mensal_utilizacoes WHERE loja_id=? AND assinante_id=? ORDER BY criado_em DESC,id DESC LIMIT 1000',(user['loja_id'],rid))]
            events=[]
            for row in db.execute('SELECT * FROM mensal_eventos WHERE loja_id=? AND assinante_id=? ORDER BY criado_em DESC,id DESC LIMIT 1000',(user['loja_id'],rid)):
                event=dict(row);event['detalhes']=json.loads(event['detalhes']) if p['assinaturas_financeiro'] else {}
                events.append(event)
            return {'assinante':member_json(db,user,member,p),'ciclos':cycles,'utilizacoes':uses,'eventos':events}
    @app.put('/api/mensalistas/ciclos/{rid}')
    def editar_cobranca(rid:str,data:Cobranca,request:Request):
        if data.desconto_centavos>data.valor_centavos:raise HTTPException(422,'Confira o desconto.')
        with banco() as db:
            user,p=auth(db,request,change=True,owner=True);lock(db,user['loja_id']);old=get(db,'mensal_ciclos',user,rid)
            if old['status']!='pendente':raise HTTPException(409,'Cobrança paga ou cancelada mantém seus valores históricos.')
            values=data.model_dump(mode='json');values['total_centavos']=data.valor_centavos-data.desconto_centavos+data.acrescimo_centavos
            db.execute('UPDATE mensal_ciclos SET '+','.join(k+'=?' for k in values)+' WHERE loja_id=? AND id=?',(*values.values(),user['loja_id'],rid))
            audit(db,user,'cobranca_alterada',{'ciclo_id':rid,'antes':old,'depois':values},old['assinante_id'])
            return get(db,'mensal_ciclos',user,rid)
    @app.post('/api/mensalistas/ciclos/{rid}/pagamento')
    def pagar(rid:str,data:Pago,request:Request):
        if not data.confirmado:raise HTTPException(422,'Confirme que o recebimento foi conferido.')
        if data.data_pagamento>today():raise HTTPException(422,'O pagamento confirmado não pode ter data futura.')
        with banco() as db:
            user,p=auth(db,request,change=True,owner=True);lock(db,user['loja_id']);cycle=get(db,'mensal_ciclos',user,rid)
            if cycle['status']=='pago':return {'id':rid,'status':'pago','ja_confirmado':True}
            if cycle['status']=='cancelado':raise HTTPException(409,'Cobrança cancelada não pode ser confirmada.')
            db.execute("UPDATE mensal_ciclos SET status='pago',pago_em=?,confirmado_por=?,pagamento=? WHERE loja_id=? AND id=?",(data.data_pagamento.isoformat(),user['id'],data.pagamento,user['loja_id'],rid))
            audit(db,user,'pagamento_confirmado',{'ciclo_id':rid,'valor_centavos':cycle['total_centavos'],'pagamento':data.pagamento,'pago_em':data.data_pagamento.isoformat()},cycle['assinante_id'])
            return {'id':rid,'status':'pago','ja_confirmado':False}
    @app.post('/api/mensalistas/assinantes/{rid}/acao')
    def mudar(rid:str,data:Acao,request:Request):
        with banco() as db:
            user,p=auth(db,request,change=True,owner=True);lock(db,user['loja_id']);member=get(db,'mensal_assinantes',user,rid)
            if member['status']=='cancelada':raise HTTPException(409,'Assinatura cancelada mantém o histórico. Cadastre uma nova adesão.')
            if data.acao=='trocar_plano':
                if not data.plano_id:raise HTTPException(422,'Escolha o novo plano.')
                plan=get(db,'mensal_planos',user,data.plano_id)
                if plan['status']!='ativo' or (plan['vencimento'] and plan['vencimento']<today().isoformat()):raise HTTPException(409,'Plano indisponível.')
                db.execute('UPDATE mensal_assinantes SET plano_id=? WHERE loja_id=? AND id=?',(plan['id'],user['loja_id'],rid))
                audit(db,user,'troca_plano',{'anterior':get(db,'mensal_planos',user,member['plano_id'])['nome'],'novo':plan['nome'],'aplicacao':'proximo_ciclo'},rid)
            elif data.acao=='renovar':
                if member['status']=='pausada':raise HTTPException(409,'Retome a assinatura antes de renovar.')
                last=latest(db,user,member);plan=get(db,'mensal_planos',user,member['plano_id'])
                start=data.data or (date.fromisoformat(last['fim']) if last else today())
                new_cycle(db,user,member,plan,start,data.fim)
            elif data.acao=='cancelar_cobranca':
                cycle=latest(db,user,member)
                if not cycle or cycle['status']!='pendente':raise HTTPException(409,'Somente uma cobrança pendente pode ser cancelada.')
                db.execute("UPDATE mensal_ciclos SET status='cancelado' WHERE loja_id=? AND id=?",(user['loja_id'],cycle['id']))
                audit(db,user,'cobranca_cancelada',{'ciclo_id':cycle['id'],'motivo':data.motivo},rid)
            else:
                state={'pausar':'pausada','retomar':'ativa','cancelar':'cancelada'}[data.acao]
                if data.acao=='cancelar' and (not data.data or data.data>today()):raise HTTPException(422,'Informe a data efetiva do cancelamento, até hoje.')
                if state=='ativa' and member['status']!='pausada':raise HTTPException(409,'Esta assinatura não está pausada.')
                if state=='pausada' and member['status']!='ativa':raise HTTPException(409,'Esta assinatura não está ativa.')
                db.execute('UPDATE mensal_assinantes SET status=?,cancelado_em=?,motivo_cancelamento=? WHERE loja_id=? AND id=?',(state,data.data.isoformat() if state=='cancelada' else None,data.motivo if state=='cancelada' else None,user['loja_id'],rid))
                if state=='cancelada':db.execute("UPDATE mensal_ciclos SET status='cancelado' WHERE loja_id=? AND assinante_id=? AND status='pendente'",(user['loja_id'],rid))
                audit(db,user,data.acao,{'anterior':member['status'],'status':state,'data':data.data.isoformat() if data.data else today().isoformat(),'motivo':data.motivo},rid)
            return member_json(db,user,get(db,'mensal_assinantes',user,rid),p)
    @app.get('/api/mensalistas/permissoes')
    def ler_permissoes(request:Request):
        with banco() as db:
            user,p=auth(db,request,owner=True);result=[]
            for r in db.execute('SELECT * FROM funcionarios WHERE loja_id=? AND ativo=1',(user['loja_id'],)):
                staff=dict(r);staff['papel']='barbeiro';result.append({'id':staff['id'],'nome':next((b['nome'] for b in c['config_da_loja'](db,user['loja_id'])['barbeiros'] if b['id']==staff['barbeiro_id']),staff['email']),'email':staff['email'],'permissoes':perms(db,staff)})
            return result
    @app.put('/api/mensalistas/permissoes/{rid}')
    def salvar_permissoes(rid:str,data:Permissoes,request:Request):
        if set(data.permissoes)-set(PERMISSIONS):raise HTTPException(422,'Permissão desconhecida.')
        values=dict.fromkeys(PERMISSIONS,False);values.update(data.permissoes)
        if not values['assinaturas_ver'] and any(v for k,v in values.items() if k!='assinaturas_ver'):raise HTTPException(422,'Autorize a consulta de assinaturas antes das outras funções.')
        with banco() as db:
            user,p=auth(db,request,change=True,owner=True);lock(db,user['loja_id'])
            if not db.execute('SELECT id FROM funcionarios WHERE id=? AND loja_id=? AND ativo=1',(rid,user['loja_id'])).fetchone():raise HTTPException(404,'Profissional não encontrado.')
            old=db.execute('SELECT permissoes FROM permissoes_caixa WHERE loja_id=? AND funcionario_id=?',(user['loja_id'],rid)).fetchone();merged=json.loads(old['permissoes']) if old else {};merged.update(values)
            db.execute('INSERT INTO permissoes_caixa(id,loja_id,funcionario_id,permissoes,atualizado_por,atualizado_em) VALUES(?,?,?,?,?,?) ON CONFLICT(loja_id,funcionario_id) DO UPDATE SET permissoes=excluded.permissoes,atualizado_por=excluded.atualizado_por,atualizado_em=excluded.atualizado_em',(ident(),user['loja_id'],rid,json.dumps(merged),user['id'],now()))
            audit(db,user,'permissoes_alteradas',{'funcionario_id':rid,'permissoes':values})
            return values

    def selected_member(db,user,phone):
        row=db.execute("SELECT * FROM mensal_assinantes WHERE loja_id=? AND cliente_telefone=? AND status<>'cancelada' ORDER BY criado_em DESC,id DESC LIMIT 1",(user['loja_id'],phone)).fetchone()
        return dict(row) if row else None
    def coverage(db,user,member,service):
        if not member:return None
        cycle=current_cycle(db,user,member)
        if not cycle:return None
        current=cycle['inicio']<=today().isoformat()<cycle['fim']
        active=member['status']=='ativa' and cycle['status']=='pago' and current
        item=next((s for s in balances(db,user,cycle) if s['servico_id']==service),None)
        return {'member':member,'cycle':cycle,'item':item,'active':active,'available':active and item is not None and (item['restantes'] is None or item['restantes']>0)}
    def consumir(db,user,row,usar):
        lock(db,user['loja_id'])
        if usar is True and not perms(db,user)['assinaturas_utilizar']:raise HTTPException(403,'Peça autorização para registrar utilizações de assinatura.')
        existing=db.execute('SELECT id FROM mensal_utilizacoes WHERE loja_id=? AND agendamento_id=? AND estornada_em IS NULL',(user['loja_id'],row['id'])).fetchone()
        if existing:
            if usar is False:raise HTTPException(409,'Este atendimento já utilizou o plano. Reabra para corrigir antes de cobrar avulso.')
            return
        member=selected_member(db,user,telefone(row['cliente_telefone']))
        if member:ensure_cycle(db,user,member)
        info=coverage(db,user,member,row['servico_id'])
        if usar is None and info and info['available']:raise HTTPException(409,'Este serviço está incluído no plano. Confirme a utilização ou escolha cobrar avulso.')
        if usar is False and info and info['available']:raise HTTPException(409,'Serviço já incluído no plano. Confirme a utilização para evitar uma cobrança duplicada.')
        if usar is not True:return
        p=perms(db,user)
        if not p['assinaturas_utilizar']:raise HTTPException(403,'Peça autorização para registrar utilizações de assinatura.')
        if row['status']!='agendado':raise HTTPException(409,'A utilização exige um atendimento agendado que será concluído agora.')
        if not info or not info['active']:raise HTTPException(409,'Assinatura sem ciclo pago e ativo. Confira o pagamento ou cobre o serviço avulso.')
        if not info['item']:raise HTTPException(409,'Serviço não incluído no plano. Cobre normalmente.')
        if not info['available']:raise HTTPException(409,'Limite atingido neste ciclo. Cobre o serviço separadamente.')
        rid=ident();cycle=info['cycle']
        insert(db,'mensal_utilizacoes',dict(id=rid,loja_id=user['loja_id'],assinante_id=member['id'],ciclo_id=cycle['id'],agendamento_id=row['id'],servico_id=row['servico_id'],servico_nome=row['servico_nome'],barbeiro_id=row['barbeiro_id'],barbeiro_nome=row['barbeiro_nome'],cliente_nome=row['cliente_nome'],plano_nome=cycle['plano_nome'],criado_em=now(),registrado_por=user['id'],estornada_em=None,estornado_por=None))
        audit(db,user,'utilizacao',{'utilizacao_id':rid,'agendamento_id':row['id'],'servico':row['servico_nome'],'barbeiro':row['barbeiro_nome']},member['id'])
    def estornar(db,user,row):
        lock(db,user['loja_id'])
        uses=list(db.execute('SELECT * FROM mensal_utilizacoes WHERE loja_id=? AND agendamento_id=? AND estornada_em IS NULL',(user['loja_id'],row['id'])))
        if uses and user['papel']!='dono':raise HTTPException(403,'Somente o dono pode corrigir uma utilização concluída.')
        for use in uses:
            db.execute('UPDATE mensal_utilizacoes SET estornada_em=?,estornado_por=? WHERE loja_id=? AND id=?',(now(),user['id'],user['loja_id'],use['id']))
            audit(db,user,'utilizacao_estornada',{'utilizacao_id':use['id'],'agendamento_id':row['id'],'novo_status':'não concluído'},use['assinante_id'])
    def enriquecer(db,user,rows):
        p=perms(db,user)
        members=[dict(r) for r in db.execute('SELECT * FROM mensal_assinantes WHERE loja_id=? ORDER BY criado_em,id',(user['loja_id'],))]
        mapping={}
        for member in members:
            if member['status']!='cancelada':mapping[member['cliente_telefone']]=member
        cycles={};counts={}
        for row in db.execute('SELECT * FROM mensal_ciclos WHERE loja_id=? ORDER BY inicio,id',(user['loja_id'],)):cycles[row['assinante_id']]=dict(row)
        for row in db.execute('SELECT * FROM mensal_ciclos WHERE loja_id=? AND inicio<=? AND fim>? ORDER BY inicio,id',(user['loja_id'],today().isoformat(),today().isoformat())):cycles[row['assinante_id']]=dict(row)
        due=[m for m in mapping.values() if m['status']=='ativa' and m['renovacao'] and cycles.get(m['id'],{}).get('status')=='pago' and cycles[m['id']]['fim']<=today().isoformat()]
        if due:
            lock(db,user['loja_id'])
            for member in due:cycles[member['id']]=ensure_cycle(db,user,member)
        for row in db.execute('SELECT ciclo_id,servico_id,COUNT(*) AS total FROM mensal_utilizacoes WHERE loja_id=? AND estornada_em IS NULL GROUP BY ciclo_id,servico_id',(user['loja_id'],)):counts[(row['ciclo_id'],row['servico_id'])]=row['total']
        used={r['agendamento_id'] for r in db.execute('SELECT agendamento_id FROM mensal_utilizacoes WHERE loja_id=? AND estornada_em IS NULL',(user['loja_id'],))}
        for row in rows:
            row['incluido_assinatura']=row['id'] in used
            member=mapping.get(telefone(row['cliente_telefone']))
            cycle=cycles.get(member['id']) if member else None
            if not member or not cycle:continue
            active=member['status']=='ativa' and cycle['status']=='pago' and cycle['inicio']<=today().isoformat()<cycle['fim']
            item=next((s for s in json.loads(cycle['servicos']) if s['servico_id']==row['servico_id']),None)
            count=counts.get((cycle['id'],row['servico_id']),0)
            available=active and item is not None and (item['quantidade'] is None or count<item['quantidade'])
            row['protecao_assinatura']=available
            if p['assinaturas_ver']:
                row['assinatura']={'id':member['id'],'plano':cycle['plano_nome'],'status':member['status'] if member['status']!='ativa' else 'ativa' if active else 'pagamento_atrasado' if cycle['status']=='pendente' and cycle['vencimento']<today().isoformat() else 'pendente' if cycle['status']!='pago' else 'vencida','vencimento':cycle['fim'],'ativo':active,'servico_incluido':item is not None,'disponivel':available,'utilizados':count,'quantidade':item['quantidade'] if item else 0,'pode_utilizar':p['assinaturas_utilizar']}
        return rows
    def financeiro(db,tenant,start,end):
        receipts=[dict(r) for r in db.execute("SELECT c.id,c.plano_nome,a.cliente_nome,c.total_centavos,c.pagamento,c.pago_em FROM mensal_ciclos c JOIN mensal_assinantes a ON a.loja_id=c.loja_id AND a.id=c.assinante_id WHERE c.loja_id=? AND c.status='pago' AND c.pago_em>=? AND c.pago_em<=? ORDER BY c.pago_em DESC,c.id DESC",(tenant,start[:10],end[:10]))]
        return {'total_centavos':sum(r['total_centavos'] for r in receipts),'receitas':receipts[:200]}
    @app.get('/api/mensalistas/dashboard')
    def dashboard(request:Request,inicio:date|None=None,fim:date|None=None):
        start=inicio or today().replace(day=1);end=fim or today()
        if end<start or (end-start).days>366:raise HTTPException(422,'Selecione até 366 dias.')
        with banco() as db:
            user,p=auth(db,request,'assinaturas_financeiro');lock(db,user['loja_id'])
            members=[dict(r) for r in db.execute('SELECT * FROM mensal_assinantes WHERE loja_id=?',(user['loja_id'],))]
            for member in members:ensure_cycle(db,user,member)
            current=[member_json(db,user,m,p) for m in members]
            receipts=financeiro(db,user['loja_id'],start.isoformat(),end.isoformat())
            paid=db.execute("SELECT COUNT(*) AS total FROM mensal_ciclos WHERE loja_id=? AND status='pago' AND pago_em>=? AND pago_em<=?",(user['loja_id'],start.isoformat(),end.isoformat())).fetchone()['total']
            pending=list(db.execute("SELECT vencimento FROM mensal_ciclos WHERE loja_id=? AND status='pendente' AND vencimento>=? AND vencimento<=?",(user['loja_id'],start.isoformat(),end.isoformat())))
            top=[dict(r) for r in db.execute("SELECT plano_nome,COUNT(*) AS total FROM mensal_ciclos WHERE loja_id=? AND status='pago' AND pago_em>=? AND pago_em<=? GROUP BY plano_nome ORDER BY total DESC LIMIT 20",(user['loja_id'],start.isoformat(),end.isoformat()))]
            services=[dict(r) for r in db.execute("SELECT servico_nome,COUNT(*) AS total FROM mensal_utilizacoes WHERE loja_id=? AND estornada_em IS NULL AND SUBSTR(criado_em,1,10)>=? AND SUBSTR(criado_em,1,10)<=? GROUP BY servico_nome ORDER BY total DESC LIMIT 30",(user['loja_id'],start.isoformat(),end.isoformat()))]
            return {'ativos':sum(m['ativo'] for m in current),'receita_centavos':receipts['total_centavos'],'pagas':paid,'pendentes':len(pending),'atrasadas':sum(r['vencimento']<today().isoformat() for r in pending),'cancelamentos':sum(m['status']=='cancelada' and start.isoformat()<=(m['cancelado_em'] or '')<=end.isoformat() for m in members),'novos':sum(start.isoformat()<=m['criado_em'][:10]<=end.isoformat() for m in members),'planos':top,'servicos':services,'receitas':receipts['receitas']}
    @app.get('/mensalistas.js')
    def script():return FileResponse(c['ROOT']/'mensalistas.js',media_type='application/javascript')
    @app.get('/mensalistas.css')
    def css():return FileResponse(c['ROOT']/'mensalistas.css',media_type='text/css')
    c['mensal_concluir']=consumir;c['mensal_estornar']=estornar;c['mensal_enriquecer']=enriquecer;c['mensal_financeiro']=financeiro
