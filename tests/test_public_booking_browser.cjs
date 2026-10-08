const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
(async () => {
 const browser = await chromium.launch(), errors = [];
 const base = 'http://127.0.0.1:8788', password = 'SenhaTeste!12345';
 const owner = await browser.newContext(), customer = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const watch = page => page.on('pageerror', e => errors.push(e.message));
 let r = await owner.request.post(base+'/api/cadastro',{data:{aceite_termos:true,nome:'Loja Agendamento',slug:'public-booking',email:'public-owner@example.com',senha:password}});
 assert.equal(r.status(),201,await r.text());
 const session = await (await owner.request.get(base+'/api/sessao')).json(), headers = {'X-CSRF-Token':session.csrf};
 const cfg = await (await owner.request.get(base+'/api/configuracao')).json();
 Object.assign(cfg,{nome:'Loja Agendamento',servicos:[{id:'corte',nome:'Corte',preco:35,duracao:30}],barbeiros:[{id:'prof',nome:'Carlos'},{id:'outro',nome:'João'}],dias:[0,1,2,3,4,5,6],periodos:[{inicio:'08:00',fim:'20:00'}],intervalo:30,whatsapp:'11900000000'});
 r = await owner.request.put(base+'/api/configuracao',{headers,data:cfg}); assert.equal(r.status(),200,await r.text());
 r = await owner.request.post(base+'/api/equipe/prof/convite',{headers,data:{email:'public-staff@example.com'}}); assert.equal(r.status(),201,await r.text());
 const token = (await r.json()).link.split('#')[1];
 const staff = await browser.newContext();
 r = await staff.request.post(base+'/api/convite/aceitar',{data:{token,senha:password}}); assert.equal(r.status(),201,await r.text());
 const page = await customer.newPage(); watch(page);
 const assertPublic = async () => {
  assert.equal(await page.locator('body').getAttribute('data-public-booking'),'true');
  assert.equal(await page.locator('#instalacao-app,#instalar-app,#ajuda-app,link[rel=manifest]').count(),0);
  assert.equal(await page.locator('a[href="/"],a[href^="/painel"],a[href^="/entrar"],a[href^="/admin"],a[href^="/barbeiro"],a[href^="/cadastro"]').count(),0);
  assert.doesNotMatch(await page.locator('body').innerText(),/Área da barbearia|Área do Barbeiro|Instalar aplicativo|Como instalar no celular/i);
 };
 // Sem JavaScript: nenhum CTA interno ou instalação aparece durante o carregamento.
 const nojs = await browser.newContext({javaScriptEnabled:false}), raw = await nojs.newPage();
 await raw.goto(base+'/b/public-booking');
 assert.equal(await raw.locator('header a,#instalacao-app,link[rel=manifest]').count(),0);
 await nojs.close();
 await page.goto(base+'/b/public-booking'); await page.locator('#start-booking').waitFor(); await assertPublic();
 assert.equal(await page.locator('header .brand').innerText(),'Loja Agendamento');
 const prevented = await page.evaluate(() => {const e=new Event('beforeinstallprompt',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;}); assert.equal(prevented,true);
 const day = new Date(Date.now()+2*86400000).toISOString().slice(0,10);
 async function chooseTime(){
  for(let i=0;i<2 && await page.locator('[data-date="'+day+'"]').count()===0;i++) await page.locator('[data-month="1"]').click();
  await page.locator('[data-date="'+day+'"]').click();
  await page.locator('[data-hour="09:00"]').waitFor(); await page.locator('[data-hour="09:00"]').click();
 }
 await page.locator('#start-booking').click();
 await page.locator('#service-choices [data-choice=corte]').click(); await page.locator('#continuar-servico').click();
 await page.locator('#professional-choices [data-choice=prof]').click(); await page.locator('#continuar-profissional').click();
 await chooseTime(); await page.locator('#continuar-horario').click();
 assert.equal(await page.locator('#reserva input:not([type=hidden])').count(),2);
 await page.locator('[name=cliente_nome]').fill('Cliente pelo navegador'); await page.locator('[name=cliente_telefone]').fill('11944447777');
 await page.locator('#continuar-dados').click(); await assertPublic();
 await page.locator('#agendar').click(); await page.getByRole('heading',{name:'Agendamento confirmado!',exact:true}).waitFor(); await assertPublic();
 const reservations = await (await owner.request.get(base+'/api/agendamentos')).json();
 const appointment = reservations.find(a=>a.cliente_nome==='Cliente pelo navegador'); assert.ok(appointment); assert.equal(appointment.barbeiro_id,'prof');
 const own = await (await staff.request.get(base+'/api/agendamentos')).json(); assert.ok(own.some(a=>a.id===appointment.id));
 assert.equal((await customer.request.get(base+'/api/agendamentos')).status(),401);
 await fs.mkdir('test-results',{recursive:true}); await page.screenshot({path:'test-results/public-booking-success-mobile.png',fullPage:true});
 const manage = await page.getByRole('link',{name:'Ver ou alterar minha reserva'}).getAttribute('href'); assert.ok(manage);
 await page.goto(new URL(manage,base).href); await page.getByRole('heading',{name:'Minha reserva',exact:true}).waitFor(); await assertPublic();
 // Qualquer profissional, telefone/tablet/desktop e erro sem saída para ambiente interno.
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:900}); await page.goto(base+'/b/public-booking'); await page.locator('#start-booking').waitFor(); await assertPublic();
  await page.locator('#start-booking').click(); await page.locator('#service-choices [data-choice=corte]').click(); await page.locator('#continuar-servico').click();
  assert.equal(await page.locator('#professional-choices [data-choice="*"]').getAttribute('aria-pressed'),'true');
  await page.locator('#continuar-profissional').click(); await chooseTime(); await assertPublic();
  const dims=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth})); assert.ok(dims.scroll<=dims.width+1,JSON.stringify(dims));
  await page.screenshot({path:'test-results/public-booking-'+width+'.png',fullPage:true});
 }
 await page.goto(base+'/b/loja-inexistente'); await page.getByRole('heading',{name:'Não foi possível abrir esta página'}).waitFor(); await assertPublic();
 assert.equal(await page.getByRole('link',{name:'Tentar novamente'}).getAttribute('href'),'/b/loja-inexistente');
 for(const [context,email] of [[owner,'public-owner@example.com'],[staff,'public-staff@example.com']]){
  const p = await context.newPage(); watch(p);
  const s = await (await context.request.get(base+'/api/sessao')).json(); await context.request.post(base+'/api/logout',{headers:{'X-CSRF-Token':s.csrf}});
  await p.goto(base+'/entrar'); await p.locator('[name=email]').fill(email); await p.locator('[name=senha]').fill(password); await p.locator('#form-acesso button[type=submit]').click(); await p.waitForURL(/\/painel(?:#.*)?$/);
  await p.locator('#app-shell').waitFor(); assert.equal(await p.locator('#instalar-app').count(),1); assert.equal(await p.locator('link[rel=manifest]').count(),1);
  assert.ok((await (await context.request.get(base+'/api/agendamentos')).json()).some(a=>a.id===appointment.id));
 }
 assert.deepEqual(errors,[]); await browser.close();
 console.log('OK: cliente sem conta/instalação, fluxo completo mobile, qualquer profissional, três larguras, reserva privada, erro seguro, login dono/barbeiro e reservas na agenda.');
})().catch(e=>{console.error(e);process.exit(1);});
