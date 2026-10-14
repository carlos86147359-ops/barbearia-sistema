const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch();
 const context=await browser.newContext({viewport:{width:390,height:844}});
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:8788';
 const qrFixture=JSON.parse(await fs.readFile('test-results/pix-qr-fixture.json','utf8'));
 const r=await context.request.post(base+'/api/cadastro',{data:{nome:'Teste Contratação',slug:'billing-browser',email:'billing-browser@example.test',senha:'SenhaTeste!12345',aceite_termos:true}});
 assert.equal(r.status(),201,await r.text());
 const session=await (await context.request.get(base+'/api/sessao')).json();
 let state={disponivel:true,ambiente:'production',valor_centavos:6000,vendas_habilitadas:true,contratos:[],pagamentos:[],pix_disponivel:true,ciclos_promocionais_restantes:3};
 // Mock somente do provedor/contratação, sem rede financeira, em servidor temporário.
 await page.route('**/api/saas/assinatura',route=>route.fulfill({json:state}));
 await page.route('**/api/saas/checkout',async route=>{
  requests.push(route.request().postDataJSON());
  state.contratos=[{id:'test-contract',ambiente:'production',status:'checkout',forma_pagamento:route.request().postDataJSON().forma_pagamento||'CREDIT_CARD',valor_centavos:6000,checkout_url:'https://www.asaas.com/checkoutSession/show?id=test',condicoes:{ultimo_vencimento:'2027-01-13'}}];
  await route.fulfill({json:state.contratos[0]});
 });
 await page.route('**/api/saas/contratos/*/pix',route=>route.fulfill({json:{situacao:'pendente',payload:qrFixture.payload,valor_centavos:6000,expira_em:'2099-01-01T23:59:59-03:00',matriz:qrFixture.matriz}}));
 await page.route('https://www.asaas.com/checkoutSession/show?**',route=>route.fulfill({contentType:'text/html',body:'<h1>PIX hospedado de teste</h1>'}));
 await page.goto(base+'/painel#plano');await page.reload();
 await page.getByRole('heading',{name:'Minha assinatura',exact:true}).waitFor();
 await page.locator('[data-real-contract]').click();
 await page.getByRole('button',{name:'Aceitar e abrir checkout',exact:true}).click();
 await page.getByRole('link',{name:'Continuar no checkout seguro',exact:true}).waitFor();
 assert.equal(requests.length,1);
 assert.equal(requests[0].aceite_condicoes,'tres_meses_60_depois_nova_contratacao_90_v1');
 assert.match(await page.locator('#asaas-sandbox').innerText(),/nova contratação de R\$ 90/);
 await fs.mkdir('test-results',{recursive:true});
 for(const theme of ['claro','escuro']){
  const response=await context.request.put(base+'/api/aparencia',{headers:{'X-CSRF-Token':session.csrf},data:{tema:theme}});assert.equal(response.status(),200);
  for(const width of [390,768,1440]){
   await page.setViewportSize({width,height:900});await page.reload();
   await page.getByRole('link',{name:'Continuar no checkout seguro',exact:true}).waitFor();
   const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
   assert.ok(size.scroll<=size.width+1,JSON.stringify(size));
   await page.screenshot({path:'test-results/cobranca-'+theme+'-'+width+'.png',fullPage:true});
  }
 }
 state={...state,contratos:[]};
 await page.reload();
 await page.locator('[data-pix-contract]').click();
 await page.getByRole('button',{name:'Aceitar e abrir PIX',exact:true}).click();
 await page.waitForURL('https://www.asaas.com/checkoutSession/show?id=test');
 await page.getByRole('heading',{name:'PIX hospedado de teste',exact:true}).waitFor();
 assert.equal(requests[1].forma_pagamento,'PIX');
 assert.equal(requests[1].aceite_pix,'pix_mensal_sem_debito_automatico_v1');
 await page.goto(base+'/painel#plano');
 await page.getByRole('link',{name:'Abrir QR Code e código PIX',exact:true}).waitFor();
 const pixImage=page.getByRole('img',{name:'QR Code PIX da mensalidade',exact:true});
 await pixImage.waitFor();
 state.contratos[0].status='expirada';await page.reload();await pixImage.waitFor();
 for(const width of [360,390,768,1440]){
  await page.setViewportSize({width,height:900});
  const box=await pixImage.boundingBox();assert.ok(box&&box.width>150&&Math.abs(box.width-box.height)<2);
  const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert.ok(size.scroll<=size.width+1);
  await page.screenshot({path:'test-results/pix-local-'+width+'.png',fullPage:true});
 }
 await pixImage.screenshot({path:'test-results/pix-qr-renderizado.png'});
 assert.equal(await page.locator('[data-pix-code]').inputValue(),qrFixture.payload);
 await page.getByRole('button',{name:'Atualizar QR Code',exact:true}).click();
 await pixImage.waitFor();
 state={...state,valor_centavos:9000,contratos:[],vendas_habilitadas:false};
 await page.reload();await page.getByRole('button',{name:'Contratar R$ 90/mês',exact:true}).waitFor();
 assert.equal(await page.locator('[data-real-contract]').isDisabled(),true);
 assert.equal(errors.length,0,errors.join('\n'));
 await browser.close();console.log('OK: aceite, checkout hospedado, oferta, bloqueio, temas e responsividade da cobrança.');
})().catch(e=>{console.error(e);process.exit(1)});
