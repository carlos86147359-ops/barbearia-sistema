"""Agenda de barbearias com contas, configuração e isolamento por estabelecimento."""
import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get('DATABASE_URL')
DB_PATH = os.environ.get('BARBER_DB_PATH', str(ROOT / 'barbearia.db'))
CLOUD = bool(os.environ.get('RENDER'))
if CLOUD and not DATABASE_URL:
    raise RuntimeError('Configure DATABASE_URL com o banco Neon.')
BRASIL = timezone(timedelta(hours=-3))
COOKIE = 'barber_session'
SESSION_SECONDS = 60 * 60 * 12

class Postgres:
    def __init__(self, db): self.db = db
    def execute(self, sql, params=()): return self.db.execute(sql.replace('?', '%s'), params)

@contextmanager
def banco():
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15) as db:
            yield Postgres(db)
    else:
        db = sqlite3.connect(DB_PATH, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

def padrao():
    return {'nome':'Barbearia de demonstração', 'whatsapp':'', 'comissao':50,
            'barbeiros':[{'id':'carlos','nome':'Carlos Henrique'}, {'id':'marcos','nome':'Marcos Silva'}, {'id':'diego','nome':'Diego Barba'}],
            'servicos':[{'id':'corte','nome':'Corte Cabelo Fade','preco':65,'duracao':60}, {'id':'barba','nome':'Barboterapia Completa','preco':50,'duracao':60}, {'id':'combo','nome':'Combo Cabelo + Barba','preco':105,'duracao':120}],
            'dias':[0,1,2,3,4,5,6], 'periodos':[{'inicio':'09:00','fim':'12:00'}, {'inicio':'14:00','fim':'19:00'}], 'intervalo':30}

def iniciar():
    with banco() as db:
        db.execute('CREATE TABLE IF NOT EXISTS lojas (id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, configuracao TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS usuarios (id TEXT PRIMARY KEY, loja_id TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, senha TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS sessoes (token TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, csrf TEXT NOT NULL, expira BIGINT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS limites (chave TEXT PRIMARY KEY, janela BIGINT NOT NULL, quantidade INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS assinaturas (loja_id TEXT PRIMARY KEY, vencimento TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS cortesias (loja_id TEXT PRIMARY KEY, administrador_id TEXT NOT NULL, criado_em TEXT NOT NULL, motivo TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS pagamentos (id TEXT PRIMARY KEY, loja_id TEXT NOT NULL, referencia TEXT UNIQUE NOT NULL, valor_centavos INTEGER NOT NULL, confirmado_por TEXT NOT NULL, confirmado_em TEXT NOT NULL, vencimento TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS funcionarios (id TEXT PRIMARY KEY, loja_id TEXT NOT NULL, barbeiro_id TEXT NOT NULL, email TEXT UNIQUE NOT NULL, senha TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1, UNIQUE(loja_id,barbeiro_id))')
        db.execute('CREATE TABLE IF NOT EXISTS convites (token TEXT PRIMARY KEY, loja_id TEXT NOT NULL, barbeiro_id TEXT NOT NULL, email TEXT NOT NULL, expira BIGINT NOT NULL)')
        chave = 'BIGSERIAL PRIMARY KEY' if DATABASE_URL else 'INTEGER PRIMARY KEY'
        db.execute(f'''CREATE TABLE IF NOT EXISTS agendamentos (id {chave}, cliente_nome TEXT NOT NULL, cliente_telefone TEXT NOT NULL,
            barbeiro_nome TEXT NOT NULL, servico_nome TEXT NOT NULL, data_hora TEXT NOT NULL, preco REAL NOT NULL, criado_em TEXT,
            status TEXT NOT NULL DEFAULT 'agendado', inicio TEXT, duracao_minutos INTEGER NOT NULL DEFAULT 60,
            loja_id TEXT NOT NULL DEFAULT 'demo', barbeiro_id TEXT, servico_id TEXT, comissao_pct INTEGER NOT NULL DEFAULT 50)''')
        if DATABASE_URL:
            cols = {r['name'] for r in db.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='agendamentos'")}
        else: cols = {r['name'] for r in db.execute('PRAGMA table_info(agendamentos)')}
        for name, definition in [('status',"TEXT NOT NULL DEFAULT 'agendado'"), ('inicio','TEXT'), ('duracao_minutos','INTEGER NOT NULL DEFAULT 60'), ('loja_id',"TEXT NOT NULL DEFAULT 'demo'"), ('barbeiro_id','TEXT'), ('servico_id','TEXT'), ('comissao_pct','INTEGER NOT NULL DEFAULT 50')]:
            if name not in cols: db.execute(f'ALTER TABLE agendamentos ADD COLUMN {name} {definition}')
        demo = padrao()
        db.execute('INSERT INTO lojas (id,slug,configuracao) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING', ('demo','barbearia',json.dumps(demo)))
        for row in db.execute('SELECT * FROM agendamentos WHERE inicio IS NULL OR barbeiro_id IS NULL').fetchall():
            inicio = row['inicio'] or datetime.strptime(row['data_hora'],'%Y-%m-%d às %H:%M').isoformat(timespec='minutes')
            barber = next((b['id'] for b in demo['barbeiros'] if b['nome']==row['barbeiro_nome']), 'antigo-'+str(row['id']))
            service = next((s for s in demo['servicos'] if s['nome']==row['servico_nome']), None)
            db.execute('UPDATE agendamentos SET inicio=?, barbeiro_id=?, servico_id=? WHERE id=?', (inicio,barber,service['id'] if service else None,row['id']))
            if 'duracao_minutos' not in cols and service:
                db.execute('UPDATE agendamentos SET duracao_minutos=? WHERE id=?',(service['duracao'],row['id']))
        db.execute('CREATE INDEX IF NOT EXISTS agenda_loja_inicio ON agendamentos(loja_id,inicio)')

iniciar()
app = FastAPI(title='BarberSaaS', version='2.0.0', docs_url=None if CLOUD else '/docs', redoc_url=None)

@app.middleware('http')
async def protecoes(request: Request, call_next):
    # Os formulários legítimos usam a mesma origem. Evita alterações por outros sites.
    if request.method in ('POST','PATCH','PUT','DELETE'):
        origin = request.headers.get('origin')
        expected = os.environ.get('PUBLIC_BASE_URL', str(request.base_url).rstrip('/'))
        if origin and origin.rstrip('/') != expected:
            return Response('Origem inválida.', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    return response

def hash_senha(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex()
    return salt + ':' + digest

def confere_senha(password, stored):
    salt, digest = stored.split(':')
    actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex()
    return hmac.compare_digest(digest, actual)

def limite(db, request, action, maximum, seconds=900):
    ip = request.client.host if request.client else 'local'
    # Render fornece o IP do cliente no cabeçalho de proxy.
    if CLOUD: ip = request.headers.get('x-forwarded-for',ip).split(',')[0].strip()
    key = hashlib.sha256((action+':'+ip).encode()).hexdigest()
    window = int(time.time()) // seconds
    row = db.execute('''INSERT INTO limites(chave,janela,quantidade) VALUES (?,?,1)
        ON CONFLICT(chave) DO UPDATE SET quantidade=CASE WHEN limites.janela=excluded.janela THEN limites.quantidade+1 ELSE 1 END, janela=excluded.janela RETURNING quantidade''',(key,window)).fetchone()
    return row['quantidade'] > maximum

def limitar(request, action, maximum, seconds=900):
    with banco() as db: blocked = limite(db,request,action,maximum,seconds)
    if blocked: raise HTTPException(429,'Muitas tentativas. Aguarde alguns minutos.')

def usuario(request, db, change=False):
    raw = request.cookies.get(COOKIE,'')
    token = hashlib.sha256(raw.encode()).hexdigest()
    row = db.execute("""SELECT contas.*, sessoes.csrf FROM sessoes JOIN (
        SELECT id,loja_id,email,senha,'dono' AS papel,'' AS barbeiro_id FROM usuarios
        UNION ALL SELECT id,loja_id,email,senha,'barbeiro' AS papel,barbeiro_id FROM funcionarios WHERE ativo=1
        ) AS contas ON contas.id=sessoes.usuario_id WHERE sessoes.token=? AND sessoes.expira>?""",(token,int(time.time()))).fetchone()
    if row and row['papel']=='barbeiro' and not any(b['id']==row['barbeiro_id'] for b in config_da_loja(db,row['loja_id'])['barbeiros']):
        row=None
    if not row: raise HTTPException(401,'Entre na sua conta para acessar o painel.')
    if change and not hmac.compare_digest(row['csrf'],request.headers.get('x-csrf-token','')):
        raise HTTPException(403,'Atualize a página e tente novamente.')
    return dict(row)

def dono(request,db,change=False):
    user=usuario(request,db,change)
    if user['papel']!='dono': raise HTTPException(403,'Acesso exclusivo do dono da barbearia.')
    return user

def abrir_sessao(db, user_id, response):
    raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    db.execute('DELETE FROM sessoes WHERE expira<?',(int(time.time()),))
    db.execute('INSERT INTO sessoes(token,usuario_id,csrf,expira) VALUES(?,?,?,?)', (hashlib.sha256(raw.encode()).hexdigest(),user_id,csrf,int(time.time())+SESSION_SECONDS))
    response.set_cookie(COOKIE,raw,httponly=True,secure=CLOUD,samesite='lax',max_age=SESSION_SECONDS,path='/')
    return csrf

class Acesso(BaseModel):
    email: str = Field(min_length=3,max_length=150)
    senha: str = Field(min_length=10,max_length=128)

class Cadastro(Acesso):
    nome: str = Field(min_length=2,max_length=100)
    slug: str = Field(min_length=3,max_length=50)
    aceite_termos: bool = False

def email_valido(email):
    email=email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise HTTPException(422,'Informe um e-mail válido.')
    return email

@app.post('/api/cadastro',status_code=201)
def cadastrar(data: Cadastro, request: Request, response: Response, background: BackgroundTasks):
    if not data.aceite_termos: raise HTTPException(422,'Leia e aceite os termos de uso e a política de privacidade para criar a conta.')
    limitar(request,'cadastro',10,3600)
    email=email_valido(data.email)
    if eh_admin({'email':email}):
        raise HTTPException(409,'Esta conta está reservada para administração. Use Entrar.')
    slug=data.slug.strip().lower()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug): raise HTTPException(422,'Use letras minúsculas, números e hífens no endereço.')
    shop_id,user_id=secrets.token_hex(16),secrets.token_hex(16)
    config={'nome':data.nome.strip(),'whatsapp':'','comissao':50,'barbeiros':[],'servicos':[],'dias':[0,1,2,3,4,5],'periodos':[{'inicio':'09:00','fim':'19:00'}],'intervalo':30}
    if len(config['nome'])<2: raise HTTPException(422,'Informe o nome da barbearia.')
    with banco() as db:
        if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        else: db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT id FROM funcionarios WHERE email=?',(email,)).fetchone() or db.execute('SELECT id FROM usuarios WHERE email=?',(email,)).fetchone(): raise HTTPException(409,'Esse e-mail já possui conta. Use Entrar.')
        if db.execute('SELECT id FROM lojas WHERE slug=?',(slug,)).fetchone(): raise HTTPException(409,'Esse endereço já está em uso. Escolha outro.')
        db.execute('INSERT INTO lojas(id,slug,configuracao) VALUES(?,?,?)',(shop_id,slug,json.dumps(config)))
        db.execute('INSERT INTO usuarios(id,loja_id,email,senha) VALUES(?,?,?,?)',(user_id,shop_id,email,hash_senha(data.senha)))
        registrar_aceite(db,user_id)
        csrf=abrir_sessao(db,user_id,response)
    if email_pronto(): background.add_task(enviar_acao_email,user_id,email,'verificar')
    return {'csrf':csrf,'slug':slug}

@app.post('/api/login')
def login(data: Acesso, request: Request, response: Response):
    limitar(request,'login',20)
    email=email_valido(data.email)
    with banco() as db:
        row=db.execute('SELECT * FROM usuarios WHERE email=?',(email,)).fetchone()
        if not row:
            row=db.execute('SELECT * FROM funcionarios WHERE email=? AND ativo=1',(email,)).fetchone()
            if row and not any(b['id']==row['barbeiro_id'] for b in config_da_loja(db,row['loja_id'])['barbeiros']): row=None
        stored=row['senha'] if row else '00'*16+':'+'00'*32
        if not confere_senha(data.senha,stored) or not row: raise HTTPException(401,'E-mail ou senha incorretos.')
        csrf=abrir_sessao(db,row['id'],response)
    return {'csrf':csrf}

@app.get('/api/sessao')
def sessao(request: Request):
    with banco() as db:
        user=usuario(request,db)
        shop=db.execute('SELECT slug FROM lojas WHERE id=?',(user['loja_id'],)).fetchone()
    return {'email':user['email'],'csrf':user['csrf'],'slug':shop['slug'],'administrador':eh_admin(user),'papel':user['papel'],'barbeiro_id':user['barbeiro_id'],'email_confirmado':email_confirmado(user['id']),'email_disponivel':email_pronto()}

@app.post('/api/logout')
def logout(request: Request,response: Response):
    with banco() as db:
        usuario(request,db,True)
        db.execute('DELETE FROM sessoes WHERE token=?',(hashlib.sha256(request.cookies.get(COOKIE,'').encode()).hexdigest(),))
    response.delete_cookie(COOKIE,path='/')
    return {'status':'ok'}


def eh_admin(user):
    allowed={e.strip().lower() for e in os.environ.get('ADMIN_EMAILS','').split(',') if e.strip()}
    return user.get('papel','dono')=='dono' and user['email'].lower() in allowed

def administrador(request,db,change=False):
    user=dono(request,db,change)
    if not eh_admin(user): raise HTTPException(403,'Acesso exclusivo do administrador do sistema.')
    return user

def cobranca_ativa(): return os.environ.get('BILLING_ENABLED','').lower()=='true'

def assinatura(db,shop_id):
    courtesy=db.execute('SELECT criado_em,motivo FROM cortesias WHERE loja_id=?',(shop_id,)).fetchone()
    if courtesy:
        return {'ativa':True,'status':'cortesia','vencimento':None,'valor':0,'cobranca_ativa':cobranca_ativa(),'cortesia':True,'motivo':courtesy['motivo']}
    row=db.execute('SELECT vencimento FROM assinaturas WHERE loja_id=?',(shop_id,)).fetchone()
    due=row['vencimento'] if row else None
    active=bool(due and datetime.fromisoformat(due)>datetime.now(BRASIL))
    return {'ativa':active or not cobranca_ativa() or shop_id=='demo', 'status':'ativa' if active else 'vencida' if due else 'aguardando_pagamento', 'vencimento':due,'valor':90,'cobranca_ativa':cobranca_ativa()}

def exigir_assinatura(db,shop_id):
    if not assinatura(db,shop_id)['ativa']: raise HTTPException(403,'Esta agenda está temporariamente indisponível. Fale com a barbearia.')

@app.post('/api/gestao/minha-cortesia')
def minha_cortesia(request: Request):
    with banco() as db:
        user=administrador(request,db,True)
        db.execute('INSERT INTO cortesias(loja_id,administrador_id,criado_em,motivo) VALUES(?,?,?,?) ON CONFLICT(loja_id) DO NOTHING',(user['loja_id'],user['id'],datetime.now(BRASIL).isoformat(timespec='seconds'),'Conta do proprietário do SaaS'))
        return assinatura(db,user['loja_id'])

@app.get('/api/assinatura')
def minha_assinatura(request: Request):
    with banco() as db:
        user=dono(request,db)
        info=assinatura(db,user['loja_id'])
        payments=[dict(r) for r in db.execute('SELECT valor_centavos,confirmado_em,vencimento FROM pagamentos WHERE loja_id=? ORDER BY confirmado_em DESC',(user['loja_id'],)).fetchall()]
    return {**info,'pix_chave':os.environ.get('PIX_KEY',''),'pix_titular':os.environ.get('PIX_HOLDER',''),'whatsapp':os.environ.get('BILLING_WHATSAPP',''),'pagamentos':payments}

@app.get('/api/gestao/barbearias')
def gestao(request: Request):
    with banco() as db:
        administrador(request,db)
        rows=db.execute('SELECT lojas.*,usuarios.email FROM lojas JOIN usuarios ON usuarios.loja_id=lojas.id ORDER BY lojas.slug').fetchall()
        return [{'id':r['id'],'slug':r['slug'],'nome':json.loads(r['configuracao'])['nome'],'email':r['email'],**assinatura(db,r['id'])} for r in rows]

class ConfirmacaoPix(BaseModel):
    referencia: str = Field(min_length=6,max_length=100)

@app.post('/api/gestao/barbearias/{shop_id}/pagamentos',status_code=201)
def confirmar_pix(shop_id: str,data: ConfirmacaoPix,request: Request):
    reference=data.referencia.strip().upper()
    if len(reference)<6: raise HTTPException(422,'Informe o identificador do Pix conferido no banco.')
    now=datetime.now(BRASIL)
    with banco() as db:
        user=administrador(request,db,True)
        if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(?)',(7821602,))
        else: db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT id FROM usuarios WHERE loja_id=?',(shop_id,)).fetchone(): raise HTTPException(404,'Barbearia não encontrada.')
        if db.execute('SELECT id FROM pagamentos WHERE referencia=?',(reference,)).fetchone(): raise HTTPException(409,'Este Pix já foi confirmado. Nenhum mês foi acrescentado.')
        previous=assinatura(db,shop_id)['vencimento']
        start=max(now,datetime.fromisoformat(previous)) if previous else now
        month=start.month%12+1
        year=start.year+(start.month==12)
        due=start.replace(year=year,month=month,day=min(start.day,calendar.monthrange(year,month)[1])).isoformat(timespec='seconds')
        db.execute('INSERT INTO pagamentos(id,loja_id,referencia,valor_centavos,confirmado_por,confirmado_em,vencimento) VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(16),shop_id,reference,9000,user['id'],now.isoformat(timespec='seconds'),due))
        db.execute('INSERT INTO assinaturas(loja_id,vencimento) VALUES(?,?) ON CONFLICT(loja_id) DO UPDATE SET vencimento=excluded.vencimento',(shop_id,due))
    return {'vencimento':due,'valor':90}


@app.get('/api/equipe')
def equipe(request: Request):
    with banco() as db:
        user=dono(request,db)
        accounts={r['barbeiro_id']:dict(r) for r in db.execute('SELECT barbeiro_id,email,ativo FROM funcionarios WHERE loja_id=?',(user['loja_id'],)).fetchall()}
        invites={r['barbeiro_id']:dict(r) for r in db.execute('SELECT barbeiro_id,email FROM convites WHERE loja_id=? AND expira>?',(user['loja_id'],int(time.time()))).fetchall()}
        return [{'id':b['id'],'nome':b['nome'],'conta':accounts.get(b['id']),'convite':invites.get(b['id'])} for b in config_da_loja(db,user['loja_id'])['barbeiros']]

class ConviteNovo(BaseModel):
    email: str = Field(min_length=3,max_length=150)

@app.post('/api/equipe/{barber_id}/convite',status_code=201)
def convidar(barber_id: str,data: ConviteNovo,request: Request):
    email=email_valido(data.email)
    if eh_admin({'email':email}): raise HTTPException(409,'Use o e-mail pessoal do profissional, não a conta administrativa.')
    raw=secrets.token_urlsafe(32)
    with banco() as db:
        if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        else: db.execute('BEGIN IMMEDIATE')
        user=dono(request,db,True)
        if not any(b['id']==barber_id for b in config_da_loja(db,user['loja_id'])['barbeiros']): raise HTTPException(404,'Salve o profissional nas configurações antes de convidar.')
        if db.execute('SELECT id FROM usuarios WHERE email=?',(email,)).fetchone(): raise HTTPException(409,'Esse e-mail já pertence a um dono de barbearia.')
        row=db.execute('SELECT * FROM funcionarios WHERE email=?',(email,)).fetchone()
        if row and (row['loja_id']!=user['loja_id'] or row['barbeiro_id']!=barber_id): raise HTTPException(409,'Esse e-mail já possui outro acesso.')
        db.execute('DELETE FROM convites WHERE loja_id=? AND barbeiro_id=?',(user['loja_id'],barber_id))
        db.execute('INSERT INTO convites(token,loja_id,barbeiro_id,email,expira) VALUES(?,?,?,?,?)',(hashlib.sha256(raw.encode()).hexdigest(),user['loja_id'],barber_id,email,int(time.time())+7*86400))
    return {'link':'/convite#'+raw,'validade_dias':7}

@app.post('/api/equipe/{barber_id}/revogar')
def revogar(barber_id: str,request: Request):
    with banco() as db:
        if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        else: db.execute('BEGIN IMMEDIATE')
        user=dono(request,db,True)
        row=db.execute('SELECT id FROM funcionarios WHERE loja_id=? AND barbeiro_id=?',(user['loja_id'],barber_id)).fetchone()
        if row:
            db.execute('UPDATE funcionarios SET ativo=0 WHERE id=?',(row['id'],))
            db.execute('DELETE FROM sessoes WHERE usuario_id=?',(row['id'],))
        db.execute('DELETE FROM convites WHERE loja_id=? AND barbeiro_id=?',(user['loja_id'],barber_id))
    return {'status':'revogado'}

class TokenConvite(BaseModel):
    token: str = Field(min_length=20,max_length=100)

def convite_valido(db,token):
    row=db.execute('SELECT * FROM convites WHERE token=? AND expira>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    if not row: raise HTTPException(410,'Convite inválido, expirado ou já utilizado. Peça outro ao dono.')
    config=config_da_loja(db,row['loja_id'])
    barber=next((b for b in config['barbeiros'] if b['id']==row['barbeiro_id']),None)
    if not barber: raise HTTPException(410,'Este profissional não está mais cadastrado.')
    return row,config,barber

@app.post('/api/convite/info')
def convite_info(data: TokenConvite,request: Request):
    limitar(request,'convite-info',60)
    with banco() as db: row,config,barber=convite_valido(db,data.token)
    return {'email':row['email'],'barbearia':config['nome'],'profissional':barber['nome']}

class AceitarConvite(TokenConvite):
    senha: str = Field(min_length=10,max_length=128)

@app.post('/api/convite/aceitar',status_code=201)
def aceitar_convite(data: AceitarConvite,request: Request,response: Response):
    limitar(request,'convite-aceitar',20)
    with banco() as db:
        if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        else: db.execute('BEGIN IMMEDIATE')
        row,config,barber=convite_valido(db,data.token)
        if eh_admin({'email':row['email']}) or db.execute('SELECT id FROM usuarios WHERE email=?',(row['email'],)).fetchone(): raise HTTPException(409,'Esse e-mail já está em uso. Peça outro convite ao dono.')
        other=db.execute('SELECT * FROM funcionarios WHERE email=?',(row['email'],)).fetchone()
        if other and (other['loja_id']!=row['loja_id'] or other['barbeiro_id']!=row['barbeiro_id']): raise HTTPException(409,'Esse e-mail já possui outro acesso.')
        existing=db.execute('SELECT id FROM funcionarios WHERE loja_id=? AND barbeiro_id=?',(row['loja_id'],row['barbeiro_id'])).fetchone()
        uid=existing['id'] if existing else secrets.token_hex(16)
        if existing:
            db.execute('DELETE FROM sessoes WHERE usuario_id=?',(uid,))
            db.execute('UPDATE funcionarios SET email=?,senha=?,ativo=1 WHERE id=?',(row['email'],hash_senha(data.senha),uid))
        else: db.execute('INSERT INTO funcionarios(id,loja_id,barbeiro_id,email,senha,ativo) VALUES(?,?,?,?,?,1)',(uid,row['loja_id'],row['barbeiro_id'],row['email'],hash_senha(data.senha)))
        db.execute('DELETE FROM convites WHERE token=?',(row['token'],))
        csrf=abrir_sessao(db,uid,response)
    return {'csrf':csrf}

@app.get('/api/meu-perfil')
def meu_perfil(request: Request):
    with banco() as db:
        user=usuario(request,db)
        config=config_da_loja(db,user['loja_id'])
        barber=next((b for b in config['barbeiros'] if b['id']==user['barbeiro_id']),None)
        return {'barbearia':config['nome'],'profissional':barber['nome'] if barber else '', 'agenda_liberada':assinatura(db,user['loja_id'])['ativa']}

class Identificado(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    nome: str = Field(min_length=2,max_length=100)

class Barbeiro(Identificado):
    whatsapp: str = Field(default='',max_length=25)

class Servico(Identificado):
    preco: Decimal = Field(gt=0,le=10000,max_digits=7,decimal_places=2)
    duracao: int = Field(ge=5,le=480)

class Periodo(BaseModel):
    inicio: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    fim: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

class Configuracao(BaseModel):
    nome: str = Field(min_length=2,max_length=100)
    whatsapp: str = Field(max_length=25)
    comissao: int = Field(ge=0,le=100)
    barbeiros: list[Barbeiro] = Field(max_length=30)
    servicos: list[Servico] = Field(max_length=60)
    dias: list[int] = Field(max_length=7)
    periodos: list[Periodo] = Field(max_length=4)
    intervalo: int = Field(ge=5,le=120)
    logo_url: str = Field(default='',max_length=1000)
    capa_url: str = Field(default='',max_length=1000)
    cor_principal: str = Field(default='#dfa94d',pattern=r'^#[0-9a-fA-F]{6}$')
    endereco: str = Field(default='',max_length=250)
    instagram: str = Field(default='',max_length=250)
    localizacao_url: str = Field(default='',max_length=1000)

def config_da_loja(db,shop_id):
    return json.loads(db.execute('SELECT configuracao FROM lojas WHERE id=?',(shop_id,)).fetchone()['configuracao'])

@app.get('/api/configuracao')
def ler_config(request: Request):
    with banco() as db: return config_da_loja(db,dono(request,db)['loja_id'])

@app.put('/api/configuracao')
def salvar_config(data: Configuracao,request: Request):
    config=json.loads(data.model_dump_json())
    for field in ('logo_url','capa_url','instagram'):
        value=config[field].strip()
        if value:
            try:
                parsed=urlsplit(value)
                valid=parsed.scheme=='https' and bool(parsed.hostname) and not parsed.username and not parsed.password and not any(c.isspace() for c in value)
                if field=='instagram': valid=valid and parsed.hostname in ('instagram.com','www.instagram.com')
            except ValueError: valid=False
            if not valid: raise HTTPException(422,'Use links HTTPS válidos para logo, capa e perfil do Instagram.')
        config[field]=value
    value=config['localizacao_url'].strip()
    if value:
        try:
            parsed=urlsplit(value)
            host=(parsed.hostname or '').lower()
            google=host in ('google.com','www.google.com','google.com.br','www.google.com.br') and (parsed.path=='/maps' or parsed.path.startswith('/maps/'))
            maps=host=='maps.google.com' or (host=='maps.app.goo.gl' and len(parsed.path)>1) or (host=='goo.gl' and parsed.path.startswith('/maps/'))
            valid=parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and not any(c.isspace() for c in value) and (google or maps)
        except ValueError: valid=False
        if not valid: raise HTTPException(422,'Use um link HTTPS do Google Maps. No Maps, toque em Compartilhar e copie o link.')
    config['localizacao_url']=value
    config['endereco']=config['endereco'].strip()
    for barber in config['barbeiros']:
        raw=barber['whatsapp'].strip()
        number=re.sub(r'\D','',raw)
        if raw and not (len(number) in (10,11) or (number.startswith('55') and len(number) in (12,13))):
            raise HTTPException(422,f"Informe o WhatsApp de {barber['nome']} com DDD ou deixe em branco.")
        barber['whatsapp']=number
    config['nome']=config['nome'].strip()
    raw_store_phone=config['whatsapp'].strip()
    config['whatsapp']=re.sub(r'\D','',raw_store_phone)
    store_phone=config['whatsapp']
    if len(config['nome'])<2 or (raw_store_phone and not (len(store_phone) in (10,11) or (store_phone.startswith('55') and len(store_phone) in (12,13)))):
        raise HTTPException(422,'Confira o nome da barbearia e o WhatsApp com DDD.')
    if not config['dias'] or any(d not in range(7) for d in config['dias']) or len(set(config['dias'])) != len(config['dias']): raise HTTPException(422,'Escolha os dias de funcionamento.')
    for kind in ('barbeiros','servicos'):
        values=config[kind]
        if len({v['id'] for v in values}) != len(values) or any(len(v['nome'].strip())<2 for v in values): raise HTTPException(422,'Confira os nomes e os itens duplicados.')
        for v in values: v['nome']=v['nome'].strip()
    periods=sorted(config['periodos'],key=lambda p:p['inicio'])
    if not periods or any(p['inicio']>=p['fim'] for p in periods) or any(a['fim']>b['inicio'] for a,b in zip(periods,periods[1:])): raise HTTPException(422,'Os períodos devem ter início antes do fim e não podem se sobrepor.')
    config['periodos']=periods
    with banco() as db:
        if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        else: db.execute('BEGIN IMMEDIATE')
        user=dono(request,db,True)
        kept={b['id'] for b in config['barbeiros']}
        old=config_da_loja(db,user['loja_id'])
        # Clientes antigos da API continuam preservando a identidade já configurada.
        for field in ('logo_url','capa_url','cor_principal','endereco','instagram','localizacao_url'):
            if field not in data.model_fields_set and field in old: config[field]=old[field]
        for b in old['barbeiros']:
            if b['id'] not in kept:
                staff=db.execute('SELECT id FROM funcionarios WHERE loja_id=? AND barbeiro_id=?',(user['loja_id'],b['id'])).fetchone()
                if staff:
                    db.execute('UPDATE funcionarios SET ativo=0 WHERE id=?',(staff['id'],))
                    db.execute('DELETE FROM sessoes WHERE usuario_id=?',(staff['id'],))
                db.execute('DELETE FROM convites WHERE loja_id=? AND barbeiro_id=?',(user['loja_id'],b['id']))
        db.execute('UPDATE lojas SET configuracao=? WHERE id=?',(json.dumps(config),user['loja_id']))
    return config

def loja_publica(db,slug):
    shop=db.execute('SELECT * FROM lojas WHERE slug=?',(slug,)).fetchone()
    if not shop: raise HTTPException(404,'Barbearia não encontrada.')
    return shop,json.loads(shop['configuracao'])

@app.get('/api/publico/{slug}/configuracao')
def publico(slug: str):
    with banco() as db:
        shop,config=loja_publica(db,slug)
        active=assinatura(db,shop['id'])['ativa']
    return {**{k:v for k,v in config.items() if k!='comissao'},'agenda_liberada':active}

def escolher(config,barber_id,service_id):
    barber=next((b for b in config['barbeiros'] if b['id']==barber_id),None)
    service=next((s for s in config['servicos'] if s['id']==service_id),None)
    if not barber or not service: raise HTTPException(422,'Escolha um profissional e um serviço disponíveis.')
    return barber,service

def inicio_valido(config,day,hour,duration):
    try: start=datetime.fromisoformat(f'{day.isoformat()}T{hour}')
    except ValueError: raise HTTPException(422,'Horário inválido.')
    if not re.fullmatch(r'\d{2}:\d{2}',hour): raise HTTPException(422,'Horário inválido.')
    if day.weekday() not in config['dias']: raise HTTPException(422,'A barbearia não abre nesse dia.')
    end=start+timedelta(minutes=duration)
    valid=False
    for p in config['periodos']:
        a=datetime.fromisoformat(f"{day}T{p['inicio']}")
        b=datetime.fromisoformat(f"{day}T{p['fim']}")
        offset=int((start-a).total_seconds()//60)
        if a<=start and end<=b and offset%config['intervalo']==0: valid=True
    if not valid: raise HTTPException(422,'O serviço não cabe nesse horário de funcionamento.')
    if start.replace(tzinfo=BRASIL)<=datetime.now(BRASIL): raise HTTPException(422,'Escolha um horário futuro.')
    if day>datetime.now(BRASIL).date()+timedelta(days=180): raise HTTPException(422,'Agende com no máximo 180 dias de antecedência.')
    return start

def ocupado(db,shop_id,barber_id,start,duration,ignore=0):
    end=start+timedelta(minutes=duration)
    rows=db.execute("SELECT inicio,duracao_minutos FROM agendamentos WHERE loja_id=? AND barbeiro_id=? AND status!='cancelado' AND inicio LIKE ? AND id!=?",(shop_id,barber_id,start.date().isoformat()+'%',ignore))
    return bloqueado(db,shop_id,barber_id,start,end) or any(start<datetime.fromisoformat(r['inicio'])+timedelta(minutes=r['duracao_minutos']) and datetime.fromisoformat(r['inicio'])<end for r in rows)

@app.get('/api/publico/{slug}/disponibilidade')
def disponibilidade(slug: str,data: date,barbeiro_id: str,servico_id: str):
    with banco() as db:
        shop,config=loja_publica(db,slug)
        exigir_assinatura(db,shop['id'])
        barber,service=escolher(config,barbeiro_id,servico_id)
        hours=[]
        for p in config['periodos']:
            cur=datetime.fromisoformat(f"{data}T{p['inicio']}")
            end=datetime.fromisoformat(f"{data}T{p['fim']}")
            while cur<end:
                hour=cur.strftime('%H:%M')
                try: start=inicio_valido(config,data,hour,service['duracao'])
                except HTTPException: cur+=timedelta(minutes=config['intervalo']); continue
                if not ocupado(db,shop['id'],barber['id'],start,service['duracao']): hours.append(hour)
                cur+=timedelta(minutes=config['intervalo'])
    return {'horarios':hours}

class Reserva(BaseModel):
    cliente_nome: str = Field(min_length=2,max_length=100)
    cliente_telefone: str = Field(min_length=10,max_length=25)
    barbeiro_id: str
    servico_id: str
    data: date
    horario: str

def travar(db,shop_id,barber_id):
    if DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(hashtext(?))',('agenda:'+shop_id,))
    else: db.execute('BEGIN IMMEDIATE')

@app.post('/api/publico/{slug}/agendamentos',status_code=201)
def criar(slug: str,data: Reserva,request: Request):
    limitar(request,'agendar',30)
    name=data.cliente_nome.strip()
    phone=re.sub(r'\D','',data.cliente_telefone)
    if phone.startswith('55') and len(phone) in (12,13): phone=phone[2:]
    if len(name)<2 or len(phone) not in (10,11): raise HTTPException(422,'Informe seu nome e WhatsApp com DDD.')
    with banco() as db:
        # Em SQLite o bloqueio deve vir antes da leitura; no PostgreSQL isolamos por loja e profissional.
        if not DATABASE_URL: db.execute('BEGIN IMMEDIATE')
        shop,config=loja_publica(db,slug)
        if shop['id']=='demo': raise HTTPException(400,'Esta é uma demonstração. Crie uma conta para abrir sua própria agenda.')
        exigir_assinatura(db,shop['id'])
        barber,service=escolher(config,data.barbeiro_id,data.servico_id)
        if DATABASE_URL: travar(db,shop['id'],barber['id'])
        start=inicio_valido(config,data.data,data.horario,service['duracao'])
        if ocupado(db,shop['id'],barber['id'],start,service['duracao']): raise HTTPException(409,'Esse horário acabou de ser reservado. Escolha outro.')
        sql='''INSERT INTO agendamentos(cliente_nome,cliente_telefone,barbeiro_nome,servico_nome,data_hora,preco,criado_em,status,inicio,duracao_minutos,loja_id,barbeiro_id,servico_id,comissao_pct)
            VALUES(?,?,?,?,?,?,?,'agendado',?,?,?,?,?,?)'''
        if DATABASE_URL: sql+=' RETURNING id'
        cur=db.execute(sql,(name,phone,barber['nome'],service['nome'],f'{data.data} às {data.horario}',float(service['preco']),datetime.now(BRASIL).isoformat(),start.isoformat(timespec='minutes'),service['duracao'],shop['id'],barber['id'],service['id'],config['comissao']))
        reservation_id=cur.fetchone()['id'] if DATABASE_URL else cur.lastrowid
        management=criar_link_cliente(db,reservation_id)
    message=f"Olá! Agendei {service['nome']} com {barber['nome']} em {config['nome']}, para {data.data} às {data.horario}. Meu nome é {name}. Reserva #{reservation_id}."
    professional_phone=barber.get('whatsapp','')
    store_phone=professional_phone or config['whatsapp']
    if len(store_phone) in (10,11): store_phone='55'+store_phone
    return {'agendamento_id':reservation_id,'preco':service['preco'],'link_gerenciar':management,'whatsapp_destinatario':'barbeiro' if professional_phone else 'loja' if store_phone else None,'link_whatsapp':f'https://wa.me/{store_phone}?text={quote(message)}' if store_phone else None}

@app.get('/api/agendamentos')
def agenda(request: Request):
    with banco() as db:
        user=usuario(request,db)
        if user['papel']=='barbeiro':
            return [dict(r) for r in db.execute('SELECT * FROM agendamentos WHERE loja_id=? AND barbeiro_id=? ORDER BY inicio,id',(user['loja_id'],user['barbeiro_id']))]
        return [dict(r) for r in db.execute('SELECT * FROM agendamentos WHERE loja_id=? ORDER BY inicio,id',(user['loja_id'],))]

class Situacao(BaseModel):
    status: str

@app.patch('/api/agendamentos/{reservation_id}')
def alterar(reservation_id: int,data: Situacao,request: Request):
    if data.status not in ('agendado','concluido','cancelado'): raise HTTPException(422,'Situação inválida.')
    with banco() as db:
        if not DATABASE_URL: db.execute('BEGIN IMMEDIATE')
        user=usuario(request,db,True)
        row=db.execute('SELECT * FROM agendamentos WHERE id=? AND loja_id=?',(reservation_id,user['loja_id'])).fetchone()
        if not row or (user['papel']=='barbeiro' and row['barbeiro_id']!=user['barbeiro_id']): raise HTTPException(404,'Agendamento não encontrado.')
        if user['papel']=='barbeiro' and (data.status!='concluido' or row['status']!='agendado'): raise HTTPException(403,'Você pode concluir seus atendimentos agendados. Peça ao dono para cancelar ou reabrir.')
        if DATABASE_URL:
            travar(db,user['loja_id'],row['barbeiro_id'])
            row=db.execute('SELECT * FROM agendamentos WHERE id=? AND loja_id=?',(reservation_id,user['loja_id'])).fetchone()
            if user['papel']=='barbeiro' and row['status']!='agendado': raise HTTPException(409,'A situação deste atendimento mudou. Atualize sua agenda.')
        if row['status']=='cancelado' and data.status!='cancelado' and ocupado(db,user['loja_id'],row['barbeiro_id'],datetime.fromisoformat(row['inicio']),row['duracao_minutos'],reservation_id): raise HTTPException(409,'Esse horário já foi ocupado por outra reserva.')
        db.execute('UPDATE agendamentos SET status=? WHERE id=? AND loja_id=?',(data.status,reservation_id,user['loja_id']))
    return {'status':data.status}

@app.get('/health')
def health():
    with banco() as db: db.execute('SELECT 1')
    return {'status':'ok','banco':'postgresql' if DATABASE_URL else 'sqlite'}

@app.head('/')
def head(): return None

@app.get('/design-system.css')
def design_css(): return FileResponse(ROOT/'design-system.css',media_type='text/css')

@app.get('/design-system.js')
def design_js(): return FileResponse(ROOT/'design-system.js',media_type='application/javascript')

@app.get('/image-upload.js')
def image_upload_js(): return FileResponse(ROOT/'image-upload.js',media_type='application/javascript')

@app.get('/agenda-live.js')
def agenda_live_script(): return FileResponse(ROOT/'agenda-live.js',media_type='application/javascript')

@app.get('/',response_class=HTMLResponse)
@app.get('/recuperar-senha',response_class=HTMLResponse)
@app.get('/redefinir-senha',response_class=HTMLResponse)
@app.get('/confirmar-email',response_class=HTMLResponse)
@app.get('/minha-reserva',response_class=HTMLResponse)
@app.get('/termos',response_class=HTMLResponse)
@app.get('/privacidade',response_class=HTMLResponse)
@app.get('/suporte',response_class=HTMLResponse)
@app.get('/convite',response_class=HTMLResponse)
@app.get('/gestao',response_class=HTMLResponse)
@app.get('/painel',response_class=HTMLResponse)
@app.get('/entrar',response_class=HTMLResponse)
@app.get('/cadastro',response_class=HTMLResponse)
@app.get('/admin',response_class=HTMLResponse)
@app.get('/barbeiro',response_class=HTMLResponse)
@app.get('/b/{slug}',response_class=HTMLResponse)
def pagina(): return (ROOT/'index.html').read_text(encoding='utf-8')

from pwa import instalar as instalar_pwa
instalar_pwa(app, ROOT)

# Os recursos adicionais usam as mesmas sessões e transações do núcleo.
import importlib.util as _importlib
_spec=_importlib.spec_from_file_location("recursos_barber",ROOT / "recursos.py")
_recursos=_importlib.module_from_spec(_spec)
_spec.loader.exec_module(_recursos)
_recursos.instalar(app,globals())

from imagens import instalar as instalar_imagens
instalar_imagens(app,globals())
