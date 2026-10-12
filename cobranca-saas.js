/* Homologação Grupo Havo. Não é o módulo de mensalistas da barbearia. */
(()=>{
 'use strict';
 const original=renderAssinatura;
 const labels={criando:'Criando checkout',incerta:'Aguardando conferência',checkout:'Checkout disponível',aguardando_pagamento:'Aguardando pagamento',ativa:'Ativa',atrasada:'Pagamento pendente ou atrasado',cancelada:'Cancelada',expirada:'Checkout expirado'};
 function buttonBusy(b,action){b.disabled=true;return action().catch(e=>mensagem(e.message,true)).finally(()=>{if(b.isConnected)b.disabled=false;});}
 renderAssinatura=function(){original();if(!sessao?.administrador)return;const host=document.getElementById('assinatura-area');const target=document.createElement('section');target.className='card';target.id='asaas-sandbox';host.append(target);load(target);};
 async function load(target){
  try{
   const a=await api('/api/saas/assinatura');if(!target.isConnected)return;if(!a.disponivel){target.remove();return;}
   const current=a.contratos.find(c=>!['cancelada','expirada'].includes(c.status));
   target.innerHTML=`<span class="badge">SANDBOX · TESTES</span><h2>Minha assinatura · Asaas</h2><p>Teste a contratação de ${money(a.valor_centavos/100)} por mês no cartão. Não movimenta dinheiro real e não altera o acesso das barbearias.</p>${current?`<p><strong>${esc(labels[current.status]||current.status)}</strong></p><p>Próxima cobrança: ${esc(current.proximo_vencimento||'Aguardando confirmação')}</p><p>Período pago simulado até: ${esc(current.pago_ate||'Nenhum')}</p>${current.erro?`<p role="alert">${esc(current.erro)}</p>`:''}${current.checkout_url?`<p><a class="button" href="${esc(current.checkout_url)}" target="_blank" rel="noopener">Abrir checkout de teste</a></p>`:''}<button class="secondary" data-cancel="${esc(current.id)}">Cancelar contratação de teste</button>`:'<button data-contract>Testar contratação mensal</button>'}<button class="secondary" data-sync>Atualizar situação no Asaas</button><p class="muted">O retorno do checkout não confirma pagamento. A situação é conferida no servidor. Use somente dados fictícios de teste.</p><h3>Histórico de pagamentos simulados</h3>${a.pagamentos.length?'<div style="overflow-x:auto"><table><thead><tr><th>Vencimento</th><th>Valor</th><th>Situação</th><th>Fatura</th></tr></thead><tbody>'+a.pagamentos.map(p=>`<tr><td>${esc(p.vencimento)}</td><td>${money(p.valor_centavos/100)}</td><td>${esc(p.status)}</td><td>${p.fatura_url?`<a href="${esc(p.fatura_url)}" target="_blank" rel="noopener">Abrir</a>`:'—'}</td></tr>`).join('')+'</tbody></table></div>':'<p class="muted">Nenhum pagamento de teste registrado.</p>'}<p class="muted">A troca de cartão e a liberação automática em produção serão disponibilizadas após a homologação. O Pix manual continua funcionando.</p>`;
   target.querySelector('[data-contract]')?.addEventListener('click',e=>buttonBusy(e.currentTarget,async()=>{
    if(!await AppShell.confirm('Criar assinatura de teste?','Será criado um checkout recorrente de R$ 90 mensais exclusivamente no Sandbox do Asaas. Não informe cartão real.','Criar checkout de teste'))return;
    await api('/api/saas/checkout',{method:'POST'});await load(target);
   }));
   target.querySelector('[data-sync]').onclick=e=>buttonBusy(e.currentTarget,async()=>{await api('/api/saas/sincronizar',{method:'POST'});await load(target);mensagem('Situação de testes sincronizada.');});
   target.querySelector('[data-cancel]')?.addEventListener('click',e=>{const b=e.currentTarget;buttonBusy(b,async()=>{if(!await AppShell.confirm('Cancelar teste?','A recorrência simulada será interrompida. O histórico será preservado.','Cancelar teste',true))return;await api('/api/saas/contratos/'+encodeURIComponent(b.dataset.cancel)+'/cancelar',{method:'POST'});await load(target);});});
  }catch(e){if(target.isConnected)target.innerHTML='<h2>Assinatura Asaas · testes</h2><p role="alert">'+esc(e.message)+'</p>';}
 }
 const originalAdmin=adminExtras;
 adminExtras=async function(){await originalAdmin();try{const a=await api('/api/gestao/asaas');const host=document.createElement('section');host.className='card';host.innerHTML=`<h2>Asaas · homologação Sandbox</h2><p>Eventos aguardando processamento: ${Number(a.eventos_pendentes)}</p><p>${esc(a.observacao)}</p>${a.contratos.map(c=>`<div class="item"><strong>${esc(c.slug)}</strong><p>${esc(c.email)} · ${esc(labels[c.status]||c.status)} · ${money(c.valor_centavos/100)}/mês (simulado)</p></div>`).join('')||'<p>Nenhuma contratação de teste.</p>'}`;el.append(host);}catch(e){mensagem('Não foi possível consultar a homologação Asaas.',true);}};
})();
