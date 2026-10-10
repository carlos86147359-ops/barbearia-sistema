"""Ofertas por loja; preço e condições são congelados na reserva, nunca no navegador."""
import json
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

DDL = {
 'promocoes': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,nome TEXT NOT NULL,descricao TEXT NOT NULL,imagem_url TEXT NOT NULL,tipo TEXT NOT NULL,desconto_tipo TEXT NOT NULL,valor INTEGER NOT NULL,servicos TEXT NOT NULL,barbeiros TEXT NOT NULL,inicio TEXT NOT NULL,fim TEXT NOT NULL,dias TEXT NOT NULL,hora_inicio TEXT,hora_fim TEXT,limite INTEGER,status TEXT NOT NULL,criado_por TEXT NOT NULL,criado_em TEXT NOT NULL,atualizado_em TEXT NOT NULL,UNIQUE(loja_id,id)',
 'promocao_reservas': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,promocao_id TEXT NOT NULL,agendamento_id BIGINT NOT NULL UNIQUE,nome TEXT NOT NULL,original_centavos INTEGER NOT NULL,desconto_centavos INTEGER NOT NULL,total_centavos INTEGER NOT NULL,condicoes TEXT NOT NULL,criado_em TEXT NOT NULL,UNIQUE(loja_id,agendamento_id)',
 'promocao_pagamentos': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,agendamento_id BIGINT NOT NULL UNIQUE,valor_centavos INTEGER NOT NULL,forma TEXT NOT NULL,recebido_em TEXT NOT NULL,registrado_por TEXT NOT NULL',
 'promocao_eventos': 'id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,promocao_id TEXT NOT NULL,usuario_id TEXT NOT NULL,tipo TEXT NOT NULL,detalhes TEXT NOT NULL,criado_em TEXT NOT NULL'
}
TABLES={t:[p.split()[0] for p in ddl.split(',UNIQUE(',1)[0].split(',')] for t,ddl in DDL.items()}
INDEXES=['CREATE INDEX IF NOT EXISTS promocoes_loja ON promocoes(loja_id,status,inicio,fim)', 'CREATE INDEX IF NOT EXISTS promocao_uso ON promocao_reservas(loja_id,promocao_id)', 'CREATE INDEX IF NOT EXISTS promocao_receita ON promocao_pagamentos(loja_id,recebido_em)']
PERMISSION='promocoes_gerenciar'

class Oferta(BaseModel):
    model_config=ConfigDict(extra='forbid')
    nome:str=Field(min_length=2,max_length=100)
    descricao:str=Field(default='',max_length=500)
    imagem_url:str=Field(default='',max_length=1000)
    tipo:str=Field(default='personalizada',pattern='^(dia|semana|servico|horario|porcentagem|personalizada)$')
    desconto_tipo:str=Field(pattern='^(fixo|reais|percentual)$')
    valor:int=Field(ge=1,le=10000000,strict=True)
    servicos:list[str]=Field(min_length=1,max_length=100)
    barbeiros:list[str]=Field(default_factory=list,max_length=100)
    inicio:date
    fim:date
    dias:list[int]=Field(min_length=1,max_length=7)
    hora_inicio:str|None=None
    hora_fim:str|None=None
    limite:int|None=Field(default=None,ge=1,le=1000000,strict=True)
    status:str=Field(default='ativa',pattern='^(ativa|pausada|encerrada|arquivada)$')

class Estado(BaseModel):
    status:str=Field(pattern='^(ativa|pausada|encerrada|arquivada)$')

class Permissao(BaseModel):
    gerenciar:bool=Field(strict=True)

class Recebimento(BaseModel):
    forma:str=Field(pattern='^(pix|dinheiro|debito|credito|outro)$')
    valor_centavos:int=Field(ge=0,le=10000000,strict=True)

