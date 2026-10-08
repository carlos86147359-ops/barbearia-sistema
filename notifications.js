/* Apenas o ambiente autenticado inicializa este módulo. */
const BarberNotifications=(()=>{
 let settings=null,offset=0,timer=null,busy=false;
 const compatible=()=>isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
 const standalone=()=>matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
 const ios=()=>/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
 const permission=()=>('Notification' in window?Notification.permission:'default');
 const target=()=>document.getElementById('notificacoes-area');
 async function worker(){const r=await navigator.serviceWorker.register('/sw.js',{scope:'/'});await r.update();return navigator.serviceWorker.ready;}
 async function bind(account){const r=await worker();(r.active||navigator.serviceWorker.controller)?.postMessage({type:'PUSH_ACCOUNT',account});}
 function state(){
  if(!compatible()||(ios()&&!standalone()))return 'Dispositivo não compatível';
  if(permission()==='denied')return 'Permissão bloqueada';
  return settings?.dispositivo_ativo&&permission()==='granted'?'Notificações ativadas':'Notificações desativadas';
 }
 async function activate(){
  const b=document.getElementById('push-activate');b.disabled=true;
  try{
   if(!settings.public_key)throw Error('O administrador precisa configurar o envio de push no servidor.');
   // Permission is requested directly in the click handler, never during loading.
   const p=permission()==='granted'?'granted':await Notification.requestPermission();
   if(p!=='granted'){settings.dispositivo_ativo=false;await render();return;}
   const r=await worker();let sub=await r.pushManager.getSubscription();
   if(sub&&!settings.dispositivo_ativo){await sub.unsubscribe();sub=null;}
   const raw=atob(settings.public_key.replace(/-/g,'+').replace(/_/g,'/'));
   const key=Uint8Array.from(raw,x=>x.charCodeAt(0));
   sub=sub||await r.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
   try{await api('/api/notificacoes/dispositivos',{method:'POST',body:JSON.stringify(sub.toJSON())});}
   catch(e){await sub.unsubscribe().catch(()=>{});throw e;}
   await bind(settings.conta);settings.dispositivo_ativo=true;await render();AppShell.toast('Notificações ativadas neste dispositivo.');
  }catch(e){AppShell.toast(e.message,true);}finally{if(b.isConnected)b.disabled=false;}
 }
 async function disable(){
  await bind('');
  await api('/api/notificacoes/dispositivos/atual',{method:'DELETE'});
  const r=await worker(),s=await r.pushManager.getSubscription();if(s)await s.unsubscribe();
  settings.dispositivo_ativo=false;await render();
 }
 async function refresh(){
  if(busy||!settings||document.hidden)return;busy=true;
  try{
   const data=await api('/api/notificacoes?offset='+offset);
   const bell=document.getElementById('notification-bell');if(bell){bell.textContent='🔔'+(data.nao_lidas?' '+data.nao_lidas:'');bell.setAttribute('aria-label','Notificações: '+data.nao_lidas+' não lidas');}
   const list=document.getElementById('notification-list');if(!list)return;
   list.innerHTML=data.itens.length?data.itens.map(n=>`<article class="card"><div class="section-heading"><strong>${esc(n.titulo)}</strong><span class="badge">${n.lida_em?'Lida':'Não lida'}</span></div><p><strong>${esc(n.cliente)}</strong></p><p>${esc(n.servico)} · ${esc(n.profissional)}</p><p>${esc(dateLabel(n.inicio))} · ${esc(n.inicio.slice(11,16))}</p><p class="muted">${esc(new Date(n.criado_em*1000).toLocaleString('pt-BR'))}</p><div class="row"><button data-open-notification="${n.id}" data-appointment="${n.agendamento_id}">Ver agendamento</button>${n.lida_em?'':`<button class="secondary" data-read-notification="${n.id}">Marcar como lida</button>`}</div></article>`).join(''):UI.empty('Nenhuma notificação','Os próximos avisos da sua agenda aparecerão aqui.');
   list.querySelectorAll('[data-read-notification]').forEach(b=>b.onclick=()=>read(b.dataset.readNotification).catch(e=>AppShell.toast(e.message,true)));
   list.querySelectorAll('[data-open-notification]').forEach(b=>b.onclick=async()=>{try{await read(b.dataset.openNotification);reservas=await api('/api/agendamentos');await mostrarAba('agenda');showAppointment(Number(b.dataset.appointment));}catch(e){AppShell.toast(e.message,true);}});
   document.getElementById('notification-prev').disabled=offset===0;document.getElementById('notification-next').disabled=data.itens.length<50;
  }catch(e){if(target()&&!target().classList.contains('hidden'))AppShell.toast('Não foi possível atualizar os avisos. Tente novamente.',true);}finally{busy=false;}
 }
 async function read(id){await api('/api/notificacoes/'+id+'/lida',{method:'POST'});await refresh();}
 async function render(){
  settings=await api('/api/notificacoes/config');const root=target();if(!root)return;
  root.innerHTML=AppShell.heading('SUA AGENDA','Notificações','Avisos dos atendimentos e configurações deste dispositivo.')+
   `<section class="card"><h2>Configurações → Notificações</h2><h3>${state()}</h3><p>Receba avisos de novos agendamentos, cancelamentos e alterações diretamente neste celular.</p>
   ${ios()&&!standalone()?'<p>Para receber push no iPhone, abra o sistema no Safari e use Compartilhar → Adicionar à Tela de Início. Requer iOS 16.4 ou mais recente.</p>':''}
   ${permission()==='denied'?'<p>A permissão está bloqueada. Altere a permissão de notificações nas configurações do navegador para reativar.</p>':''}
   ${!settings.public_key?'<p class="muted">A central funciona normalmente. O envio para o celular aguarda configuração pelo administrador.</p>':''}
   <div class="row"><button id="push-activate" ${!compatible()||permission()==='denied'||(ios()&&!standalone())||!settings.public_key?'disabled':''}>Ativar notificações neste dispositivo</button><button id="push-disable" class="secondary" ${!settings.dispositivo_ativo?'disabled':''}>Desativar neste dispositivo</button></div>
   <form id="notification-settings"><h3>Receber</h3>${[['novos','Novos agendamentos'],['cancelamentos','Cancelamentos'],['reagendamentos','Reagendamentos'],['lembretes','Lembretes'],...(settings.gestor?[['equipe','Receber agendamentos de toda a equipe']]:[])].map(([key,label])=>`<label class="check"><input type="checkbox" name="${key}" ${settings[key]?'checked':''}> ${label}</label>`).join('')}
   <label>Lembrar antes do atendimento (minutos)<input type="number" name="minutos" min="5" max="120" value="${settings.minutos}"></label>
   ${!settings.lembretes_continuos?'<p class="muted">Na hospedagem que suspende o servidor, lembretes podem não chegar no horário. Para lembretes contínuos, o servidor precisa permanecer ativo.</p>':''}
   ${settings.gestor?'<p class="muted">Ative “toda a equipe” para receber os avisos da barbearia. Cada barbeiro recebe somente seus próprios atendimentos.</p>':''}<button>Salvar preferências</button></form></section>
   <section><div class="section-heading"><h2>Central de notificações</h2><button class="secondary" id="notification-read-all">Marcar todas como lidas</button></div><div id="notification-list" aria-live="polite">${UI.loading('Carregando avisos…')}</div><div class="row"><button class="secondary" id="notification-prev">Anteriores</button><button class="secondary" id="notification-next">Próximas</button></div></section>`;
  document.getElementById('push-activate').onclick=activate;
  document.getElementById('push-disable').onclick=()=>disable().catch(e=>AppShell.toast(e.message,true));
  document.getElementById('notification-settings').onsubmit=async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button');b.disabled=true;try{const values={minutos:Number(f.elements.minutos.value)};for(const key of ['novos','cancelamentos','reagendamentos','lembretes','equipe'])values[key]=Boolean(f.elements[key]?.checked);await api('/api/notificacoes/config',{method:'PUT',body:JSON.stringify(values)});AppShell.toast('Preferências salvas.');}catch(err){AppShell.toast(err.message,true);}finally{b.disabled=false;}};
  document.getElementById('notification-read-all').onclick=async()=>{try{await api('/api/notificacoes/lidas',{method:'POST'});await refresh();}catch(e){AppShell.toast(e.message,true);}};
  document.getElementById('notification-prev').onclick=()=>{offset=Math.max(0,offset-50);refresh();};document.getElementById('notification-next').onclick=()=>{offset+=50;refresh();};
  await refresh();
 }
 async function init(){
  if(document.body.dataset.publicBooking==='true'||!sessao)return;
  settings=await api('/api/notificacoes/config');
  const top=document.querySelector('.app-topbar');if(top&&!document.getElementById('notification-bell')){const b=document.createElement('button');b.id='notification-bell';b.className='secondary';b.type='button';b.textContent='🔔';b.onclick=()=>mostrarAba('notificacoes');top.append(b);}
  if(compatible()){await bind(settings.dispositivo_ativo?settings.conta:'');navigator.serviceWorker.addEventListener('message',e=>{if(e.data?.type==='PUSH_RECEIVED')refresh();});}
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  clearInterval(timer);timer=setInterval(refresh,60000);await refresh();
 }
 return{init,render,refresh,disable};
})();
