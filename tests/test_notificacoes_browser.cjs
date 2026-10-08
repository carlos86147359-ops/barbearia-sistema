const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch();const base='http://127.0.0.1:8788',errors=[];
 const context=await browser.newContext({viewport:{width:390,height:844}});
 const instrument=()=>{window.__permissionPrompts=0;if('Notification' in window){const original=Notification.requestPermission.bind(Notification);Notification.requestPermission=(...args)=>{window.__permissionPrompts++;return original(...args);};}};
 await context.addInitScript(instrument);const page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 let r=await context.request.post(base+'/api/cadastro',{data:{aceite_termos:true,email:'push-browser@example.com',nome:'Push Browser',slug:'push-browser',senha:'SenhaTeste!12345'}});
 assert.equal(r.status(),201);const csrf=(await r.json()).csrf;
 await page.goto(base+'/painel#notificacoes');await page.getByRole('heading',{name:'Notificações',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>window.__permissionPrompts),0);
 await page.locator('[name=equipe]').check();await page.getByRole('button',{name:'Salvar preferências'}).click();
 await page.reload();await page.locator('[name=equipe]').waitFor();assert.equal(await page.locator('[name=equipe]').isChecked(),true);
 const cfg=await(await context.request.get(base+'/api/configuracao')).json();
 Object.assign(cfg,{barbeiros:[{id:'prof',nome:'Carlos'}],servicos:[{id:'corte',nome:'Corte',preco:35,duracao:30}],dias:[0,1,2,3,4,5,6],periodos:[{inicio:'08:00',fim:'20:00'}],intervalo:30});
 assert.equal((await context.request.put(base+'/api/configuracao',{headers:{'X-CSRF-Token':csrf},data:cfg})).status(),200);
 const publicContext=await browser.newContext();await publicContext.addInitScript(instrument);const customer=await publicContext.newPage();
 let requests=0;customer.on('request',r=>{if(r.url().includes('/api/notificacoes'))requests++;});
 await customer.goto(base+'/b/push-browser');await customer.locator('#start-booking').waitFor();
 assert.equal(await customer.locator('#notification-bell,#push-activate,#notification-settings').count(),0);
 assert.equal(requests,0);assert.equal(await customer.evaluate(()=>window.__permissionPrompts),0);
 const day=new Date(Date.now()+2*86400000).toISOString().slice(0,10);
 r=await publicContext.request.post(base+'/api/publico/push-browser/agendamentos',{data:{cliente_nome:'João Browser',cliente_telefone:'11900000000',data:day,horario:'09:00',barbeiro_id:'prof',servico_id:'corte'}});
 assert.equal(r.status(),201);const aid=(await r.json()).agendamento_id;
 await page.evaluate(()=>BarberNotifications.refresh());await page.getByRole('button',{name:'Ver agendamento',exact:true}).waitFor();
 assert.match(await page.locator('#notification-bell').innerText(),/1/);
 await page.getByRole('button',{name:'Ver agendamento',exact:true}).click();await page.locator('dialog[open]').waitFor();
 assert.match(await page.locator('dialog[open]').innerText(),/João Browser/);
 await page.goto(base+'/painel?agendamento='+aid+'#agenda');await page.locator('dialog[open]').waitFor();
 assert.match(await page.locator('dialog[open]').innerText(),/João Browser/);
 await page.goto(base+'/painel#notificacoes');await page.locator('#notification-list').waitFor();
 for(const width of [390,768,1440]){await page.setViewportSize({width,height:900});await page.getByRole('heading',{name:'Notificações',exact:true}).waitFor();await fs.mkdir('test-results',{recursive:true});await page.screenshot({path:'test-results/notifications-'+width+'.png',fullPage:true});const size=await page.evaluate(()=>[document.documentElement.scrollWidth,innerWidth]);assert.ok(size[0]<=size[1]+1,String(size));}
 // Denied permission is shown without repeated prompts. No configuration means no subscription attempt.
 await page.evaluate(()=>{Object.defineProperty(Notification,'permission',{configurable:true,value:'denied'});});
 await page.evaluate(()=>BarberNotifications.render());assert.equal(await page.locator('#push-activate').isDisabled(),true);assert.match(await page.locator('#notificacoes-area').innerText(),/Permissão bloqueada/);
 
 // Activation is explicit; subscribe is mocked, the authenticated storage endpoint is real.
 await page.evaluate(()=>{
  let current=null;window.__pushRequests=0;window.__pushSubscriptions=0;
  Object.defineProperty(Notification,'permission',{configurable:true,value:'default'});
  Notification.requestPermission=async()=>{window.__pushRequests++;Object.defineProperty(Notification,'permission',{configurable:true,value:'granted'});return 'granted';};
  PushManager.prototype.getSubscription=async()=>current;
  PushManager.prototype.subscribe=async()=>{window.__pushSubscriptions++;const raw={endpoint:'https://fcm.googleapis.com/fcm/send/browser-test',keys:{p256dh:'',auth:'YWFhYWFhYWFhYWFhYWFhYQ'},expirationTime:null};raw.keys.p256dh=window.__pushKey;current={toJSON:()=>raw,unsubscribe:async()=>{current=null;return true;}};return current;};
 });
 const pushConfig=await(await context.request.get(base+'/api/notificacoes/config')).json();assert.ok(pushConfig.public_key);
 await page.evaluate(k=>window.__pushKey=k,pushConfig.public_key);
 await page.evaluate(()=>BarberNotifications.render());assert.equal(await page.evaluate(()=>window.__pushRequests),0);
 await page.locator('#push-activate').click();await page.getByRole('heading',{name:'Notificações ativadas',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>window.__pushRequests),1);assert.equal(await page.evaluate(()=>window.__pushSubscriptions),1);
 assert.equal((await(await context.request.get(base+'/api/notificacoes/config')).json()).dispositivo_ativo,true);
 await page.locator('#push-disable').click();await page.getByRole('heading',{name:'Notificações desativadas',exact:true}).waitFor();
 assert.equal((await(await context.request.get(base+'/api/notificacoes/config')).json()).dispositivo_ativo,false);
 assert.equal((await publicContext.request.get(base+'/api/notificacoes')).status(),401);
 assert.deepEqual(errors,[]);await browser.close();console.log('OK: central mobile/tablet/desktop, account preferences, unread count, deep link, denied permission and no public push prompts.');
})().catch(e=>{console.error(e);process.exit(1);});
