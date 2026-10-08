const OFFLINE_CACHE = 'barbersaas-offline-v1';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then(cache => cache.add('/offline.html').then(()=>self.skipWaiting())));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('barbersaas-offline-') && key !== OFFLINE_CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
// Reservas, sessões e respostas da API sempre passam pela rede.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => caches.match('/offline.html')));
});


/* Conta ativa e identificadores de entrega; nenhum dado de cliente é colocado no cache. */
function pushStore(action){
 return new Promise((resolve,reject)=>{
  const open=indexedDB.open('barber-push-state',1);
  open.onupgradeneeded=()=>open.result.createObjectStore('state',{keyPath:'id'});
  open.onerror=()=>reject(open.error);
  open.onsuccess=()=>{
   const db=open.result,tx=db.transaction('state','readwrite'),s=tx.objectStore('state');let result;
   tx.oncomplete=()=>{db.close();resolve(result);};tx.onerror=()=>{db.close();reject(tx.error);};tx.onabort=()=>{db.close();reject(tx.error);};
   action(s,value=>result=value);
  };
 });
}
self.addEventListener('message',event=>{
 if(event.data?.type!=='PUSH_ACCOUNT')return;
 event.waitUntil((async()=>{
  if(!event.source?.id)return;
  const client=await self.clients.get(event.source.id);
  if(!client||new URL(client.url).origin!==self.location.origin||!/^\/(painel|admin|barbeiro)$/.test(new URL(client.url).pathname))return;
  await pushStore((s,done)=>{s.put({id:'account',value:String(event.data.account||'')});done(true);});
  event.ports?.[0]?.postMessage({ok:true});
 })());
});
self.addEventListener('push',event=>{
 event.waitUntil((async()=>{
  let p;try{p=event.data.json();}catch{return;}
  if(!/^[a-f0-9]{64}$/.test(p.id)||!Number.isSafeInteger(p.agendamento_id)||p.agendamento_id<1)return;
  const accepted=await pushStore((s,done)=>{
   const account=s.get('account');account.onsuccess=()=>{
    if(!account.result?.value||account.result.value!==p.conta){done(false);return;}
    const seen=s.get(p.id);seen.onsuccess=()=>{
     if(seen.result){done(false);return;}
     s.put({id:p.id,at:Date.now()});done(true);
     const cursor=s.openCursor();cursor.onsuccess=()=>{const cur=cursor.result;if(!cur)return;if(cur.value.at&&cur.value.at<Date.now()-7*86400000)cur.delete();cur.continue();};
    };
   };
  });
  if(!accepted)return;
  try{
   await self.registration.showNotification(String(p.titulo||'Sua agenda').slice(0,100),{
    body:String(p.mensagem||'Confira o atendimento no painel.').slice(0,250),icon:'/icons/icon-192.png',
    badge:'/icons/icon-192.png',tag:'booking-event-'+p.id,renotify:false,
    data:{id:p.id,appointment:p.agendamento_id,account:p.conta}
   });
  }catch(e){await pushStore((s,done)=>{s.delete(p.id);done(true);});throw e;}
  const clients=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  clients.forEach(c=>{if(new URL(c.url).origin===self.location.origin)c.postMessage({type:'PUSH_RECEIVED'});});
 })());
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();
 event.waitUntil((async()=>{
  const data=event.notification.data||{};
  if(!Number.isSafeInteger(data.appointment)||data.appointment<1||!/^[a-f0-9]{64}$/.test(data.id))return;
  const account=await pushStore((s,done)=>{const q=s.get('account');q.onsuccess=()=>done(q.result?.value);});
  if(account!==data.account)return;
  const url=self.location.origin+'/painel?agendamento='+data.appointment+'&notificacao='+data.id+'#agenda';
  const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  for(const client of windows){
   if(new URL(client.url).origin===self.location.origin&&new URL(client.url).pathname==='/painel'){
    await client.navigate(url);await client.focus();return;
   }
  }
  await self.clients.openWindow(url);
 })());
});
