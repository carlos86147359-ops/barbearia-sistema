/* Navega��o e feedback compartilhados. Sem regras de neg�cio. */
const AppShell=(()=>{
 let current=[],select=()=>{},guard=()=>true,toastTimer,currentActive;
 const link=(item,active)=>`<a href="${esc(item.href||'#'+item.id)}" data-shell="${esc(item.id)}" class="shell-link ${active===item.id?'selected':''}" ${active===item.id?'aria-current="page"':''} title="${esc(item.label)}">${UI.icon(item.icon)}<span>${esc(item.label)}</span></a>`;
 function mount({name,logo='',role,items,active,onSelect,canLeave=()=>true}){
  currentActive=active;current=items;select=onSelect||(()=>{});guard=canLeave;document.body.classList.add('workspace');
  document.getElementById('app-shell')?.remove();const shell=document.createElement('div');shell.id='app-shell';
  shell.innerHTML=`<a class="skip-link" href="#workspace-main">Pular para o conte�do</a><aside class="app-sidebar" aria-label="Menu principal"><a class="shell-brand" href="/painel#inicio">${UI.avatar(name,logo)}<span><strong>${esc(name)}</strong><small>${esc(role)}</small></span></a><button class="shell-collapse secondary" type="button" aria-label="Recolher menu" aria-expanded="true">${UI.icon('menu')}<span>Recolher menu</span></button><nav>${[...new Set(items.map(x=>x.group))].map(group=>`<section class="shell-group"><small class="shell-group-label">${esc(group)}</small>${items.filter(x=>x.group===group).map(x=>link(x,active)).join('')}</section>`).join('')}</nav><a class="shell-help" href="/suporte">${UI.icon('help')}<span>Ajuda e suporte</span></a></aside><div class="app-topbar"><span class="shell-shop-name">${esc(name)}</span><span class="shell-role">${esc(role)}</span><a href="/suporte" aria-label="Ajuda e suporte">${UI.icon('help')}</a></div><nav class="app-bottom" aria-label="Navega��o principal">${['inicio','agenda','clientes','caixa'].map(id=>items.find(x=>x.id===id)).filter(Boolean).map(x=>link(x.id==='caixa'?{...x,label:'Caixa'}:x,active)).join('')}<button type="button" id="shell-more" aria-haspopup="dialog">${UI.icon('menu')}<span>Mais</span></button></nav>`;
  document.body.prepend(shell);const main=document.querySelector('main');if(main){main.id='workspace-main';main.tabIndex=-1;}
  try{document.body.classList.toggle('sidebar-small',localStorage.getItem('barber-menu-small')==='1');}catch{}
  const collapse=shell.querySelector('.shell-collapse');function sync(){collapse.setAttribute('aria-expanded',String(!document.body.classList.contains('sidebar-small')));collapse.setAttribute('aria-label',document.body.classList.contains('sidebar-small')?'Expandir menu':'Recolher menu');}sync();
  collapse.onclick=()=>{document.body.classList.toggle('sidebar-small');sync();try{localStorage.setItem('barber-menu-small',document.body.classList.contains('sidebar-small')?'1':'0');}catch{}};
  bind(shell);document.getElementById('shell-more').onclick=()=>{open('Mais op��es',`<nav class="more-menu">${items.map(x=>link(x,currentActive)).join('')}</nav>`);bind(document.getElementById('shell-dialog'));};
 }
 function bind(root){root.querySelectorAll('[data-shell]').forEach(a=>a.onclick=e=>{if(!guard()){e.preventDefault();return;}const item=current.find(x=>x.id===a.dataset.shell);if(item&&!item.href){e.preventDefault();close();Promise.resolve(select(item.id)).catch(e=>toast(e.message,true));}});}
 function active(id){currentActive=id;document.querySelectorAll('#app-shell [data-shell]').forEach(x=>{const selected=x.dataset.shell===id;x.classList.toggle('selected',selected);if(selected)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});}
 function open(title,html,description=''){
  let dialog=document.getElementById('shell-dialog');if(!dialog){dialog=document.createElement('dialog');dialog.id='shell-dialog';dialog.className='ui-modal';document.body.append(dialog);}
  dialog.setAttribute('aria-labelledby','shell-dialog-title');dialog.innerHTML=`<div class="modal-heading"><h2 id="shell-dialog-title">${esc(title)}</h2><button type="button" class="secondary ui-icon-button" data-close-modal aria-label="Fechar janela">${UI.icon('close')}</button></div>${description?`<p class="muted">${esc(description)}</p>`:''}<div id="shell-dialog-message" role="alert" hidden></div><div class="modal-body">${html}</div>`;
  dialog.querySelector('[data-close-modal]').onclick=close;if(!dialog.open)dialog.showModal();return dialog;
 }
 function close(){document.getElementById('shell-dialog')?.close();}
 function confirm(title,description,action='Confirmar',danger=false){return new Promise(resolve=>{const d=open(title,`<div class="modal-actions"><button type="button" class="secondary" id="confirm-back">Voltar</button><button type="button" class="${danger?'danger':''}" id="confirm-yes">${esc(action)}</button></div>`,description);let answer=false;d.addEventListener('close',()=>resolve(answer),{once:true});document.getElementById('confirm-back').onclick=close;document.getElementById('confirm-yes').onclick=()=>{answer=true;close();};document.getElementById('confirm-back').focus();});}
 function toast(text,error=false){
  const modal=document.querySelector('dialog[open]');let box=modal?.querySelector('[role=alert]');
  if(modal&&!box){box=document.createElement('div');box.setAttribute('role','alert');(modal.querySelector('.modal-body,#modal-content')||modal).prepend(box);}
  if(!box){box=document.getElementById('app-toast');if(!box){box=document.createElement('div');box.id='app-toast';box.setAttribute('role','status');box.setAttribute('aria-live','polite');document.body.append(box);}}
  box.hidden=false;box.className='app-toast'+(error?' is-error':'');box.replaceChildren();const span=document.createElement('span');span.textContent=text;const button=document.createElement('button');button.className='toast-close';button.type='button';button.setAttribute('aria-label','Dispensar mensagem');button.innerHTML=UI.icon('close');button.onclick=()=>box.hidden=true;box.append(span,button);clearTimeout(toastTimer);if(!error)toastTimer=setTimeout(()=>box.hidden=true,6000);
 }
 function heading(eyebrow,title,description,actions=''){return `<div class="page-heading"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1><p class="muted">${esc(description)}</p></div>${actions?`<div class="page-actions">${actions}</div>`:''}</div>`;}
 const metric=(label,value,detail='')=>`<article class="card metric"><small>${esc(label)}</small><strong>${esc(value)}</strong>${detail?`<span class="muted">${esc(detail)}</span>`:''}</article>`;
 const empty=(title,text,action='')=>`<div class="card empty-state">${UI.empty(title,text)}${action}</div>`;
 function responsiveTable(root=document){root.querySelectorAll('table').forEach(table=>{const labels=[...table.querySelectorAll('thead th')].map(x=>x.textContent);table.querySelectorAll('tbody tr').forEach(row=>[...row.children].forEach((cell,i)=>cell.dataset.label=labels[i]||''));});}
 return {mount,active,open,close,confirm,toast,heading,metric,empty,responsiveTable};
})();

