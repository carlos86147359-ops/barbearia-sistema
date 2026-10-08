const assert=require('node:assert/strict'),{chromium}=require('playwright'),fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch(),base='http://127.0.0.1:8788',password='SenhaTeste!12345',errors=[];
 const owner=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true}),page=await owner.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 let r=await owner.request.post(base+'/api/cadastro',{data:{nome:'Foto Teste',slug:'photo-crop',email:'photo-owner@example.com',senha:password,aceite_termos:true}});assert.equal(r.status(),201,await r.text());
 const session=await (await owner.request.get(base+'/api/sessao')).json(),headers={'X-CSRF-Token':session.csrf};
 let cfg=await (await owner.request.get(base+'/api/configuracao')).json();
 const oldUrl='https://res.cloudinary.com/teste-cloud/image/upload/v1/antiga.png',photoUrl='https://res.cloudinary.com/teste-cloud/image/upload/v2/recortada.webp';
 Object.assign(cfg,{servicos:[{id:'corte',nome:'Corte',preco:35,duracao:30}],barbeiros:[{id:'prof',nome:'Carlos',foto_url:oldUrl},{id:'sem-foto',nome:'Bruno'}],dias:[0,1,2,3,4,5,6],periodos:[{inicio:'08:00',fim:'20:00'}]});
 r=await owner.request.put(base+'/api/configuracao',{headers,data:cfg});assert.equal(r.status(),200,await r.text());
 let sent=null,uploads=0,fail=true;
 const old=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jh1sAAAAASUVORK5CYII=','base64');
 async function cloud(route){await route.fulfill({contentType:route.request().url()===oldUrl?'image/png':'image/webp',body:route.request().url()===oldUrl?old:sent});}
 await page.route('https://res.cloudinary.com/teste-cloud/**',cloud);
 await page.route('**/api/imagens/status',route=>route.fulfill({json:{disponivel:true}}));
 await page.route('**/api/equipe/prof/foto',async route=>{
  if(route.request().method()!=='POST')return route.continue();
  uploads++;sent=route.request().postDataBuffer();assert.ok(sent.length<=120000);assert.equal(sent.toString('ascii',0,4),'RIFF');
  if(fail){fail=false;return route.fulfill({status:502,json:{detail:'Falha simulada. Tente novamente.'}});}
  const fresh=await (await owner.request.get(base+'/api/configuracao')).json();fresh.barbeiros[0].foto_url=photoUrl;
  const response=await owner.request.put(base+'/api/configuracao',{headers,data:fresh});assert.equal(response.status(),200,await response.text());
  await route.fulfill({json:{url:photoUrl,bytes:sent.length}});
 });
 async function team(){await page.goto(base+'/painel#equipe');await page.locator('#equipe-area [data-photo-pick]').first().waitFor();await page.waitForFunction(()=>!document.querySelector('#equipe-area [data-photo-pick]').disabled);}
 await team();
 const source=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=1200;c.height=800;const x=c.getContext('2d');x.fillStyle='#b32323';x.fillRect(0,0,400,800);x.fillStyle='#237d34';x.fillRect(400,0,400,800);x.fillStyle='#244ed0';x.fillRect(800,0,400,800);x.fillStyle='#eec98f';x.beginPath();x.ellipse(950,380,80,115,0,0,Math.PI*2);x.fill();return c.toDataURL('image/png').split(',')[1];});
 const file={name:'rosto.png',mimeType:'image/png',buffer:Buffer.from(source,'base64')};
 const editor=page.locator('#equipe-area [data-professional-photo=prof]');
 assert.equal(await editor.locator('img').getAttribute('src'),oldUrl);
 await editor.locator('[type=file]').setInputFiles(file);await page.locator('#photo-crop-dialog').waitFor();assert.equal(uploads,0);
 await page.locator('[data-crop-cancel]').click();assert.equal(uploads,0);assert.equal(await editor.locator('img').getAttribute('src'),oldUrl);
 await editor.locator('[type=file]').setInputFiles(file);await page.locator('#photo-crop-dialog').waitFor();
 const preview=page.locator('#photo-crop-dialog canvas');
 const sample=()=>preview.evaluate(c=>{const x=c.getContext('2d');return [...x.getImageData(256,256,1,1).data];});
 const before=await sample();
 await page.locator('#photo-crop-zoom').evaluate(e=>{e.value='2';e.dispatchEvent(new Event('input',{bubbles:true}));});
 const box=await preview.boundingBox(),cdp=await owner.newCDPSession(page);
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:box.x+box.width*.7,y:box.y+box.height*.5}]});
 await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:box.x+box.width*.1,y:box.y+box.height*.5}]});
 await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 const after=await sample();assert.notDeepEqual(after,before,'O toque deve alterar o enquadramento');
 const points=[[.2,.2],[.5,.5],[.7,.4],[.8,.8]];
 const expected=await preview.evaluate((c,points)=>points.map(([x,y])=>[...c.getContext('2d').getImageData(Math.floor(x*c.width),Math.floor(y*c.height),1,1).data]),points);
 const dims=await page.evaluate(()=>({view:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(dims.scroll<=dims.view+1);
 await fs.mkdir('test-results',{recursive:true});await page.screenshot({path:'test-results/photo-crop-editor-mobile.png'});
 await page.locator('[data-crop-save]').click();await editor.getByText('Falha simulada. Tente novamente.',{exact:true}).waitFor();assert.equal(uploads,1);
 assert.equal((await (await owner.request.get(base+'/api/configuracao')).json()).barbeiros[0].foto_url,oldUrl);
 // Confirmação gerou o mesmo enquadramento; reenvio usa o mesmo arquivo.
 const decoded=await page.evaluate(async ({bytes,points})=>{const b=await createImageBitmap(new Blob([new Uint8Array(bytes)],{type:'image/webp'}));const c=document.createElement('canvas');c.width=b.width;c.height=b.height;const x=c.getContext('2d');x.drawImage(b,0,0);const pixels=points.map(([u,v])=>[...x.getImageData(Math.floor(u*b.width),Math.floor(v*b.height),1,1).data]);const size=[b.width,b.height];b.close();return {size,pixels};},{bytes:[...sent],points});
 assert.equal(decoded.size[0],decoded.size[1]);assert.ok(decoded.size[0]<=512);
 decoded.pixels.forEach((p,i)=>p.slice(0,3).forEach((v,j)=>assert.ok(Math.abs(v-expected[i][j])<35,'Recorte salvo diferente da prévia')));
 const retry=Buffer.from(sent);await editor.locator('[data-photo-save]').click();await editor.getByText('Foto salva! Já aparece na escolha do profissional.').waitFor();assert.equal(uploads,2);assert.deepEqual(sent,retry);
 async function avatarCheck(p,selector,url){
  const img=p.locator(selector+' img').first();await img.waitFor();await img.evaluate(i=>i.decode());assert.equal(await img.getAttribute('src'),url);
  const values=await img.evaluate(i=>{const a=i.closest('.ui-avatar'),r=a.getBoundingClientRect(),style=getComputedStyle(i);return {w:r.width,h:r.height,fit:style.objectFit,position:style.objectPosition,radius:getComputedStyle(a).borderRadius};});
  assert.ok(Math.abs(values.w-values.h)<1,JSON.stringify(values));assert.equal(values.fit,'cover');assert.equal(values.position,'50% 50%');assert.equal(values.radius,'50%');
 }
 await avatarCheck(page,'#equipe-area [data-professional-avatar=prof]',photoUrl);
 await page.goto(base+'/painel#inicio');await page.reload();await avatarCheck(page,'#inicio-area [data-professional-avatar=prof]',photoUrl);
 await page.goto(base+'/painel#config');await page.reload();await page.locator('[data-config-section=config-profissionais]').click();await avatarCheck(page,'#profissionais [data-professional-avatar=prof]',photoUrl);
 // Cancela no editor de configurações e mantém o arquivo processado.
 await page.waitForFunction(()=>!document.querySelector('#profissionais [data-photo-pick]').disabled);
 await page.locator('#profissionais [data-professional-photo=prof] [type=file]').setInputFiles(file);await page.locator('#photo-crop-dialog').waitFor();await page.keyboard.press('Escape');assert.equal(uploads,2);
 const staff=await browser.newContext({viewport:{width:390,height:844}}),staffPage=await staff.newPage();staffPage.on('pageerror',e=>errors.push(e.message));await staffPage.route('https://res.cloudinary.com/teste-cloud/**',cloud);
 r=await owner.request.post(base+'/api/equipe/prof/convite',{headers,data:{email:'photo-staff@example.com'}});assert.equal(r.status(),201);
 const token=(await r.json()).link.split('#')[1];r=await staff.request.post(base+'/api/convite/aceitar',{data:{token,senha:password}});assert.equal(r.status(),201);
 for(const path of ['/painel#inicio','/painel#perfil']){await staffPage.goto(base+path);await staffPage.reload();await avatarCheck(staffPage,'[data-professional-avatar=prof]',photoUrl);}
 const day=new Date(Date.now()+2*86400000).toISOString().slice(0,10);
 r=await owner.request.post(base+'/api/publico/photo-crop/agendamentos',{data:{cliente_nome:'Cliente Foto',cliente_telefone:'11911112222',servico_id:'corte',barbeiro_id:'prof',data:day,horario:'09:00'}});assert.equal(r.status(),201);
 await page.goto(base+'/painel#agenda');await page.reload();await page.locator('#filtro-data').fill(day);await page.locator('#filtro-data').dispatchEvent('change');await page.locator('#agenda-group').click();await avatarCheck(page,'.agenda-column-title [data-professional-avatar=prof]',photoUrl);
 for(const width of [360,390,768,1440]){
  await page.setViewportSize({width,height:900});await page.goto(base+'/b/photo-crop');await page.locator('#start-booking').click();await page.locator('#service-choices [data-choice=corte]').click();await page.locator('#continuar-servico').click();
  await avatarCheck(page,'#professional-choices [data-professional-avatar=prof]',photoUrl);
  assert.equal(await page.locator('#professional-choices [data-professional-avatar=sem-foto]').innerText(),'B');
  const d=await page.evaluate(()=>({view:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(d.scroll<=d.view+1);
  await page.screenshot({path:'test-results/photo-public-'+width+'.png',fullPage:true});
 }
 // Foto antiga retangular ainda é aceita na configuração e exibida pela URL original.
 cfg=await (await owner.request.get(base+'/api/configuracao')).json();cfg.barbeiros[0].foto_url=oldUrl;
 r=await owner.request.put(base+'/api/configuracao',{headers,data:cfg});assert.equal(r.status(),200);
 await page.goto(base+'/b/photo-crop');await page.locator('#start-booking').click();await page.locator('#service-choices [data-choice=corte]').click();await page.locator('#continuar-servico').click();await avatarCheck(page,'#professional-choices [data-professional-avatar=prof]',oldUrl);
 assert.deepEqual(errors,[]);await browser.close();
 console.log('OK: cancelamento, toque real, zoom, pixels do recorte, 512px/120KB, falha/reenvio, equipe/config/dashboard/perfil/agenda/página pública, iniciais, fotos antigas e 4 larguras.');
})().catch(e=>{console.error(e);process.exit(1);});
