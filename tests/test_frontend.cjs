const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);new vm.Script(fs.readFileSync(path.join(root,'pwa.js'),'utf8'));
const route=script.slice(script.indexOf('async function entrada()'),script.indexOf('async function iniciar()'));
const guide=script.slice(script.indexOf('function etapasConfiguracao('),script.indexOf('function renderPrimeirosPassos('));
(async()=>{
  for(const status of [200,401,500]){
    let panel=false,form=false;
    const ctx={api:async()=>{if(status!==200)throw {status};},location:{replace:p=>{panel=p==='/painel';}},acesso:()=>{form=true;}};
    vm.createContext(ctx);vm.runInContext(route,ctx);
    if(status===500)await assert.rejects(ctx.entrada());else await ctx.entrada();
    assert.equal(panel,status===200);assert.equal(form,status===401);
  }
  const guideCtx={};vm.createContext(guideCtx);vm.runInContext(guide,guideCtx);
  const config={nome:'Loja',whatsapp:'',barbeiros:[],servicos:[],dias:[],periodos:[]};
  assert.equal(guideCtx.etapasConfiguracao(config,{ativa:false}).filter(s=>s.pronto).length,0);
  Object.assign(config,{whatsapp:'11999990000',barbeiros:[{}],servicos:[{}],dias:[0],periodos:[{}]});
  assert.equal(guideCtx.etapasConfiguracao(config,{ativa:false}).filter(s=>s.pronto).length,4);
  assert.equal(guideCtx.etapasConfiguracao(config,{ativa:true}).filter(s=>s.pronto).length,5);
  const events={},offline={page:'offline'},online={page:'online'},cacheReads=[];
  let networkFails=false;
  const ctx={self:{addEventListener:(name,fn)=>events[name]=fn},fetch:async()=>{if(networkFails)throw Error('offline');return online;},caches:{match:async name=>{cacheReads.push(name);return offline;}}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'sw.js'),'utf8'),ctx);
  let response;
  events.fetch({request:{method:'GET',mode:'navigate'},respondWith:p=>response=p});
  assert.equal(await response,online);assert.equal(cacheReads.length,0);
  networkFails=true;events.fetch({request:{method:'GET',mode:'navigate'},respondWith:p=>response=p});
  assert.equal(await response,offline);assert.equal(cacheReads[0],'/offline.html');
  for(const request of [{method:'POST',mode:'navigate'},{method:'GET',mode:'cors'}]){
    let intercepted=false;events.fetch({request,respondWith:()=>intercepted=true});assert.equal(intercepted,false);
  }
  const controls={'instalar-app':{},'ajuda-app':{hidden:true},'instalacao-app':{hidden:false},'conexao-app':{hidden:true}};
  const uiEvents={};const ui={document:{getElementById:id=>controls[id]},matchMedia:()=>({matches:false}),navigator:{onLine:true},window:{addEventListener:(name,fn)=>uiEvents[name]=fn}};
  vm.createContext(ui);vm.runInContext(fs.readFileSync(path.join(root,'pwa.js'),'utf8'),ui);
  await controls['instalar-app'].onclick();assert.equal(controls['ajuda-app'].hidden,false);
  ui.navigator.onLine=false;uiEvents.offline();assert.equal(controls['conexao-app'].hidden,false);
  ui.navigator.onLine=true;uiEvents.online();assert.equal(controls['conexao-app'].hidden,true);
  let prompted=false;uiEvents.beforeinstallprompt({preventDefault(){},prompt:async()=>prompted=true,userChoice:Promise.resolve({outcome:'dismissed'})});
  await controls['instalar-app'].onclick();assert.equal(prompted,true);assert.equal(controls['instalacao-app'].hidden,false);
  uiEvents.appinstalled();assert.equal(controls['instalacao-app'].hidden,true);
  console.log('OK: login, progresso, instalação, conexão e nenhuma alteração/API armazenada offline.');
})().catch(err=>{console.error(err);process.exitCode=1;});

