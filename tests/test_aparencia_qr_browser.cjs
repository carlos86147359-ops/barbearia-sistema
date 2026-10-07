const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch();
 await fs.mkdir('test-results',{recursive:true});
 const errors=[];
 const context=await browser.newContext({viewport:{width:1440,height:960},colorScheme:'dark',acceptDownloads:true});
 const page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:8788';
 const password='SenhaTeste!12345';
 let r=await context.request.post(base+'/api/cadastro',{data:{aceite_termos:true,nome:'Barbearia Teste',slug:'teste-qr',email:'qr-browser@example.com',senha:password}});
 assert.equal(r.status(),201,await r.text());
 const session=await (await context.request.get(base+'/api/sessao')).json();
 const cfg=await (await context.request.get(base+'/api/configuracao')).json();
 cfg.servicos=[{id:'corte',nome:'Corte',preco:35,duracao:30}];
 cfg.barbeiros=[{id:'prof',nome:'Profissional'}];
 cfg.cor_principal='#dfa94d';
 r=await context.request.put(base+'/api/configuracao',{headers:{'X-CSRF-Token':session.csrf},data:cfg});
 assert.equal(r.status(),200,await r.text());
 async function profile(){await page.goto(base+'/painel#perfil');await page.reload();await page.getByRole('heading',{name:'Aparência',exact:true}).waitFor();}
 async function theme(value){await page.locator('[data-appearance-choice="'+value+'"]').click();await page.getByText('Preferência salva na sua conta.',{exact:true}).waitFor();}
 await profile();
 await theme('claro');
 assert.equal(await page.locator('html').getAttribute('data-theme'),'claro');
 assert.equal((await (await context.request.get(base+'/api/aparencia')).json()).tema,'claro');
 await page.screenshot({path:'test-results/perfil-claro.png',fullPage:true});
 await page.reload();await page.getByRole('heading',{name:'Aparência',exact:true}).waitFor();
 assert.equal(await page.locator('html').getAttribute('data-theme'),'claro');
 await theme('escuro');
 assert.equal(await page.locator('html').getAttribute('data-theme'),'escuro');
 await page.screenshot({path:'test-results/perfil-escuro.png',fullPage:true});
 await theme('sistema');
 await page.emulateMedia({colorScheme:'light'});
 await page.waitForFunction(()=>document.documentElement.dataset.theme==='claro');
 assert.equal(await page.locator('html').getAttribute('data-theme'),'claro');
 await page.emulateMedia({colorScheme:'dark'});
 await page.waitForFunction(()=>document.documentElement.dataset.theme==='escuro');
 assert.equal(await page.locator('html').getAttribute('data-theme'),'escuro');
 await theme('claro');
 await page.locator('#profile-logout').click();
 await page.waitForURL('**/entrar');
 assert.equal(await page.locator('html').getAttribute('data-theme'),'claro');
 await page.locator('input[name=email]').fill('qr-browser@example.com');
 await page.locator('input[name=senha]').fill(password);
 await page.locator('#form-acesso button[type=submit],#form-acesso button:not([type])').click();
 await page.waitForURL(/\/painel(?:#.*)?$/);
 await profile();
 assert.equal(await page.locator('html').getAttribute('data-theme'),'claro');
 await page.locator('#app-shell [data-shell=qr]').first().click();
 await page.locator('.qr-preview').waitFor();
 await page.locator('.qr-preview').evaluate(img=>img.decode());
 assert.equal(await page.locator('.qr-link a').getAttribute('href'),base+'/b/teste-qr');
 const download=page.waitForEvent('download');
 await page.getByRole('link',{name:'Baixar QR Code'}).click();
 const file=await download;assert.equal(await file.failure(),null);
 await file.saveAs('test-results/qr-agendamento.png');
 await page.goto(base+'/qr-agendamento/imprimir');
 await page.locator('.qr').evaluate(img=>img.decode());
 await page.emulateMedia({media:'print'});
 assert.equal(await page.locator('.tools').isVisible(),false);
 await page.pdf({path:'test-results/cartaz-a4.pdf',format:'A4',printBackground:true});
 await page.emulateMedia({media:'screen'});
 for(const mode of ['claro','escuro']){
 await profile();await theme(mode);
 for(const viewport of [{width:1440,height:960},{width:768,height:1024},{width:390,height:844}]){
  await page.setViewportSize(viewport);
  for(const path of ['/painel#inicio','/painel#agenda','/painel#clientes','/painel#financeiro','/painel#config','/painel#qr','/produtos','/b/teste-qr']){
   await page.goto(base+path);
   if(path.startsWith('/painel'))await page.reload();
   await page.waitForFunction(()=>!document.body.textContent.includes('Carregando sua área')&&!document.body.textContent.includes('Gerando seu QR Code'));
   await page.waitForTimeout(500);
   assert.equal(await page.locator('html').getAttribute('data-theme'),mode);
   const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
   assert.ok(sizes.scroll<=sizes.width+1,path+': '+JSON.stringify(sizes));
   await page.screenshot({path:'test-results/'+mode+'-'+viewport.width+'-'+path.replace(/[^a-z0-9]/gi,'_')+'.png',fullPage:true});
  }
 }
 }
 // Outro dono, outro contexto e preferência independente.
 const other=await browser.newContext({colorScheme:'dark'});
 r=await other.request.post(base+'/api/cadastro',{data:{aceite_termos:true,nome:'Outra Loja',slug:'outra-qr',email:'other-qr@example.com',senha:password}});
 assert.equal(r.status(),201);
 assert.equal((await (await other.request.get(base+'/api/aparencia')).json()).tema,'sistema');
 assert.equal((await (await other.request.get(base+'/api/qr-agendamento')).json()).url,base+'/b/outra-qr');
 assert.deepEqual(errors,[]);
 await browser.close();
 console.log('OK: browser real, temas, sistema, logout/login, download, PDF, páginas e três larguras.');
})().catch(e=>{console.error(e);process.exit(1);});
