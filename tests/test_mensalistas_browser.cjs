const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch(),errors=[];
 const context=await browser.newContext({viewport:{width:1440,height:960},colorScheme:'dark'});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:8788',password='SenhaTeste!12345';
 let r=await context.request.post(base+'/api/cadastro',{data:{nome:'Barbearia Mensalistas',slug:'monthly-browser',email:'monthly-browser@example.com',senha:password,aceite_termos:true}});
 assert.equal(r.status(),201,await r.text());
 const session=await (await context.request.get(base+'/api/sessao')).json(),headers={'X-CSRF-Token':session.csrf};
 const cfg=await (await context.request.get(base+'/api/configuracao')).json();
 cfg.servicos=[{id:'corte',nome:'Corte',preco:35,duracao:30}];cfg.barbeiros=[{id:'prof',nome:'Carlos'}];cfg.dias=[0,1,2,3,4,5,6];cfg.periodos=[{inicio:'08:00',fim:'20:00'}];cfg.intervalo=30;cfg.whatsapp='11900000000';
 r=await context.request.put(base+'/api/configuracao',{headers,data:cfg});assert.equal(r.status(),200,await r.text());
 const now=new Date(),day=new Date(now.getTime()+2*86400000).toISOString().slice(0,10);
 r=await context.request.post(base+'/api/publico/monthly-browser/agendamentos',{data:{cliente_nome:'João Mensalista',cliente_telefone:'11944444444',barbeiro_id:'prof',servico_id:'corte',data:day,horario:'09:00'}});
 assert.equal(r.status(),201,await r.text());const aid=(await r.json()).agendamento_id;
 await page.goto(base+'/painel#assinaturas');
 await page.getByRole('heading',{name:'Assinaturas',exact:true}).waitFor();
 await page.locator('[data-month-tab=planos]').click();await page.locator('#monthly-new-plan').click();
 await page.locator('#monthly-plan-form [name=nome]').fill('Plano Premium');
 await page.locator('#monthly-plan-form [name=valor]').fill('179.90');
 await page.locator('[data-plan-service=corte]').check();
 await page.locator('[data-limit=corte]').fill('4');
 await page.locator('#monthly-plan-form button').click();
 await page.locator('#monthly-body').getByRole('heading',{name:'Plano Premium',exact:true}).waitFor();
 await page.locator('#app-shell [data-shell=clientes]').first().click();
 await page.locator('[data-client=11944444444]').click();
 await page.locator('#monthly-enroll').click();
 await page.locator('#monthly-enroll-form button').click();
 await page.locator('#shell-dialog-title').filter({hasText:'Assinatura · João Mensalista'}).waitFor();
 await page.getByRole('button',{name:'Confirmar pagamento',exact:true}).click();
 await page.locator('#monthly-payment-form [name=confirmado]').check();
 await page.locator('#monthly-payment-form button').click();
 await page.getByText('Pagamento registrado no caixa.',{exact:true}).waitFor();
 await page.locator('#shell-dialog [data-close-modal]').click();
 await page.locator('#app-shell [data-shell=agenda]').first().click();
 await page.locator('#filtro-data').fill(day);await page.locator('#filtro-data').dispatchEvent('change');
 const card=page.locator('[data-appointment="'+aid+'"]');
 await card.getByText(/INCLUÍDO NA ASSINATURA/).waitFor();
 await card.locator('[data-complete]').click();
 await page.getByRole('button',{name:'Confirmar utilização da assinatura',exact:true}).click();
 await card.getByText('Utilização registrada no plano',{exact:false}).waitFor();
 assert.equal((await (await context.request.get(base+'/api/agendamentos')).json()).find(x=>x.id===aid).incluido_assinatura,true);
 await page.locator('#app-shell [data-shell=assinaturas]').first().click();
 await page.locator('[data-month-tab=assinantes]').click();
 await page.getByText('1 / 4 utilizados · 3 restantes',{exact:true}).waitFor();
 await page.locator('[data-month-tab=dashboard]').click();
 await page.getByText('Receita recebida',{exact:true}).waitFor();
 assert.match(await page.locator('#monthly-body').innerText(),/179,90/);
 await fs.mkdir('test-results',{recursive:true});
 for(const scheme of ['light','dark']){
  // Change persisted theme through real API and sync after reload.
  r=await context.request.put(base+'/api/aparencia',{headers,data:{tema:scheme==='light'?'claro':'escuro'}});assert.equal(r.status(),200,await r.text());
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:960});await page.goto(base+'/painel#assinaturas');
   await page.getByRole('heading',{name:'Assinaturas',exact:true}).waitFor();
   await page.getByText('1 / 4 utilizados · 3 restantes',{exact:true}).waitFor();
   const dimensions=await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth}));
   assert.ok(dimensions.body<=dimensions.viewport+1,JSON.stringify(dimensions));
   await page.screenshot({path:'test-results/assinaturas-'+scheme+'-'+width+'.png',fullPage:true});
  }
 }
 // The existing product cash view includes the confirmed receipt.
 await page.goto(base+'/produtos?view=overview');await page.getByRole('heading',{name:'Faturamento por origem',exact:true}).waitFor();
 await page.getByText('Mensalidades recebidas:',{exact:false}).waitFor();
 assert.match(await page.locator('#content').innerText(),/Plano Premium/);
 // Actual public customer flow remains available.
 await page.goto(base+'/b/monthly-browser');await page.locator('#start-booking').click();
 await page.locator('#service-choices [data-choice=corte]').click();await page.locator('#continuar-servico').click();
 await page.locator('#professional-choices [data-choice=prof]').waitFor();
 // Re-login preserves saved appearance and subscription history.
 await context.request.post(base+'/api/logout',{headers});
 r=await context.request.post(base+'/api/login',{data:{email:'monthly-browser@example.com',senha:password}});assert.equal(r.status(),200,await r.text());
 await page.goto(base+'/painel#assinaturas');await page.getByText('1 / 4 utilizados · 3 restantes',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 await browser.close();console.log('OK: planos, adesão do cliente existente, pagamento, agenda, conclusão, limite, financeiro, temas e 3 tamanhos.');
})().catch(e=>{console.error(e);process.exit(1);});