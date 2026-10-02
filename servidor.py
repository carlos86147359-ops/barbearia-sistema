"""BarberSaaS: agenda local. Execute python servidor.py."""
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone, date
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('BARBER_DB_PATH', str(ROOT / 'barbearia.db')))
DATABASE_URL = os.environ.get('DATABASE_URL')
if os.environ.get('RENDER') and not DATABASE_URL:
    raise RuntimeError('Configure DATABASE_URL com o banco Neon antes de iniciar no Render.')
BRASIL = timezone(timedelta(hours=-3))
SERVICOS = {'Corte Cabelo Fade': (65, 60), 'Barboterapia Completa': (50, 60), 'Combo Cabelo + Barba': (105, 120)}
BARBEIROS = ['Carlos Henrique', 'Marcos Silva', 'Diego Barba']
HORARIOS = ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00', '17:00', '18:00']

@contextmanager
def conectar():
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15) as db:
            yield BancoPostgres(db)
        return
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

class BancoPostgres:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, parametros=()):
        return self.db.execute(sql.replace('?', '%s'), parametros)

def inicializar():
    with conectar() as db:
        chave = 'BIGSERIAL PRIMARY KEY' if DATABASE_URL else 'INTEGER PRIMARY KEY'
        db.execute(f'''CREATE TABLE IF NOT EXISTS agendamentos (
            id {chave}, cliente_nome TEXT NOT NULL,
            cliente_telefone TEXT NOT NULL, barbeiro_nome TEXT NOT NULL,
            servico_nome TEXT NOT NULL, data_hora TEXT NOT NULL,
            preco REAL NOT NULL, criado_em TEXT,
            status TEXT NOT NULL DEFAULT 'agendado', inicio TEXT,
            duracao_minutos INTEGER NOT NULL DEFAULT 60)''')
        if DATABASE_URL:
            colunas = {r['name'] for r in db.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'agendamentos'")}
        else:
            colunas = {r['name'] for r in db.execute('PRAGMA table_info(agendamentos)')}
        for nome, definicao in [('status', "TEXT NOT NULL DEFAULT 'agendado'"), ('inicio', 'TEXT'), ('duracao_minutos', 'INTEGER NOT NULL DEFAULT 60')]:
            if nome not in colunas:
                db.execute(f'ALTER TABLE agendamentos ADD COLUMN {nome} {definicao}')
        for row in db.execute('SELECT * FROM agendamentos WHERE inicio IS NULL').fetchall():
            try:
                inicio = datetime.strptime(row['data_hora'], '%Y-%m-%d às %H:%M').isoformat(timespec='minutes')
            except ValueError:
                raise RuntimeError(f"Agendamento antigo {row['id']} tem data inválida; revise antes de iniciar.")
            duracao = SERVICOS.get(row['servico_nome'], (0, 60))[1]
            db.execute('UPDATE agendamentos SET inicio=?, duracao_minutos=? WHERE id=?', (inicio, duracao, row['id']))

inicializar()
app = FastAPI(title='BarberSaaS', version='1.1.0')

class Reserva(BaseModel):
    cliente_nome: str = Field(min_length=2, max_length=100)
    cliente_telefone: str = Field(min_length=10, max_length=25)
    barbeiro_nome: str
    servico_nome: str
    data: date
    horario: str
    # Compatibilidade com a tela original: preço e telefone são definidos no servidor.
    preco: float | None = None
    telefone_barbeiro: str | None = None

class Situacao(BaseModel):
    status: str

def validar_opcoes(barbeiro, servico):
    if barbeiro not in BARBEIROS or servico not in SERVICOS:
        raise HTTPException(422, 'Escolha um barbeiro e um serviço válidos.')

def inicio_valido(data, horario, duracao):
    if horario not in HORARIOS:
        raise HTTPException(422, 'Horário fora do expediente.')
    inicio = datetime.fromisoformat(f'{data.isoformat()}T{horario}').replace(tzinfo=BRASIL)
    fim = inicio + timedelta(minutes=duracao)
    if not ((9 <= inicio.hour and fim.hour <= 12) or (14 <= inicio.hour and fim.hour <= 19)) or (fim.hour in (12, 19) and fim.minute):
        raise HTTPException(422, 'O serviço deve terminar antes do intervalo ou fechamento.')
    if inicio <= datetime.now(BRASIL):
        raise HTTPException(422, 'Escolha uma data e um horário futuros.')
    return inicio.replace(tzinfo=None)

def ocupado(db, barbeiro, inicio, duracao):
    fim = inicio + timedelta(minutes=duracao)
    rows = db.execute('SELECT inicio, duracao_minutos FROM agendamentos WHERE barbeiro_nome=? AND inicio LIKE ?', (barbeiro, inicio.date().isoformat() + '%'))
    return any(inicio < datetime.fromisoformat(r['inicio']) + timedelta(minutes=r['duracao_minutos']) and datetime.fromisoformat(r['inicio']) < fim for r in rows)

@app.get('/', response_class=HTMLResponse)
@app.get('/barbeiro', response_class=HTMLResponse)
@app.get('/admin', response_class=HTMLResponse)
def pagina():
    return (ROOT / 'index.html').read_text(encoding='utf-8')

@app.get('/api/agendamentos')
def listar():
    with conectar() as db:
        return [dict(r) for r in db.execute('SELECT * FROM agendamentos ORDER BY inicio, id')]

@app.get('/api/disponibilidade')
def disponibilidade(data: date, barbeiro_nome: str, servico_nome: str):
    validar_opcoes(barbeiro_nome, servico_nome)
    duracao = SERVICOS[servico_nome][1]
    horarios = []
    with conectar() as db:
        for hora in HORARIOS:
            try:
                inicio = inicio_valido(data, hora, duracao)
            except HTTPException:
                continue
            if not ocupado(db, barbeiro_nome, inicio, duracao):
                horarios.append(hora)
    return {'horarios': horarios}

@app.post('/api/agendamentos', status_code=201)
def criar(dados: Reserva):
    validar_opcoes(dados.barbeiro_nome, dados.servico_nome)
    nome = dados.cliente_nome.strip()
    telefone = re.sub(r'\D', '', dados.cliente_telefone)
    if telefone.startswith('55') and len(telefone) in (12, 13):
        telefone = telefone[2:]
    if len(nome) < 2 or len(telefone) not in (10, 11):
        raise HTTPException(422, 'Informe seu nome e WhatsApp com DDD.')
    preco, duracao = SERVICOS[dados.servico_nome]
    inicio = inicio_valido(dados.data, dados.horario, duracao)
    with conectar() as db:
        # Serializa a verificação e a gravação, inclusive entre processos.
        if DATABASE_URL:
            db.execute('SELECT pg_advisory_xact_lock(hashtext(?))', (dados.barbeiro_nome,))
        else:
            db.execute('BEGIN IMMEDIATE')
        if ocupado(db, dados.barbeiro_nome, inicio, duracao):
            raise HTTPException(409, 'Esse horário foi reservado. Escolha outro horário.')
        sql = '''INSERT INTO agendamentos
            (cliente_nome, cliente_telefone, barbeiro_nome, servico_nome, data_hora, preco, criado_em, inicio, duracao_minutos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'''
        if DATABASE_URL:
            sql += ' RETURNING id'
        cursor = db.execute(sql, (nome, telefone, dados.barbeiro_nome, dados.servico_nome, f'{dados.data} às {dados.horario}', preco, datetime.now(BRASIL).isoformat(), inicio.isoformat(timespec='minutes'), duracao))
        reserva_id = cursor.fetchone()['id'] if DATABASE_URL else cursor.lastrowid
    mensagem = f'Olá {nome}! Seu agendamento de {dados.servico_nome} com {dados.barbeiro_nome} está confirmado para {dados.data} às {dados.horario}.'
    return {'status': 'sucesso', 'agendamento_id': reserva_id, 'link_whatsapp_direto': f'https://wa.me/55{telefone}?text={quote(mensagem)}'}

@app.patch('/api/agendamentos/{reserva_id}')
def atualizar(reserva_id: int, dados: Situacao):
    if dados.status not in ('agendado', 'concluido'):
        raise HTTPException(422, 'Situação inválida.')
    with conectar() as db:
        cursor = db.execute('UPDATE agendamentos SET status=? WHERE id=?', (dados.status, reserva_id))
        if not cursor.rowcount:
            raise HTTPException(404, 'Agendamento não encontrado.')
        return dict(db.execute('SELECT * FROM agendamentos WHERE id=?', (reserva_id,)).fetchone())

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('PORT', '8000')))
