/* Imagens são reduzidas no dispositivo; os arquivos não entram no banco de reservas. */
const ShopImages=(()=>{
 const limits={logo:{edge:512,bytes:120000,label:'logo'},capa:{edge:1200,bytes:250000,label:'capa'},foto:{edge:512,bytes:120000,label:'foto'}};
 const pending=new Map();let enabled=false,busy=false;
 function field(kind,value){return `<section class="image-editor" data-image-editor="${kind}"><h3>${kind==='logo'?'Logo da barbearia':'Foto de capa'}</h3><div class="image-preview ${kind}" id="preview-${kind}">${value?`<img src="${esc(value)}" alt="Prévia ${kind==='logo'?'do logo':'da capa'}" referrerpolicy="no-referrer">`:`<span>${UI.icon(kind==='logo'?'user':'scissors')}<small>Nenhuma imagem adicionada</small></span>`}</div><input type="file" id="file-${kind}" accept="image/jpeg,image/png,image/webp" class="hidden" aria-label="Escolher ${kind==='logo'?'logo':'foto de capa'}"><div class="row image-actions"><button type="button" class="secondary" data-pick="${kind}" disabled>${kind==='logo'?'Enviar logo':'Enviar foto de capa'}</button><button type="button" class="secondary" data-remove-image="${kind}" ${value?'':'hidden'}>Remover</button><button type="button" data-save-image="${kind}" hidden>Salvar ${limits[kind].label}</button><button type="button" class="secondary" data-discard-image="${kind}" hidden>Descartar</button></div><p class="muted image-feedback" id="feedback-${kind}" role="status">${kind==='logo'?'Até 512 px e 120 KB':'Até 1200 px e 250 KB'} após redução.</p><details class="image-link"><summary>Já tenho um link de imagem</summary><label>Link ${kind==='logo'?'do logo':'da capa'}<input name="${kind}_url" type="url" maxlength="1000" value="${esc(value||'')}" placeholder="https://..."></label></details></section>`;}
 const markup=cfg=>`<div id="image-storage-notice" class="muted" role="status">Conferindo envio de imagens…</div><div class="image-editors">${field('logo',cfg.logo_url)}${field('capa',cfg.capa_url)}</div><p class="muted"><small>As imagens aparecerão na página pública da barbearia. Use imagens que você tem autorização para publicar.</small></p>`;
 async function compress(file,kind){
  if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Escolha uma imagem JPG, PNG ou WebP.');
  if(file.size>15*1024*1024)throw Error('Escolha uma imagem com até 15 MB.');
  let image,url;
  try{
   if(typeof createImageBitmap==='function')image=await createImageBitmap(file);
   else {url=URL.createObjectURL(file);image=new Image();image.src=url;await image.decode();}
   const width=image.width||image.naturalWidth,height=image.height||image.naturalHeight;
   if(!width||!height||width*height>50000000)throw Error('A resolução é muito grande. Escolha uma versão menor da imagem.');
   const settings=limits[kind],ratio=Math.min(1,settings.edge/width,settings.edge/height),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(width*ratio));canvas.height=Math.max(1,Math.round(height*ratio));
   const ctx=canvas.getContext('2d');if(!ctx)throw Error('Seu navegador não conseguiu preparar a imagem.');ctx.drawImage(image,0,0,canvas.width,canvas.height);
   for(const quality of [.8,.65,.5]){const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',quality));if(blob&&['image/webp','image/png'].includes(blob.type)&&blob.size<=settings.bytes)return blob;}
   throw Error('Não conseguimos reduzir esta imagem. Escolha outra foto.');
  }catch(err){if(err.message&&/Escolha|resolução|navegador|reduzir/.test(err.message))throw err;throw Error('Não conseguimos abrir esta imagem. Tente uma foto JPG, PNG ou WebP.');}
  finally{if(image?.close)image.close();if(url)URL.revokeObjectURL(url);}
 }
 function clear(kind){const item=pending.get(kind);if(item)URL.revokeObjectURL(item.url);pending.delete(kind);}
 function preview(kind,url){const box=document.getElementById('preview-'+kind);box.replaceChildren();if(url){const img=document.createElement('img');img.src=url;img.alt='Prévia '+kind;img.referrerPolicy='no-referrer';box.append(img);}else box.innerHTML='<span>'+UI.icon('user')+'<small>Nenhuma imagem adicionada</small></span>';}
 function controls(kind){document.querySelector('[data-save-image="'+kind+'"]').hidden=!pending.has(kind);document.querySelector('[data-discard-image="'+kind+'"]').hidden=!pending.has(kind);document.querySelector('[data-remove-image="'+kind+'"]').hidden=pending.has(kind)||!document.querySelector('[name="'+kind+'_url"]').value;}
 function feedback(kind,text,error=false){const p=document.getElementById('feedback-'+kind);p.textContent=text;p.classList.toggle('upload-error',error);}
 function lock(value){busy=value;document.querySelectorAll('.image-editor button,#salvar-config').forEach(b=>b.disabled=value||(b.hasAttribute('data-pick')&&!enabled));document.querySelectorAll('.image-editor input').forEach(i=>i.disabled=value);}
 async function bind(){
  for(const kind of ['logo','capa'])clear(kind);enabled=false;busy=false;
  document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>document.getElementById('file-'+b.dataset.pick).click());
  document.querySelectorAll('[data-remove-image]').forEach(b=>b.onclick=()=>{const kind=b.dataset.removeImage;document.querySelector('[name="'+kind+'_url"]').value='';preview(kind,'');controls(kind);feedback(kind,'Imagem removida da prévia. Clique em Salvar configurações para aplicar.');});
  document.querySelectorAll('[data-discard-image]').forEach(b=>b.onclick=()=>{const kind=b.dataset.discardImage;clear(kind);preview(kind,document.querySelector('[name="'+kind+'_url"]').value);controls(kind);feedback(kind,'Alteração descartada.');});
  document.querySelectorAll('.image-editor input[type="url"]').forEach(input=>input.onchange=()=>{const kind=input.name.replace('_url','');clear(kind);preview(kind,input.value);controls(kind);});
  for(const kind of ['logo','capa']){
   document.getElementById('file-'+kind).onchange=async e=>{const file=e.target.files[0];e.target.value='';if(!file||busy)return;lock(true);feedback(kind,'Preparando imagem…');try{const blob=await compress(file,kind);clear(kind);const url=URL.createObjectURL(blob);pending.set(kind,{blob,url});preview(kind,url);controls(kind);feedback(kind,`Prévia pronta · ${Math.ceil(blob.size/1024)} KB. Clique em Salvar ${limits[kind].label}.`);}catch(err){feedback(kind,err.message,true);}finally{lock(false);}};
   document.querySelector('[data-save-image="'+kind+'"]').onclick=async()=>{const item=pending.get(kind);if(!item||busy)return;lock(true);feedback(kind,'Enviando e salvando na nuvem…');try{const response=await fetch('/api/imagens/'+kind,{method:'POST',headers:{'Content-Type':item.blob.type,'X-CSRF-Token':csrf},body:item.blob});const data=await response.json().catch(()=>({}));if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Não foi possível enviar a imagem.');config[kind+'_url']=data.url;document.querySelector('[name="'+kind+'_url"]').value=data.url;clear(kind);preview(kind,data.url);controls(kind);feedback(kind,'Imagem salva! Já aparece na página da barbearia.');}catch(err){feedback(kind,err.message||'Falha de conexão. Tente novamente.',true);}finally{lock(false);}};
  }
  try{const status=await api('/api/imagens/status');enabled=status.disponivel;const notice=document.getElementById('image-storage-notice');notice.textContent=enabled?'Escolha na galeria, confira a prévia e salve a imagem.':'O envio pela galeria está aguardando ativação pelo administrador. Os links de imagens continuam funcionando.';notice.classList.toggle('notice',!enabled);lock(false);}catch{document.getElementById('image-storage-notice').textContent='Não foi possível conferir o envio de imagens. Atualize a página.';}
 }
 function ready(){if(busy){mensagem('Aguarde a preparação ou o envio da imagem.',true);return false;}if(pending.size){mensagem('Salve a imagem escolhida ou descarte a prévia antes de salvar as configurações.',true);return false;}return true;}
 return {markup,bind,ready,compress};
})();

/* Recorte local: o círculo é só a máscara; o arquivo salvo é quadrado. */
const PhotoCropper=(()=>{
 let active=false;
 const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
 function rectangle(width,height,zoom=1,cx=width/2,cy=height/2){
  const side=Math.min(width,height)/clamp(zoom,1,4);
  return {x:clamp(cx-side/2,0,width-side),y:clamp(cy-side/2,0,height-side),side};
 }
 async function encode(image,crop){
  // Reduz somente depois do enquadramento, sem mudar a proporção 1:1.
  for(const edge of [Math.min(512,Math.floor(crop.side)),384,256]){
   const size=Math.max(1,Math.min(edge,Math.floor(crop.side))),canvas=document.createElement('canvas');
   canvas.width=canvas.height=size;
   const ctx=canvas.getContext('2d');if(!ctx)throw Error('Seu navegador não conseguiu preparar a foto.');
   ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
   ctx.drawImage(image,crop.x,crop.y,crop.side,crop.side,0,0,size,size);
   for(const quality of [.85,.75,.65,.5]){
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',quality));
    if(blob&&['image/webp','image/png'].includes(blob.type)&&blob.size<=120000)return blob;
   }
  }
  throw Error('Não conseguimos reduzir esta foto. Escolha outra imagem.');
 }
 async function open(file){
  if(active)throw Error('Finalize o ajuste da foto aberta.');
  if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Escolha uma imagem JPG, PNG ou WebP.');
  if(file.size>15*1024*1024)throw Error('Escolha uma imagem com até 15 MB.');
  active=true;let image,url,dialog;
  const previous=document.activeElement;
  try{
   if(typeof createImageBitmap==='function')image=await createImageBitmap(file);
   else{url=URL.createObjectURL(file);image=new Image();image.src=url;await image.decode();}
   const width=image.width||image.naturalWidth,height=image.height||image.naturalHeight;
   if(!width||!height||width*height>50000000)throw Error('A resolução é muito grande. Escolha uma versão menor da imagem.');
   dialog=document.createElement('dialog');dialog.className='ui-modal photo-crop-dialog';dialog.id='photo-crop-dialog';
   dialog.setAttribute('aria-labelledby','photo-crop-title');dialog.setAttribute('aria-describedby','photo-crop-help');
   dialog.innerHTML='<h2 id="photo-crop-title">Ajustar foto do profissional</h2><p id="photo-crop-help" class="muted">Arraste a foto com o dedo ou o mouse. Ajuste o zoom para enquadrar o rosto dentro do círculo.</p><div class="photo-crop-stage"><canvas width="512" height="512" tabindex="0" role="img" aria-label="Prévia circular. Arraste para mover ou use as setas do teclado."></canvas></div><label>Zoom<input id="photo-crop-zoom" type="range" min="1" max="4" step="0.01" value="1" aria-label="Zoom da foto"></label><p id="photo-crop-message" class="muted" role="status">A foto será salva quadrada, com o enquadramento mostrado no círculo.</p><div class="modal-actions"><button type="button" class="secondary" data-crop-cancel>Cancelar</button><button type="button" data-crop-save>Salvar foto</button></div>';
   document.body.append(dialog);
   const canvas=dialog.querySelector('canvas'),ctx=canvas.getContext('2d'),zoomInput=dialog.querySelector('input'),message=dialog.querySelector('[role=status]');
   if(!ctx)throw Error('Seu navegador não conseguiu preparar a foto.');
   let zoom=1,cx=width/2,cy=height/2,drag=null,processing=false,result=null;
   const crop=()=>rectangle(width,height,zoom,cx,cy);
   function draw(){const r=crop();cx=r.x+r.side/2;cy=r.y+r.side/2;ctx.clearRect(0,0,512,512);ctx.drawImage(image,r.x,r.y,r.side,r.side,0,0,512,512);}
   function move(dx,dy){const rect=canvas.getBoundingClientRect(),r=crop();cx-=dx*r.side/rect.width;cy-=dy*r.side/rect.height;draw();}
   zoomInput.oninput=()=>{zoom=Number(zoomInput.value);draw();};
   canvas.onpointerdown=e=>{if(processing||drag!==null||e.button>0)return;e.preventDefault();canvas.focus({preventScroll:true});drag={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);};
   canvas.onpointermove=e=>{if(!drag||drag.id!==e.pointerId||processing)return;e.preventDefault();move(e.clientX-drag.x,e.clientY-drag.y);drag.x=e.clientX;drag.y=e.clientY;};
   const end=e=>{if(drag?.id===e.pointerId)drag=null;};
   canvas.onpointerup=end;canvas.onpointercancel=end;canvas.onlostpointercapture=end;
   canvas.onkeydown=e=>{if(processing)return;const direction={ArrowLeft:[-8,0],ArrowRight:[8,0],ArrowUp:[0,-8],ArrowDown:[0,8]}[e.key];if(direction){e.preventDefault();move(...direction);}};
   const cancelled=()=>{if(processing)return;result=null;dialog.close();};
   dialog.querySelector('[data-crop-cancel]').onclick=cancelled;
   dialog.addEventListener('cancel',e=>{if(processing)e.preventDefault();});
   dialog.querySelector('[data-crop-save]').onclick=async()=>{
    if(processing)return;processing=true;drag=null;dialog.querySelectorAll('button,input').forEach(b=>b.disabled=true);message.textContent='Preparando o recorte…';
    try{result=await encode(image,crop());dialog.close();}
    catch(e){message.textContent=e.message;processing=false;dialog.querySelectorAll('button,input').forEach(b=>b.disabled=false);}
   };
   draw();
   const closed=new Promise(resolve=>dialog.addEventListener('close',resolve,{once:true}));
   dialog.showModal();await closed;return result;
  }finally{
   dialog?.remove();if(image?.close)image.close();if(url)URL.revokeObjectURL(url);active=false;
   if(previous?.isConnected)previous.focus({preventScroll:true});
  }
 }
 return {open,rectangle,encode};
})();

/* Editor compartilhado entre Equipe e Configurações > Profissionais. */
const ProfessionalPhotos=(()=>{
 const states=new Map();
 function markup(b){return '<section class="professional-photo" data-professional-photo="'+esc(b.id)+'"><h3>Foto do profissional</h3><div class="image-preview logo photo-preview">'+UI.professional(b)+'</div><input type="file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Escolher foto do profissional"><input type="hidden" data-campo="foto_url" value="'+esc(b.foto_url||'')+'"><div class="row image-actions"><button type="button" class="secondary" data-photo-pick disabled>Escolher foto</button><button type="button" data-photo-save hidden>Salvar foto</button><button type="button" class="secondary" data-photo-discard hidden>Descartar</button><button type="button" class="secondary" data-photo-remove '+(b.foto_url?'':'hidden')+'>Remover foto</button></div><p class="muted" role="status">Até 512 px e 120 KB após redução.</p></section>';}
 function ready(){for(const [box,state] of states){if(!box.isConnected){if(state.url)URL.revokeObjectURL(state.url);states.delete(box);continue;}if(state.busy||state.blob){mensagem('Salve ou descarte a foto escolhida antes de salvar as configurações.',true);return false;}}return true;}
 async function bind(){
  for(const [box,state] of states)if(!box.isConnected){if(state.url)URL.revokeObjectURL(state.url);states.delete(box);}
  let enabled=false;try{enabled=(await api('/api/imagens/status')).disponivel;}catch{}
  document.querySelectorAll('[data-professional-photo]').forEach(box=>{
   const id=box.dataset.professionalPhoto,saved=config.barbeiros.some(b=>b.id===id),pick=box.querySelector('[data-photo-pick]'),file=box.querySelector('[type=file]'),input=box.querySelector('[data-campo=foto_url]'),preview=box.querySelector('.photo-preview'),feedback=box.querySelector('[role=status]');
   if(states.has(box)){pick.disabled=!enabled||!saved;return;}
   const state={busy:false,blob:null,url:''};states.set(box,state);
   function clear(){if(state.url)URL.revokeObjectURL(state.url);state.blob=null;state.url='';}
   function draw(url){preview.innerHTML=UI.professional({id,nome:config.barbeiros.find(b=>b.id===id)?.nome||'Profissional',foto_url:url});box.querySelector('[data-photo-save]').hidden=!state.blob;box.querySelector('[data-photo-discard]').hidden=!state.blob;box.querySelector('[data-photo-remove]').hidden=!!state.blob||!input.value;}
   function lock(value){state.busy=value;box.querySelectorAll('button').forEach(b=>b.disabled=value);pick.disabled=value||!enabled||!config.barbeiros.some(b=>b.id===id);}
   state.draw=draw;
   function persist(url){
    const b=config.barbeiros.find(b=>b.id===id);if(b)b.foto_url=url;
    document.querySelectorAll('[data-professional-photo]').forEach(other=>{
     if(other.dataset.professionalPhoto!==id)return;
     other.querySelector('[data-campo=foto_url]').value=url;
     if(other!==box&&!states.get(other)?.blob)states.get(other)?.draw(url);
    });
    if(b)document.querySelectorAll('[data-professional-avatar]').forEach(avatar=>{
     if(avatar.dataset.professionalAvatar===id)avatar.outerHTML=UI.professional(b,avatar.classList.contains('large')?'large':'');
    });
    input.value=url;
   }
   pick.disabled=!enabled||!saved;
   if(!saved)feedback.textContent='Salve o novo profissional nas configurações antes de enviar a foto.';
   else if(!enabled)feedback.textContent='Envio pela galeria indisponível. Confira o armazenamento de imagens.';
   pick.onclick=()=>file.click();
   file.onchange=async()=>{
    const chosen=file.files[0];file.value='';if(!chosen||state.busy)return;
    lock(true);feedback.textContent='Abrindo ajuste da foto…';
    let save=false;
    try{
     const blob=await PhotoCropper.open(chosen);
     if(!blob){feedback.textContent='Ajuste cancelado. A foto anterior foi mantida.';return;}
     if(!box.isConnected)return;
     clear();state.blob=blob;state.url=URL.createObjectURL(blob);draw(state.url);
     feedback.textContent='Prévia pronta · '+Math.ceil(blob.size/1024)+' KB.';save=true;
    }catch(e){feedback.textContent=e.message;}
    finally{lock(false);}
    if(save)await upload();
   };
   box.querySelector('[data-photo-discard]').onclick=()=>{clear();draw(input.value);feedback.textContent='Alteração descartada.';};
   async function upload(){if(!state.blob||state.busy)return;lock(true);feedback.textContent='Salvando foto na nuvem…';try{const response=await fetch('/api/equipe/'+encodeURIComponent(id)+'/foto',{method:'POST',headers:{'Content-Type':state.blob.type,'X-CSRF-Token':csrf},body:state.blob});const data=await response.json().catch(()=>({}));if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Não foi possível salvar a foto.');persist(data.url);clear();draw(data.url);feedback.textContent='Foto salva! Já aparece na escolha do profissional.';}catch(e){feedback.textContent=e.message||'Falha de conexão. Tente novamente.';}finally{lock(false);}}
   box.querySelector('[data-photo-save]').onclick=upload;
   box.querySelector('[data-photo-remove]').onclick=async()=>{if(state.busy)return;lock(true);try{await api('/api/equipe/'+encodeURIComponent(id)+'/foto',{method:'DELETE'});persist('');clear();draw('');feedback.textContent='Foto removida.';}catch(e){feedback.textContent=e.message;}finally{lock(false);}};
  });
 }
 return {markup,bind,ready};
})();
