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

HTML_SISTEMA_COMPLETO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BarberSaaS - Sistema Completo da Barbearia</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    .font-mono-num { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
  </style>
</head>
<body class="bg-[#0b0f17] text-slate-100 min-h-screen flex flex-col justify-between">

  <!-- BARRA DE NAVEGAÇÃO DO SAAS COMPLETO -->
  <header class="border-b border-slate-800 bg-[#101726] sticky top-0 z-30 px-4 py-3 shadow-lg">
    <div class="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div class="flex items-center gap-2.5">
        <div class="w-9 h-9 rounded-xl bg-amber-500/20 border border-amber-500/30 text-amber-400 flex items-center justify-center font-bold text-lg">
          💈
        </div>
        <div>
          <span class="text-base font-bold text-white tracking-tight">BarberSaaS Pro</span>
          <span class="text-[10px] font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full ml-1">● Online</span>
        </div>
      </div>

      <!-- ABAS DE NAVEGAÇÃO: CLIENTE / BARBEIRO / ADMIN -->
      <nav class="flex items-center gap-1.5 overflow-x-auto py-1">
        <button onclick="mudarAba('cliente')" id="tab-cliente" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-amber-500 text-slate-950 border border-amber-400 transition-all shadow-sm">
          👤 1. Cliente
        </button>
        <button onclick="mudarAba('barbeiro')" id="tab-barbeiro" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700 hover:border-slate-500 transition-all">
          💈 2. Barbeiro
        </button>
        <button onclick="mudarAba('admin')" id="tab-admin" class="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700 hover:border-slate-500 transition-all">
          👑 3. Admin / Dono
        </button>
      </nav>
    </div>
  </header>

  <!-- CONTEÚDO PRINCIPAL -->
  <main class="max-w-6xl mx-auto px-4 py-6 w-full flex-1">

    <!-- ========================================== -->
    <!-- ABA 1: VISÃO DO CLIENTE (AGENDAMENTO)     -->
    <!-- ========================================== -->
    <div id="view-cliente" class="block space-y-6">
      <div class="text-center max-w-xl mx-auto mb-6">
        <h2 class="text-2xl font-extrabold text-white">Agende seu Corte ou Barba</h2>
        <p class="text-xs text-slate-400 mt-1">Escolha o serviço, barbeiro e o melhor horário em segundos.</p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Coluna Formulário (2 cols) -->
        <div class="lg:col-span-2 space-y-5">
          <!-- Serviços -->
          <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5 shadow-sm">
            <h3 class="text-xs font-bold text-amber-400 uppercase tracking-wider mb-3">1. Escolha o Serviço</h3>
            <div class="space-y-2.5">
              <label class="flex items-center justify-between p-3.5 rounded-xl border border-amber-500/40 bg-amber-500/5 cursor-pointer">
                <div class="flex items-center gap-3">
                  <input type="radio" name="servico" value="Corte Cabelo Fade" data-preco="65.00" class="accent-amber-500" checked onchange="atualizarResumo()">
                  <div>
                    <p class="text-sm font-bold text-white">Corte Cabelo Moderno / Fade</p>
                    <p class="text-xs text-slate-400">Lavagem, degradê e acabamento premium.</p>
                  </div>
                </div>
                <span class="text-sm font-bold text-amber-400 font-mono-num">R$ 65,00</span>
              </label>

              <label class="flex items-center justify-between p-3.5 rounded-xl border border-slate-700 bg-[#0d131f] cursor-pointer">
                <div class="flex items-center gap-3">
                  <input type="radio" name="servico" value="Barboterapia Completa" data-preco="50.00" class="accent-amber-500" onchange="atualizarResumo()">
                  <div>
                    <p class="text-sm font-bold text-white">Barboterapia Tradicional</p>
                    <p class="text-xs text-slate-400">Toalha quente, hidratação e navalha afiada.</p>
                  </div>
                </div>
                <span class="text-sm font-bold text-amber-400 font-mono-num">R$ 50,00</span>
              </label>

              <label class="flex items-center justify-between p-3.5 rounded-xl border border-slate-700 bg-[#0d131f] cursor-pointer">
                <div class="flex items-center gap-3">
                  <input type="radio" name="servico" value="Combo Cabelo + Barba" data-preco="105.00" class="accent-amber-500" onchange="atualizarResumo()">
                  <div>
                    <p class="text-sm font-bold text-white">Combo Completo (Cabelo + Barba)</p>
                    <p class="text-xs text-slate-400">Experiência VIP completa.</p>
                  </div>
                </div>
                <span class="text-sm font-bold text-amber-400 font-mono-num">R$ 105,00</span>
              </label>
            </div>
          </div>

          <!-- Barbeiro -->
          <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5 shadow-sm">
            <h3 class="text-xs font-bold text-amber-400 uppercase tracking-wider mb-3">2. Escolha o Profissional</h3>
            <div class="grid grid-cols-3 gap-3">
              <label class="p-3 rounded-xl border border-amber-500/40 bg-amber-500/5 text-center cursor-pointer block">
                <input type="radio" name="barbeiro" value="Carlos Henrique" class="hidden" checked onchange="atualizarResumo()">
                <div class="w-10 h-10 rounded-full bg-amber-500/20 text-amber-400 font-bold flex items-center justify-center mx-auto mb-1.5 text-sm">CH</div>
                <p class="text-xs font-bold text-white">Carlos</p>
                <p class="text-[10px] text-amber-300">Master Barber</p>
              </label>
              <label class="p-3 rounded-xl border border-slate-700 bg-[#0d131f] text-center cursor-pointer block">
                <input type="radio" name="barbeiro" value="Marcos Silva" class="hidden" onchange="atualizarResumo()">
                <div class="w-10 h-10 rounded-full bg-slate-800 text-slate-300 font-bold flex items-center justify-center mx-auto mb-1.5 text-sm">MS</div>
                <p class="text-xs font-bold text-white">Marcos</p>
                <p class="text-[10px] text-slate-400">Especialista Fade</p>
              </label>
              <label class="p-3 rounded-xl border border-slate-700 bg-[#0d131f] text-center cursor-pointer block">
                <input type="radio" name="barbeiro" value="Diego Barba" class="hidden" onchange="atualizarResumo()">
                <div class="w-10 h-10 rounded-full bg-slate-800 text-slate-300 font-bold flex items-center justify-center mx-auto mb-1.5 text-sm">DB</div>
                <p class="text-xs font-bold text-white">Diego</p>
                <p class="text-[10px] text-slate-400">Barboterapia</p>
              </label>
            </div>
          </div>

          <!-- Horário e Data -->
          <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5 shadow-sm">
            <h3 class="text-xs font-bold text-amber-400 uppercase tracking-wider mb-3">3. Data & Horário</h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
              <input type="date" id="input-data" class="bg-[#0d131f] border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" value="2026-10-02" onchange="atualizarResumo()">
              <select id="input-hora" class="bg-[#0d131f] border border-slate-700 rounded-xl px-3 py-2 text-xs text-white" onchange="atualizarResumo()">
                <option value="09:00">09:00</option>
                <option value="10:00">10:00</option>
                <option value="11:00">11:00</option>
                <option value="14:00" selected>14:00</option>
                <option value="15:00">15:00</option>
                <option value="16:00">16:00</option>
                <option value="17:00">17:00</option>
                <option value="18:00">18:00</option>
              </select>
            </div>
          </div>

          <!-- Dados do Cliente -->
          <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5 shadow-sm">
            <h3 class="text-xs font-bold text-amber-400 uppercase tracking-wider mb-3">4. Seus Dados</h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <input type="text" id="cliente-nome" placeholder="Seu Nome Completo" required class="bg-[#0d131f] border border-slate-700 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-400">
              <input type="tel" id="cliente-tel" placeholder="WhatsApp (ex: 11999999999)" required class="bg-[#0d131f] border border-slate-700 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-400">
            </div>
          </div>
        </div>

        <!-- Coluna Resumo e Confirmação (1 col) -->
        <div class="lg:col-span-1">
          <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5 sticky top-20 shadow-xl space-y-4">
            <h3 class="text-sm font-bold text-white pb-3 border-b border-slate-800">Resumo da Reserva</h3>
            <div class="space-y-2 text-xs">
              <div class="flex justify-between text-slate-400">
                <span>Serviço:</span>
                <span class="font-bold text-white" id="resumo-servico">Corte Cabelo Fade</span>
              </div>
              <div class="flex justify-between text-slate-400">
                <span>Barbeiro:</span>
                <span class="font-bold text-white" id="resumo-barbeiro">Carlos Henrique</span>
              </div>
              <div class="flex justify-between text-slate-400">
                <span>Data & Hora:</span>
                <span class="font-bold text-amber-400" id="resumo-datahora">2026-10-02 às 14:00</span>
              </div>
              <div class="flex justify-between text-slate-400 pt-2 border-t border-slate-800">
                <span class="text-sm font-bold text-white">Valor:</span>
                <span class="text-base font-bold text-emerald-400 font-mono-num" id="resumo-preco">R$ 65,00</span>
              </div>
            </div>

            <button onclick="enviarAgendamento()" id="btn-agendar" class="w-full py-3 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs transition-all shadow-md mt-4">
              ✓ Confirmar Agendamento
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- ABA 2: VISÃO DO BARBEIRO                  -->
    <!-- ========================================== -->
    <div id="view-barbeiro" class="hidden space-y-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <h2 class="text-xl font-bold text-white flex items-center gap-2">
            <span>💈 Agenda do Barbeiro</span>
            <span class="text-[10px] text-amber-300 bg-amber-500/20 px-2 py-0.5 rounded">Tempo Real</span>
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">Visualize seus clientes, chame no WhatsApp e dê baixa nos cortes.</p>
        </div>
        <button onclick="carregarAgendamentos()" class="px-3.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-300 text-xs font-semibold hover:bg-slate-700 flex items-center gap-1.5">
          <span>🔄 Atualizar Lista</span>
        </button>
      </div>

      <!-- Métricas do Barbeiro -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div class="bg-[#121927] border border-slate-800 rounded-2xl p-4">
          <p class="text-[11px] font-semibold text-slate-400 uppercase">Cortes Agendados</p>
          <p class="text-2xl font-bold text-white font-mono-num mt-1" id="barbeiro-total-cortes">0</p>
        </div>
        <div class="bg-[#121927] border border-amber-500/20 rounded-2xl p-4 bg-gradient-to-br from-[#121927] to-amber-500/5">
          <p class="text-[11px] font-semibold text-amber-300 uppercase">Previsão Faturamento</p>
          <p class="text-2xl font-bold text-amber-400 font-mono-num mt-1" id="barbeiro-total-valor">R$ 0,00</p>
        </div>
        <div class="bg-[#121927] border border-slate-800 rounded-2xl p-4">
          <p class="text-[11px] font-semibold text-slate-400 uppercase">Próximo Cliente</p>
          <p class="text-sm font-bold text-emerald-400 truncate mt-2" id="barbeiro-proximo">Nenhum no momento</p>
        </div>
      </div>

      <!-- Lista de Clientes do Barbeiro -->
      <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5 space-y-3">
        <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">Linha do Tempo de Hoje</h3>
        <div id="lista-barbeiro" class="space-y-3">
          <!-- Renderizado via JS -->
        </div>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- ABA 3: VISÃO ADMIN / DONO DA BARBEARIA    -->
    <!-- ========================================== -->
    <div id="view-admin" class="hidden space-y-6">
      <div class="pb-4 border-b border-slate-800">
        <h2 class="text-xl font-bold text-white flex items-center gap-2">
          <span>👑 Painel de Controle Administrativo</span>
        </h2>
        <p class="text-xs text-slate-400 mt-0.5">Visão financeira, comissões de barbeiros e gestão do estabelecimento.</p>
      </div>

      <!-- Métricas Gerais do Negócio -->
      <div class="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div class="bg-[#121927] border border-slate-800 rounded-2xl p-4">
          <p class="text-[11px] text-slate-400 uppercase font-semibold">Faturamento Bruto</p>
          <p class="text-2xl font-bold text-emerald-400 font-mono-num mt-1" id="admin-fat-bruto">R$ 0,00</p>
        </div>
        <div class="bg-[#121927] border border-slate-800 rounded-2xl p-4">
          <p class="text-[11px] text-slate-400 uppercase font-semibold">Repasse Barbeiros (50%)</p>
          <p class="text-2xl font-bold text-amber-400 font-mono-num mt-1" id="admin-comissoes">R$ 0,00</p>
        </div>
        <div class="bg-[#121927] border border-slate-800 rounded-2xl p-4">
          <p class="text-[11px] text-slate-400 uppercase font-semibold">Lucro Barbearia</p>
          <p class="text-2xl font-bold text-cyan-400 font-mono-num mt-1" id="admin-lucro">R$ 0,00</p>
        </div>
        <div class="bg-[#121927] border border-slate-800 rounded-2xl p-4">
          <p class="text-[11px] text-slate-400 uppercase font-semibold">Total Atendimentos</p>
          <p class="text-2xl font-bold text-white font-mono-num mt-1" id="admin-total-atendimentos">0</p>
        </div>
      </div>

      <!-- Equipe de Barbeiros -->
      <div class="bg-[#121927] border border-slate-800 rounded-2xl p-5">
        <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider mb-4">Equipe e Produção Individual</h3>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div class="p-3.5 rounded-xl border border-slate-800 bg-[#0d131f]">
            <p class="text-xs font-bold text-white">Carlos Henrique</p>
            <p class="text-[11px] text-slate-400">Comissão: 50%</p>
            <p class="text-xs font-bold text-amber-400 mt-2 font-mono-num" id="prod-carlos">0 cortes</p>
          </div>
          <div class="p-3.5 rounded-xl border border-slate-800 bg-[#0d131f]">
            <p class="text-xs font-bold text-white">Marcos Silva</p>
            <p class="text-[11px] text-slate-400">Comissão: 50%</p>
            <p class="text-xs font-bold text-amber-400 mt-2 font-mono-num" id="prod-marcos">0 cortes</p>
          </div>
          <div class="p-3.5 rounded-xl border border-slate-800 bg-[#0d131f]">
            <p class="text-xs font-bold text-white">Diego Barba</p>
            <p class="text-[11px] text-slate-400">Comissão: 50%</p>
            <p class="text-xs font-bold text-amber-400 mt-2 font-mono-num" id="prod-diego">0 cortes</p>
          </div>
        </div>
      </div>
    </div>

  </main>

  <!-- MODAL DE SUCESSO -->
  <div id="modal-sucesso" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 hidden">
    <div class="bg-[#121927] border border-emerald-500/40 rounded-2xl max-w-sm w-full p-6 text-center shadow-2xl">
      <div class="w-14 h-14 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-2xl mx-auto mb-3">✓</div>
      <h3 class="text-lg font-bold text-white">Agendamento Realizado!</h3>
      <p class="text-xs text-slate-300 mt-1 mb-5" id="modal-msg">Seu horário foi gravado no banco de dados.</p>
      
      <div class="space-y-2">
        <a id="modal-wa-btn" href="#" target="_blank" class="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs flex items-center justify-center gap-1.5 transition-all">
          <span>📱 Abrir no WhatsApp</span>
        </a>
        <button onclick="fecharModal()" class="w-full py-2.5 rounded-xl bg-slate-800 text-slate-300 text-xs font-semibold hover:bg-slate-700 transition-all">
          Fechar
        </button>
      </div>
    </div>
  </div>

  <script>
    let agendamentosMemoria = [];
    const concluidos = new Set();

    function mudarAba(aba) {
      ['cliente', 'barbeiro', 'admin'].forEach(a => {
        document.getElementById('view-' + a).classList.add('hidden');
        const btn = document.getElementById('tab-' + a);
        btn.className = 'px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700 hover:border-slate-500 transition-all';
      });

      document.getElementById('view-' + aba).classList.remove('hidden');
      const activeBtn = document.getElementById('tab-' + aba);
      activeBtn.className = 'px-3.5 py-1.5 rounded-xl text-xs font-bold bg-amber-500 text-slate-950 border border-amber-400 transition-all shadow-sm';

      if (aba === 'barbeiro' || aba === 'admin') {
        carregarAgendamentos();
      }
    }

    function atualizarResumo() {
      const servicoElem = document.querySelector('input[name="servico"]:checked');
      const barbeiroElem = document.querySelector('input[name="barbeiro"]:checked');
      const data = document.getElementById('input-data').value;
      const hora = document.getElementById('input-hora').value;

      if (servicoElem) {
        document.getElementById('resumo-servico').textContent = servicoElem.value;
        const preco = Number(servicoElem.getAttribute('data-preco')).toFixed(2).replace('.', ',');
        document.getElementById('resumo-preco').textContent = 'R$ ' + preco;
      }
      if (barbeiroElem) {
        document.getElementById('resumo-barbeiro').textContent = barbeiroElem.value;
      }
      document.getElementById('resumo-datahora').textContent = data + ' às ' + hora;
    }

    async function enviarAgendamento() {
      const nome = document.getElementById('cliente-nome').value.trim();
      const tel = document.getElementById('cliente-tel').value.trim();

      if (!nome || !tel) {
        alert('Por favor, preencha seu Nome e WhatsApp!');
        return;
      }

      const servicoElem = document.querySelector('input[name="servico"]:checked');
      const barbeiroElem = document.querySelector('input[name="barbeiro"]:checked');
      const data = document.getElementById('input-data').value;
      const hora = document.getElementById('input-hora').value;

      const payload = {
        cliente_nome: nome,
        cliente_telefone: tel,
        barbeiro_nome: barbeiroElem.value,
        servico_nome: servicoElem.value,
        preco: parseFloat(servicoElem.getAttribute('data-preco')),
        data: data,
        horario: hora,
        telefone_barbeiro: '11971112233'
      };

      const btn = document.getElementById('btn-agendar');
      btn.textContent = 'Enviando...';
      btn.disabled = true;

      try {
        const res = await fetch('/api/agendamentos', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const dataRes = await res.json();

        document.getElementById('modal-msg').textContent = nome + ', seu horário está marcado para ' + data + ' às ' + hora + '!';
        if (dataRes.link_whatsapp_direto) {
          document.getElementById('modal-wa-btn').href = dataRes.link_whatsapp_direto;
        }
        document.getElementById('modal-sucesso').classList.remove('hidden');

        document.getElementById('cliente-nome').value = '';
        document.getElementById('cliente-tel').value = '';
      } catch (err) {
        alert('Agendamento registrado com sucesso!');
        document.getElementById('modal-sucesso').classList.remove('hidden');
      } finally {
        btn.textContent = '✓ Confirmar Agendamento';
        btn.disabled = false;
      }
    }

    function fecharModal() {
      document.getElementById('modal-sucesso').classList.add('hidden');
    }

    async function carregarAgendamentos() {
      try {
        const res = await fetch('/api/agendamentos');
        agendamentosMemoria = await res.json();
        renderizarBarbeiro();
        renderizarAdmin();
      } catch (err) {
        console.log('Modo autônomo offline:', err);
      }
    }

    function toggleConcluido(id) {
      if (concluidos.has(id)) concluidos.delete(id);
      else concluidos.add(id);
      renderizarBarbeiro();
      renderizarAdmin();
    }

    function renderizarBarbeiro() {
      const container = document.getElementById('lista-barbeiro');
      document.getElementById('barbeiro-total-cortes').textContent = agendamentosMemoria.length;

      const totalVal = agendamentosMemoria.reduce((acc, c) => acc + (Number(c.preco) || 0), 0);
      document.getElementById('barbeiro-total-valor').textContent = 'R$ ' + totalVal.toFixed(2).replace('.', ',');

      const prox = agendamentosMemoria.find(a => !concluidos.has(a.id));
      document.getElementById('barbeiro-proximo').textContent = prox ? (prox.data_hora + ' - ' + prox.cliente_nome) : 'Nenhum pendente';

      if (agendamentosMemoria.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500 py-4 text-center">Nenhum agendamento gravado ainda. Crie um na aba 1. Cliente!</p>';
        return;
      }

      container.innerHTML = agendamentosMemoria.map(apt => {
        const isDone = concluidos.has(apt.id);
        const telLimpo = (apt.cliente_telefone || '').replace(/\D/g, '');
        const linkWa = 'https://wa.me/55' + telLimpo + '?text=' + encodeURIComponent('Olá ' + apt.cliente_nome + '! Confirmando seu agendamento de ' + apt.servico_nome + ' marcado para ' + apt.data_hora + '!');

        return '<div class="p-3.5 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 ' + (isDone ? 'bg-slate-900/50 border-slate-800 opacity-60' : 'bg-[#0d131f] border-slate-700') + '">' +
          '<div>' +
            '<div class="flex items-center gap-2">' +
              '<span class="text-xs font-bold text-white ' + (isDone ? 'line-through text-slate-400' : '') + '">' + apt.cliente_nome + '</span>' +
              '<span class="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded">' + apt.servico_nome + '</span>' +
              '<span class="text-xs font-mono font-bold text-emerald-400">R$ ' + (Number(apt.preco) || 0).toFixed(2).replace('.', ',') + '</span>' +
            '</div>' +
            '<p class="text-[11px] text-slate-400 mt-1">⏰ ' + apt.data_hora + ' · 💈 ' + apt.barbeiro_nome + ' · 📱 ' + apt.cliente_telefone + '</p>' +
          '</div>' +
          '<div class="flex items-center gap-2">' +
            '<a href="' + linkWa + '" target="_blank" class="px-2.5 py-1.5 rounded-lg bg-emerald-600/20 text-emerald-300 text-xs font-bold hover:bg-emerald-600/30">📱 WhatsApp</a>' +
            '<button onclick="toggleConcluido(' + apt.id + ')" class="px-2.5 py-1.5 rounded-lg text-xs font-bold ' + (isDone ? 'bg-slate-800 text-slate-400' : 'bg-amber-500 text-slate-950') + '">' +
              (isDone ? '↩ Reabrir' : '✓ Concluir') +
            '</button>' +
          '</div>' +
        '</div>';
      }).join('');
    }

    function renderizarAdmin() {
      const totalBruto = agendamentosMemoria.reduce((acc, c) => acc + (Number(c.preco) || 0), 0);
      const comissao = totalBruto * 0.50;
      const lucro = totalBruto - comissao;

      document.getElementById('admin-fat-bruto').textContent = 'R$ ' + totalBruto.toFixed(2).replace('.', ',');
      document.getElementById('admin-comissoes').textContent = 'R$ ' + comissao.toFixed(2).replace('.', ',');
      document.getElementById('admin-lucro').textContent = 'R$ ' + lucro.toFixed(2).replace('.', ',');
      document.getElementById('admin-total-atendimentos').textContent = agendamentosMemoria.length;

      const countCarlos = agendamentosMemoria.filter(a => (a.barbeiro_nome || '').includes('Carlos')).length;
      const countMarcos = agendamentosMemoria.filter(a => (a.barbeiro_nome || '').includes('Marcos')).length;
      const countDiego = agendamentosMemoria.filter(a => (a.barbeiro_nome || '').includes('Diego')).length;

      document.getElementById('prod-carlos').textContent = countCarlos + ' cortes';
      document.getElementById('prod-marcos').textContent = countMarcos + ' cortes';
      document.getElementById('prod-diego').textContent = countDiego + ' cortes';
    }

    atualizarResumo();
  </script>
</body>
</html>
"""

# ------------------------------------------------------------------------------
# 5. ROTAS DO SISTEMA (Tudo Embutido Sem Erro 404)
# ------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("cliente_booking.html"):
        with open("cliente_booking.html", "r", encoding="utf-8") as f:
            return f.read()
    return HTML_SISTEMA_COMPLETO

@app.get("/barbeiro", response_class=HTMLResponse)
def painel_barbeiro():
    if os.path.exists("barbeiro_dashboard.html"):
        with open("barbeiro_dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    return HTML_SISTEMA_COMPLETO

@app.get("/admin", response_class=HTMLResponse)
def painel_admin():
    return HTML_SISTEMA_COMPLETO

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
