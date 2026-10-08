const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {indexedDB}=require('fake-indexeddb');
const handlers={},shown=[],opened=[],messages=[];const origin='https://barber.example';
const client={id:'staff',url:origin+'/painel',postMessage:m=>messages.push(m),navigate:async u=>opened.push(u),focus:async()=>{}};
const self={location:{origin},addEventListener:(n,f)=>handlers[n]=f,registration:{showNotification:async(t,o)=>shown.push({t,o})},skipWaiting:async()=>{},clients:{get:async()=>client,claim:async()=>{},matchAll:async()=>[client],openWindow:async u=>opened.push(u)}};
vm.runInNewContext(fs.readFileSync('sw.js','utf8'),{self,indexedDB,URL,Number,String,Date,Promise,caches:{},fetch:()=>{}});
async function event(type,data){let p;handlers[type]({...data,waitUntil:q=>p=q});if(p)await p;}
(async()=>{
 const id='a'.repeat(64),account='shop:user',payload={id,conta:account,agendamento_id:22,titulo:'Novo agendamento ✂️',mensagem:'João agendou Corte.'};
 await event('message',{source:{id:'staff'},data:{type:'PUSH_ACCOUNT',account}});
 await event('push',{data:{json:()=>payload}});await event('push',{data:{json:()=>payload}});
 assert.equal(shown.length,1);assert.equal(shown[0].o.tag,'booking-event-'+id);assert.equal(shown[0].o.renotify,false);
 await event('push',{data:{json:()=>({...payload,id:'b'.repeat(64),conta:'other:user'})}});assert.equal(shown.length,1);
 await event('notificationclick',{notification:{data:shown[0].o.data,close:()=>{}}});
 assert.match(opened[0],/\/painel\?agendamento=22&notificacao=a{64}#agenda$/);
 await event('message',{source:{id:'staff'},data:{type:'PUSH_ACCOUNT',account:''}});
 await event('notificationclick',{notification:{data:shown[0].o.data,close:()=>{}}});assert.equal(opened.length,1);
 await event('push',{data:{json:()=>({...payload,id:'c'.repeat(64)})}});assert.equal(shown.length,1);
 await event('message',{source:{id:'staff'},data:{type:'PUSH_ACCOUNT',account}});
 let first=true;self.registration.showNotification=async(t,o)=>{if(first){first=false;throw Error('temporary');}shown.push({t,o});};
 const next={...payload,id:'d'.repeat(64)};
 await assert.rejects(event('push',{data:{json:()=>next}}));await event('push',{data:{json:()=>next}});assert.equal(shown.length,2);
 client.url=origin+'/b/shop';await event('message',{source:{id:'staff'},data:{type:'PUSH_ACCOUNT',account:'other:user'}});
 await event('push',{data:{json:()=>({...payload,id:'e'.repeat(64)})}});assert.equal(shown.length,3);
 console.log('OK: encrypted-payload consumer, unique display, correct click URL, account isolation, logout, public binding blocked, retry after display failure.');
})().catch(e=>{console.error(e);process.exit(1);});
