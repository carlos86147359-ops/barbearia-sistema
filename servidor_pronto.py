# ==============================================================================
# servidor_pronto.py
# Servidor Completo All-in-One da Barbearia (FastAPI + SQLite Local Grátis)
# Execute: python servidor_pronto.py
# ==============================================================================
import os
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ------------------------------------------------------------------------------
# 1. BANCO DE DADOS LOCAL 100% GRATUITO (SQLite Automático)
# ------------------------------------------------------------------------------
DATABASE_URL = "sqlite:///./barbearia.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBAppointment(Base):
    __tablename__ = "agendamentos"
    id = Column(Integer, primary_key=True, index=True)
    cliente_nome = Column(String(100), nullable=False)
    cliente_telefone = Column(String(20), nullable=False)
    barbeiro_nome = Column(String(100), nullable=False)
    servico_nome = Column(String(100), nullable=False)
    data_hora = Column(String(50), nullable=False)
    preco = Column(Float, nullable=False)
    criado_em = Column(DateTime, default=datetime.now)

# Cria o arquivo barbearia.db automaticamente se não existir
Base.metadata.create_all(bind=engine)

# ------------------------------------------------------------------------------
# 2. APLICAÇÃO FASTAPI
# ------------------------------------------------------------------------------
app = FastAPI(
    title="BarberSaaS - Servidor Local Gratuito",
    description="Sistema de agendamento pronto para rodar sem gastar nada.",
    version="1.0.0"
)

# Permitir conexões do navegador
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# 3. SCHEMAS DE DADOS
# ------------------------------------------------------------------------------
class AgendamentoEntrada(BaseModel):
    cliente_nome: str
    cliente_telefone: str
    barbeiro_nome: str
    servico_nome: str
    data: str
    horario: str
    preco: float
    telefone_barbeiro: Optional[str] = "11971112233"

# ------------------------------------------------------------------------------
# 4. FUNÇÃO DO WHATSAPP (Link Direto Grátis e Seguro)
# ------------------------------------------------------------------------------
def disparar_notificacao_whatsapp(telefone: str, msg: str):
    """
    Log de envio assíncrono para o barbeiro via BackgroundTasks.
    """
    print()
    print("📲 [WHATSAPP ENVIADO VIA SEGUNDO PLANO]")
    print(f"➡️ Para o Barbeiro no número: {telefone}")
    print(f"💬 Conteúdo da mensagem:")
    print(msg)
    print()

# ------------------------------------------------------------------------------
# 5. ROTAS DO SISTEMA
# ------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("cliente_booking.html"):
        with open("cliente_booking.html", "r", encoding="utf-8") as f:
            return f.read()
    return """
    <html>
      <body style="font-family: sans-serif; padding: 40px; background: #0b0f17; color: #fff;">
        <h1 style="color: #f59e0b;">✂️ BarberSaaS Rodando com Sucesso!</h1>
        <p>O seu servidor FastAPI e banco de dados SQLite local estão ativos!</p>
        <p>Acesse a documentação interativa em: <a style="color: #60a5fa;" href="/docs">/docs</a></p>
      </body>
    </html>
    """

@app.get("/api/agendamentos")
def listar_agendamentos():
    db = SessionLocal()
    agendamentos = db.query(DBAppointment).order_by(DBAppointment.id.desc()).all()
    db.close()
    return agendamentos

@app.post("/api/agendamentos", status_code=201)
def criar_agendamento(dados: AgendamentoEntrada, bg: BackgroundTasks):
    print()
    print("=" * 50)
    print("🔔 [NOVO AGENDAMENTO RECEBIDO NO SERVIDOR!]")
    print(f"👤 Cliente:  {dados.cliente_nome} ({dados.cliente_telefone})")
    print(f"✂️ Serviço:  {dados.servico_nome} - R$ {dados.preco:.2f}")
    print(f"💈 Barbeiro: {dados.barbeiro_nome}")
    print(f"📅 Horário:  {dados.data} às {dados.horario}")
    print("=" * 50)
    print()

    db = SessionLocal()
    novo = DBAppointment(
        cliente_nome=dados.cliente_nome,
        cliente_telefone=dados.cliente_telefone,
        barbeiro_nome=dados.barbeiro_nome,
        servico_nome=dados.servico_nome,
        data_hora=f"{dados.data} às {dados.horario}",
        preco=dados.preco
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    db.close()

    # Mensagem do WhatsApp formatada com emojis
    linhas = [
        "✂️ *Novo Agendamento Confirmado!*",
        "",
        f"👤 Cliente: *{dados.cliente_nome}*",
        f"📱 WhatsApp: *{dados.cliente_telefone}*",
        f"💈 Barbeiro: *{dados.barbeiro_nome}*",
        f"✂️ Serviço: *{dados.servico_nome}*",
        f"📅 Horário: *{dados.data} às {dados.horario}*",
        f"💰 Valor: *R$ {dados.preco:.2f}*",
        "",
        "Agendado via BarberSaaS Cloud Engine."
    ]
    msg_texto = chr(10).join(linhas)
    
    # Envio assíncrono em segundo plano (BackgroundTasks)
    bg.add_task(disparar_notificacao_whatsapp, dados.telefone_barbeiro, msg_texto)

    # Link oficial wa.me (Custo Zero)
    link_wa = f"https://wa.me/55{re.sub(r'\D', '', dados.telefone_barbeiro)}?text={urllib.parse.quote(msg_texto)}"

    return {
        "status": "sucesso",
        "mensagem": "Agendamento registrado com sucesso no banco de dados!",
        "agendamento_id": novo.id,
        "link_whatsapp_direto": link_wa
    }

# ------------------------------------------------------------------------------
# 6. INICIALIZAÇÃO DIRETA NO WINDOWS E RENDER
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    porta = int(os.environ.get("PORT", 8000))
    print()
    print("=" * 60)
    print("🚀 SERVIDOR DA BARBEARIA INICIADO COM SUCESSO!")
    print(f"👉 Porta: {porta}")
    print("👉 Acesse no seu navegador: http://localhost:8000")
    print("👉 Documentação Swagger:   http://localhost:8000/docs")
    print("=" * 60)
    print()
    uvicorn.run(app, host="0.0.0.0", port=porta)
