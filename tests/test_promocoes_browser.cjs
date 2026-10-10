const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch(),base='http://127.0.0.1:8788',errors=[],slug='promos-'+Date.now();
 const owner=await browser.newContext(),customer=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const r=await owner.request.post(base+'/api/cadastro',{data:{nome:'Loja Promoções',slug,email:slug+'@example.com',senha:'SenhaTeste!12345',aceite_termos:true}});assert.equal(r.status(),201,await r.text());
 const session=await r.json(),headers={'X-CSRF-Token':session.csrf};
 const cfg=await(await owner.request.get(base+'/api/configuracao')).json();
 Object.assign(cfg,{servicos:[{id:'corte',nome:'Corte',preco:40,duracao:30}],barbeiros:[{id:'prof',nome:'Carlos'},{id:'outro',nome:'Bruno'}],dias:[0,1,2,3,4,5,6],periodos:[{inicio:'08:00',fim:'20:00'}],intervalo:30});
 assert.equal((await owner.request.put(base+'/api/configuracao',{headers,data:cfg})).status(),200);
 const page=await owner.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/painel#promocoes');await page.locator('#promotion-create').click();
 const f=page.locator('#promotion-form');await f.locator('[name=nome]').fill('Corte com desconto');await f.locator('[name=servicos][value=corte]').check();await f.locator('[name=barbeiros][value=prof]').check();
 await page.locator('#promotion-preview').click();await page.locator('#promotion-live-preview .promotion-card').waitFor();
 await page.locator('#promotion-publish').click();await page.locator('#promotion-list h2').filter({hasText:'Corte com desconto'}).waitFor();
 const pub=await customer.newPage();pub.on('pageerror',e=>errors.push(e.message));
 await pub.goto(base+'/b/'+slug);await pub.locator('[data-promotion]').click();
 assert.equal(await pub.locator('#professional-choices [data-choice=outro]').isVisible(),false);
 assert.equal(await pub.locator('#professional-choices [data-choice=prof]').isVisible(),true);
 await pub.locator('#continuar-profissional').click();
 const day=new Date(Date.now()+2*86400000).toISOString().slice(0,10);
 if(!await pub.locator('[data-date="'+day+'"]').count())await pub.locator('[data-month="1"]').click();
 await pub.locator('[data-date="'+day+'"]').click();await pub.locator('[data-hour="09:00"]').click();await pub.locator('#continuar-horario').click();
 await pub.locator('[name=cliente_nome]').fill('Cliente Oferta');await pub.locator('[name=cliente_telefone]').fill('11944447777');await pub.locator('#continuar-dados').click();
 assert.match(await pub.locator('#review-booking').innerText(),/29,90/);assert.match(await pub.locator('#review-booking').innerText(),/10,10/);
 await pub.locator('#agendar').click();await pub.getByRole('heading',{name:'Agendamento confirmado!',exact:true}).waitFor();
 const rows=await(await owner.request.get(base+'/api/agendamentos')).json(),appointment=rows.find(a=>a.cliente_nome==='Cliente Oferta');assert.equal(appointment.preco,29.9);assert.equal(appointment.barbeiro_id,'prof');
 await page.goto(base+'/painel#agenda');await page.reload();await page.waitForFunction(()=>typeof showAppointment==='function'&&reservas.length>0);await page.evaluate(id=>showAppointment(id),appointment.id);await page.locator('#detail-finish').click();
 // O diálogo existente pede confirmação de conclusão; não registra pagamento sozinho.
 await page.locator('#confirm-yes').click();await page.waitForFunction(id=>reservas.some(r=>r.id===id&&r.status==='concluido'),appointment.id);await page.evaluate(id=>showAppointment(id),appointment.id);await page.locator('#promotion-payment').click();await page.locator('#promo-payment-form button').click();await page.getByText('Recebimento confirmado · pix',{exact:true}).waitFor();
 await page.waitForTimeout(500);
 await fs.mkdir('test-results',{recursive:true});
 for(const theme of ['claro','escuro']){
  assert.equal((await owner.request.put(base+'/api/aparencia',{headers,data:{tema:theme}})).status(),200);
  await page.goto(base+'/painel#promocoes');await page.reload();await page.locator('#promotion-create').waitFor();assert.equal(await page.locator('html').getAttribute('data-theme'),theme);await page.screenshot({path:'test-results/promocoes-'+theme+'-desktop.png',fullPage:true});
 }
 await pub.goto(base+'/b/'+slug);await pub.locator('.public-promotions').waitFor();assert.equal(await pub.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await pub.screenshot({path:'test-results/promocoes-mobile.png',fullPage:true});
 assert.equal(await pub.locator('a[href^="/painel"],a[href^="/entrar"],#instalar-app').count(),0);
 assert.deepEqual(errors,[]);await browser.close();console.log('OK promoções: editor, prévia, fluxo público mobile, preço e painel');
})().catch(e=>{console.error(e);process.exit(1);});
