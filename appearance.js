/* Aplicado no head antes de qualquer pintura; cada conta salva no servidor. */
window.Appearance=(()=>{
 const valid=['claro','escuro','sistema'], key='barber-aparencia', media=matchMedia('(prefers-color-scheme: dark)');
 let choice='sistema',csrf='',account='',saving=false;
 try{const cached=localStorage.getItem(key);if(valid.includes(cached))choice=cached;}catch{}
 function apply(value){
  choice=valid.includes(value)?value:'sistema';
  const theme=choice==='sistema'?(media.matches?'escuro':'claro'):choice;
  document.documentElement.dataset.theme=theme;
  document.documentElement.style.colorScheme=theme==='escuro'?'dark':'light';
  const meta=document.querySelector('meta[name="theme-color"]');if(meta)meta.content=theme==='escuro'?'#0b0c0d':'#f5f6f8';
  document.querySelectorAll('[data-appearance-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.appearanceChoice===choice)));
  window.dispatchEvent(new CustomEvent('appearancechange',{detail:{theme,choice}}));
 }
 function cache(){try{localStorage.setItem(key,choice);if(account)localStorage.setItem(key+':'+account,choice);}catch{}}
 apply(choice);
 media.addEventListener('change',()=>{if(choice==='sistema')apply(choice);});
 async function sync(session){
  csrf=session.csrf;
  const response=await fetch('/api/aparencia',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw Error('Não foi possível carregar sua aparência.');
  const data=await response.json();account=data.conta;apply(data.tema);cache();
 }
 async function select(value,guest=false){
  if(saving)return;saving=true;
  const previous=choice;apply(value);
  try{
   if(!guest){
    const r=await fetch('/api/aparencia',{method:'PUT',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({tema:value})});
    if(!r.ok)throw Error('Não foi possível salvar a aparência. Tente novamente.');
   }
   cache();
  }catch(e){apply(previous);throw e;}finally{saving=false;}
 }
 function mount(container,{guest=false}={}){
  container.innerHTML='<section class="appearance-section"><h3>Aparência</h3><p class="muted">'+(guest?'Escolha a aparência neste dispositivo.':'Sua escolha fica salva na sua conta.')+'</p><div class="appearance-options" role="group" aria-label="Aparência">'+[['claro','Claro'],['escuro','Escuro'],['sistema','Sistema']].map(([v,label])=>'<button type="button" class="secondary" data-appearance-choice="'+v+'" aria-pressed="'+(choice===v)+'">'+label+'</button>').join('')+'</div><p class="appearance-feedback muted" role="status" aria-live="polite"></p></section>';
  container.querySelectorAll('button').forEach(b=>b.onclick=async()=>{
   const buttons=[...container.querySelectorAll('button')];buttons.forEach(x=>x.disabled=true);
   const feedback=container.querySelector('[role=status]');feedback.textContent='';
   try{await select(b.dataset.appearanceChoice,guest);feedback.textContent=guest?'Aparência aplicada.':'Preferência salva na sua conta.';}
   catch(e){feedback.textContent=e.message;}finally{buttons.forEach(x=>x.disabled=false);}
  });
 }
 document.addEventListener('DOMContentLoaded',()=>{if(location.pathname==='/entrar'||location.pathname==='/cadastro'){const box=document.createElement('div');box.className='login-appearance';document.querySelector('main')?.append(box);mount(box,{guest:true});}});
 return {apply,sync,mount,get choice(){return choice;}};
})();