def centavos(v):return int((Decimal(str(v))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def preco(original,kind,value):
    total=value if kind=='fixo' else original-value if kind=='reais' else int((Decimal(original)*(100-value)/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    if not 0<=total<original:raise HTTPException(422,'O preço promocional precisa ser menor que o preço atual do serviço, sem ficar negativo.')
    return total

def instalar(app,c):
    banco=c['banco']
    now=lambda:datetime.now(c['BRASIL']).isoformat(timespec='seconds')
    ident=lambda:secrets.token_hex(16)
    def lock(db,shop):
        if c['DATABASE_URL']:c['travar'](db,shop,'')
        elif not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    with banco() as db:
        if c['DATABASE_URL']:db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        for t,ddl in DDL.items():db.execute('CREATE TABLE IF NOT EXISTS '+t+' ('+ddl+')')
        for sql in INDEXES:db.execute(sql)
    def insert(db,table,data):
        db.execute('INSERT INTO '+table+' ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values()))
    def audit(db,u,rid,kind,data):
        insert(db,'promocao_eventos',dict(id=ident(),loja_id=u['loja_id'],promocao_id=rid,usuario_id=u['id'],tipo=kind,detalhes=json.dumps(data,ensure_ascii=False),criado_em=now()))
    def allowed(db,u):
        if u['papel']=='dono':return True
        row=db.execute('SELECT permissoes FROM permissoes_caixa WHERE loja_id=? AND funcionario_id=?',(u['loja_id'],u['id'])).fetchone()
        return bool(row and json.loads(row['permissoes']).get(PERMISSION,False))
    def auth(db,request,change=False,owner=False):
        u=c['usuario'](request,db,change)
        if (owner and u['papel']!='dono') or not allowed(db,u):raise HTTPException(403,'Peça ao dono autorização para gerenciar promoções.')
        return u
    def get(db,shop,rid):
        row=db.execute('SELECT * FROM promocoes WHERE loja_id=? AND id=?',(shop,rid)).fetchone()
        if not row:raise HTTPException(404,'Promoção não encontrada.')
        return dict(row)
    def unpack(row):
        row=dict(row)
        for k in ('servicos','barbeiros','dias'):row[k]=json.loads(row[k])
        return row
    def count(db,shop,rid):
        return db.execute("SELECT COUNT(*) AS n FROM promocao_reservas p JOIN agendamentos a ON a.loja_id=p.loja_id AND a.id=p.agendamento_id WHERE p.loja_id=? AND p.promocao_id=? AND a.status!='cancelado'",(shop,rid)).fetchone()['n']
    def state(p):
        day=datetime.now(c['BRASIL']).date().isoformat()
        return p['status'] if p['status']!='ativa' else 'encerrada' if p['fim']<day else 'programada' if p['inicio']>day else 'ativa'
    def data(db,u,o):
        cfg=c['config_da_loja'](db,u['loja_id'])
        services={s['id']:s for s in cfg['servicos']};barbers={b['id'] for b in cfg['barbeiros']}
        if len(set(o.servicos))!=len(o.servicos) or set(o.servicos)-services.keys() or len(set(o.barbeiros))!=len(o.barbeiros) or set(o.barbeiros)-barbers:raise HTTPException(422,'Selecione serviços e profissionais desta barbearia, sem repetir.')
        if len(set(o.dias))!=len(o.dias) or any(type(d)!=int or d not in range(7) for d in o.dias):raise HTTPException(422,'Confira os dias da semana.')
        if o.fim<o.inicio or (o.fim-o.inicio).days>1095:raise HTTPException(422,'Confira as datas; use um período de até três anos.')
        if bool(o.hora_inicio)!=bool(o.hora_fim):raise HTTPException(422,'Preencha o início e o fim do horário promocional.')
        if o.hora_inicio and (not all(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',h) for h in (o.hora_inicio,o.hora_fim)) or o.hora_inicio>=o.hora_fim):raise HTTPException(422,'Confira a faixa de horários.')
        if o.desconto_tipo=='percentual' and o.valor>100:raise HTTPException(422,'O percentual deve ficar entre 1 e 100.')
        for sid in o.servicos:preco(centavos(services[sid]['preco']),o.desconto_tipo,o.valor)
        if len(o.nome.strip())<2:raise HTTPException(422,'Informe o nome da promoção.')
        if o.imagem_url:
            try:
                p=urlsplit(o.imagem_url)
                valid=p.scheme=='https' and bool(p.hostname) and not p.username and not p.password and p.port in (None,443)
            except ValueError:valid=False
            if not valid:raise HTTPException(422,'Use um link HTTPS válido para a imagem.')
        values=o.model_dump(mode='json');values['nome']=o.nome.strip()
        for k in ('servicos','barbeiros','dias'):values[k]=json.dumps(values[k])
        return values
    def validate(p,start,service,barber,duration,booking=True):
        if booking and (p['status']!='ativa' or not p['inicio']<=datetime.now(c['BRASIL']).date().isoformat()<=p['fim']):raise HTTPException(409,'Esta promoção não está disponível para novas reservas.')
        end=start+timedelta(minutes=duration)
        if not p['inicio']<=start.date().isoformat()<=p['fim'] or start.weekday() not in p['dias'] or service not in p['servicos'] or (p['barbeiros'] and barber not in p['barbeiros']) or (p['hora_inicio'] and (start.strftime('%H:%M')<p['hora_inicio'] or end.date()!=start.date() or end.strftime('%H:%M')>p['hora_fim'])):raise HTTPException(422,'Este serviço, profissional, dia ou horário não participa da promoção.')
    def quote(db,shop,rid,service,barber,start):
        p=unpack(get(db,shop,rid));validate(p,start,service['id'],barber['id'],service['duracao'])
        if p['limite'] is not None and count(db,shop,rid)>=p['limite']:raise HTTPException(409,'As vagas desta promoção esgotaram.')
        original=centavos(service['preco']);total=preco(original,p['desconto_tipo'],p['valor'])
        return dict(id=ident(),loja_id=shop,promocao_id=rid,nome=p['nome'],original_centavos=original,desconto_centavos=original-total,total_centavos=total,condicoes=json.dumps(p),criado_em=now())
    def save_booking(db,snapshot,aid):
        if snapshot:insert(db,'promocao_reservas',{**snapshot,'agendamento_id':aid})
    def move(db,row,start):
        p=db.execute('SELECT condicoes FROM promocao_reservas WHERE loja_id=? AND agendamento_id=?',(row['loja_id'],row['id'])).fetchone()
        if p:validate(json.loads(p['condicoes']),start,row['servico_id'],row['barbeiro_id'],row['duracao_minutos'],False)
    def transition(db,row,status):
        payment=db.execute('SELECT id FROM promocao_pagamentos WHERE loja_id=? AND agendamento_id=?',(row['loja_id'],row['id'])).fetchone()
        if payment and status!='concluido':raise HTTPException(409,'Este atendimento possui recebimento confirmado. Mantenha o histórico e fale com o dono para corrigir o financeiro.')
        if row['status']=='cancelado' and status!='cancelado':
            p=db.execute('SELECT promocao_id FROM promocao_reservas WHERE loja_id=? AND agendamento_id=?',(row['loja_id'],row['id'])).fetchone()
            if p:
                offer=get(db,row['loja_id'],p['promocao_id'])
                if offer['limite'] is not None and count(db,row['loja_id'],offer['id'])>=offer['limite']:raise HTTPException(409,'As vagas promocionais já foram ocupadas. Não é possível reabrir esta reserva.')
    def enrich(db,u,rows):
        promos={r['agendamento_id']:dict(r) for r in db.execute('SELECT agendamento_id,promocao_id,nome,original_centavos,desconto_centavos,total_centavos FROM promocao_reservas WHERE loja_id=?',(u['loja_id'],))}
        paid={r['agendamento_id']:dict(r) for r in db.execute('SELECT agendamento_id,valor_centavos,forma,recebido_em FROM promocao_pagamentos WHERE loja_id=?',(u['loja_id'],))}
        for row in rows:
            if row['id'] in promos:row['promocao']=promos[row['id']];row['promocao_pagamento']=paid.get(row['id'])
        return rows
    @app.get('/api/promocoes/acesso')
    def acesso(request:Request):
        with banco() as db:
            u=c['usuario'](request,db)
            return {'gerenciar':allowed(db,u),'dono':u['papel']=='dono'}
    @app.get('/api/promocoes/permissoes')
    def permissions(request:Request):
        with banco() as db:
            u=auth(db,request,owner=True);cfg=c['config_da_loja'](db,u['loja_id'])
            names={b['id']:b['nome'] for b in cfg['barbeiros']}
            return [dict(id=r['id'],nome=names[r['barbeiro_id']],gerenciar=allowed(db,dict(r,papel='barbeiro'))) for r in db.execute('SELECT * FROM funcionarios WHERE loja_id=? AND ativo=1',(u['loja_id'],)) if r['barbeiro_id'] in names]
    @app.put('/api/promocoes/permissoes/{uid}')
    def permission(uid:str,o:Permissao,request:Request):
        with banco() as db:
            u=auth(db,request,True,True);lock(db,u['loja_id'])
            if not db.execute('SELECT id FROM funcionarios WHERE loja_id=? AND id=? AND ativo=1',(u['loja_id'],uid)).fetchone():raise HTTPException(404,'Profissional não encontrado.')
            old=db.execute('SELECT permissoes FROM permissoes_caixa WHERE loja_id=? AND funcionario_id=?',(u['loja_id'],uid)).fetchone()
            p=json.loads(old['permissoes']) if old else {};p[PERMISSION]=o.gerenciar
            db.execute('INSERT INTO permissoes_caixa(id,loja_id,funcionario_id,permissoes,atualizado_por,atualizado_em) VALUES(?,?,?,?,?,?) ON CONFLICT(loja_id,funcionario_id) DO UPDATE SET permissoes=excluded.permissoes,atualizado_por=excluded.atualizado_por,atualizado_em=excluded.atualizado_em',(ident(),u['loja_id'],uid,json.dumps(p),u['id'],now()))
            audit(db,u,'','permissao',{'funcionario_id':uid,'gerenciar':o.gerenciar})
        return {'status':'ok'}
    @app.get('/api/promocoes')
    def listar(request:Request):
        with banco() as db:
            u=auth(db,request);result=[]
            for r in db.execute('SELECT * FROM promocoes WHERE loja_id=? ORDER BY criado_em DESC,id',(u['loja_id'],)):
                p=unpack(r);p.update(situacao=state(p),utilizacoes=count(db,u['loja_id'],p['id']));result.append(p)
            return result
    @app.post('/api/promocoes',status_code=201)
    def criar(o:Oferta,request:Request):
        with banco() as db:
            u=auth(db,request,True);lock(db,u['loja_id']);rid=ident();values=data(db,u,o)
            insert(db,'promocoes',dict(id=rid,loja_id=u['loja_id'],**values,criado_por=u['id'],criado_em=now(),atualizado_em=now()));audit(db,u,rid,'criada',values)
            return unpack(get(db,u['loja_id'],rid))
    @app.put('/api/promocoes/{rid}')
    def editar(rid:str,o:Oferta,request:Request):
        with banco() as db:
            u=auth(db,request,True);lock(db,u['loja_id']);old=get(db,u['loja_id'],rid);values=data(db,u,o)
            if o.limite is not None and o.limite<count(db,u['loja_id'],rid):raise HTTPException(422,'O limite não pode ser menor que as reservas já confirmadas.')
            values['atualizado_em']=now();db.execute('UPDATE promocoes SET '+','.join(k+'=?' for k in values)+' WHERE loja_id=? AND id=?',(*values.values(),u['loja_id'],rid));audit(db,u,rid,'editada',{'antes':old,'depois':values})
            return unpack(get(db,u['loja_id'],rid))
    @app.patch('/api/promocoes/{rid}')
    def status(rid:str,o:Estado,request:Request):
        with banco() as db:
            u=auth(db,request,True);lock(db,u['loja_id']);get(db,u['loja_id'],rid)
            db.execute('UPDATE promocoes SET status=?,atualizado_em=? WHERE loja_id=? AND id=?',(o.status,now(),u['loja_id'],rid));audit(db,u,rid,'status',o.model_dump())
        return {'status':o.status}
    @app.post('/api/promocoes/{rid}/duplicar',status_code=201)
    def duplicar(rid:str,request:Request):
        with banco() as db:
            u=auth(db,request,True);lock(db,u['loja_id']);old=get(db,u['loja_id'],rid);new=ident()
            old.update(id=new,nome=(old['nome']+' (cópia)')[:100],status='pausada',criado_por=u['id'],criado_em=now(),atualizado_em=now())
            insert(db,'promocoes',old);audit(db,u,new,'duplicada',{'origem':rid});return unpack(old)
    @app.get('/api/publico/{slug}/promocoes')
    def public(slug:str):
        with banco() as db:
            shop,cfg=c['loja_publica'](db,slug)
            if not c['assinatura'](db,shop['id'])['ativa']:return []
            services={s['id']:s for s in cfg['servicos']};barbers={b['id'] for b in cfg['barbeiros']};day=datetime.now(c['BRASIL']).date().isoformat();result=[]
            for r in db.execute("SELECT * FROM promocoes WHERE loja_id=? AND status='ativa' AND inicio<=? AND fim>=? ORDER BY fim,nome LIMIT 100",(shop['id'],day,day)):
                p=unpack(r)
                if p['limite'] is not None and count(db,shop['id'],p['id'])>=p['limite']:continue
                if p['barbeiros'] and not set(p['barbeiros'])&barbers:continue
                items=[]
                for sid in p['servicos']:
                    if sid not in services:continue
                    original=centavos(services[sid]['preco'])
                    try:total=preco(original,p['desconto_tipo'],p['valor'])
                    except HTTPException:continue
                    items.append({'id':sid,'nome':services[sid]['nome'],'original_centavos':original,'total_centavos':total,'desconto_centavos':original-total})
                if items:result.append({k:p[k] for k in ('id','nome','descricao','imagem_url','inicio','fim','dias','hora_inicio','hora_fim','barbeiros')}|{'servicos':items})
            return result
    @app.post('/api/promocoes/atendimentos/{aid}/pagamento')
    def receber(aid:int,o:Recebimento,request:Request):
        with banco() as db:
            u=auth(db,request,True,True);lock(db,u['loja_id'])
            a=db.execute('SELECT * FROM agendamentos WHERE loja_id=? AND id=?',(u['loja_id'],aid)).fetchone()
            p=db.execute('SELECT * FROM promocao_reservas WHERE loja_id=? AND agendamento_id=?',(u['loja_id'],aid)).fetchone()
            if not a or not p:raise HTTPException(404,'Atendimento promocional não encontrado.')
            if a['status']!='concluido':raise HTTPException(409,'Conclua o atendimento antes de registrar o pagamento.')
            if db.execute('SELECT id FROM mensal_utilizacoes WHERE loja_id=? AND agendamento_id=? AND estornada_em IS NULL',(u['loja_id'],aid)).fetchone():raise HTTPException(409,'Serviço incluído na assinatura: não cobre novamente.')
            if o.valor_centavos!=p['total_centavos']:raise HTTPException(422,'Confirme o valor promocional registrado na reserva.')
            existing=db.execute('SELECT * FROM promocao_pagamentos WHERE loja_id=? AND agendamento_id=?',(u['loja_id'],aid)).fetchone()
            if existing:
                if existing['forma']!=o.forma or existing['valor_centavos']!=o.valor_centavos:raise HTTPException(409,'O recebimento já foi confirmado com outros dados.')
                return {'status':'pago'}
            insert(db,'promocao_pagamentos',dict(id=ident(),loja_id=u['loja_id'],agendamento_id=aid,valor_centavos=o.valor_centavos,forma=o.forma,recebido_em=now(),registrado_por=u['id']));audit(db,u,p['promocao_id'],'pagamento',{'agendamento_id':aid,'valor_centavos':o.valor_centavos,'forma':o.forma})
        return {'status':'pago'}
    @app.get('/api/promocoes/relatorio')
    def report(request:Request,inicio:date|None=None,fim:date|None=None):
        start=inicio or datetime.now(c['BRASIL']).date().replace(day=1);end=fim or datetime.now(c['BRASIL']).date()
        if end<start or (end-start).days>366:raise HTTPException(422,'Selecione até 366 dias.')
        with banco() as db:
            u=auth(db,request,owner=True)
            rows=[dict(r) for r in db.execute('SELECT p.promocao_id,p.nome,p.original_centavos,p.desconto_centavos,p.total_centavos,a.id,a.status,a.servico_nome,a.inicio,a.cliente_nome FROM promocao_reservas p JOIN agendamentos a ON a.loja_id=p.loja_id AND a.id=p.agendamento_id WHERE p.loja_id=? AND SUBSTR(a.inicio,1,10)>=? AND SUBSTR(a.inicio,1,10)<=?',(u['loja_id'],start.isoformat(),end.isoformat()))]
            uses={r['agendamento_id'] for r in db.execute('SELECT agendamento_id FROM mensal_utilizacoes WHERE loja_id=? AND estornada_em IS NULL',(u['loja_id'],))}
            payments=[dict(r) for r in db.execute('SELECT p.agendamento_id,p.valor_centavos,p.forma,p.recebido_em,r.promocao_id,r.nome FROM promocao_pagamentos p JOIN promocao_reservas r ON r.loja_id=p.loja_id AND r.agendamento_id=p.agendamento_id WHERE p.loja_id=? AND SUBSTR(p.recebido_em,1,10)>=? AND SUBSTR(p.recebido_em,1,10)<=?',(u['loja_id'],start.isoformat(),end.isoformat()))]
            groups={};services={}
            for r in rows:
                g=groups.setdefault(r['promocao_id'],{'id':r['promocao_id'],'nome':r['nome'],'agendamentos':0,'concluidos':0,'cancelamentos':0,'receita_centavos':0,'descontos_centavos':0,'incluidos_assinatura':0});g['agendamentos']+=1;g['concluidos']+=r['status']=='concluido';g['cancelamentos']+=r['status']=='cancelado'
                if r['id'] in uses:g['incluidos_assinatura']+=1
                elif r['status']=='concluido':g['descontos_centavos']+=r['desconto_centavos']
                services[r['servico_nome']]=services.get(r['servico_nome'],0)+1
            for p in payments:
                g=groups.setdefault(p['promocao_id'],dict(id=p['promocao_id'],nome=p['nome'],agendamentos=0,concluidos=0,cancelamentos=0,receita_centavos=0,descontos_centavos=0,incluidos_assinatura=0));g['receita_centavos']+=p['valor_centavos']
            return {'promocoes':sorted(groups.values(),key=lambda g:-g['agendamentos']),'servicos':sorted([{'nome':k,'agendamentos':v} for k,v in services.items()],key=lambda s:-s['agendamentos']),'receita_centavos':sum(p['valor_centavos'] for p in payments),'recebimentos':payments}
    @app.post('/api/promocoes/imagem')
    async def imagem(request:Request):
        from imagens import pronto, preparar, enviar, MAX_UPLOAD
        with banco() as db:u=auth(db,request,True)
        if not pronto():raise HTTPException(503,'O armazenamento de imagens ainda não foi configurado.')
        c['limitar'](request,'imagens-'+u['loja_id'],12,3600)
        chunks=[];total=0
        async for chunk in request.stream():
            total+=len(chunk)
            if total>MAX_UPLOAD:raise HTTPException(413,'Escolha uma imagem menor.')
            chunks.append(chunk)
        processed=await run_in_threadpool(preparar,b''.join(chunks),'capa')
        url=await run_in_threadpool(enviar,processed,u['loja_id'],'promocao-'+ident())
        with banco() as db:auth(db,request,True)
        return {'url':url,'bytes':len(processed)}
    def asset_handler(asset):
        def serve():return FileResponse(c['ROOT']/asset,media_type='application/javascript' if asset.endswith('.js') else 'text/css')
        return serve
    for asset in ('promocoes.js','promocoes.css'):
        app.add_api_route('/'+asset,asset_handler(asset),methods=['GET'])
    c.update(promo_cotar=quote,promo_salvar=save_booking,promo_mover=move,promo_transicao=transition,promo_enriquecer=enrich)
