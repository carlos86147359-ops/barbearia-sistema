const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
for(const file of ['panel-ux.js','app-shell.js','produtos.js','mensalistas.js'])new vm.Script(fs.readFileSync(path.join(root,file),'utf8'));
module.exports=async function(){
 const nodes=new Map(),metrics=[];
 const ctx={Intl,Date,Map,Set,URLSearchParams,encodeURIComponent,today:()=> '2026-10-05',money:n=>Number(n).toFixed(2),esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),sessao:{papel:'dono',slug:'teste'},config:{nome:'Loja',barbeiros:[]},reservas:[],assinaturaInfo:{ativa:true},etapasConfiguracao:()=>[{pronto:true}],document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',querySelectorAll:()=>[]});return nodes.get(id);}},UI:{icon:()=>'',avatar:()=>'',professional:()=>'',empty:()=>''},AppShell:{heading:()=>'',metric:(...x)=>{metrics.push(x);return '';}},api:async()=>{throw Error('offline');}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'promocoes.js'),'utf8'),ctx);vm.runInContext(fs.readFileSync(path.join(root,'mensalistas.js'),'utf8')+';this.monthly=Monthly;',ctx);vm.runInContext(fs.readFileSync(path.join(root,'panel-ux.js'),'utf8'),ctx);const run=s=>vm.runInContext(s,ctx);
 ctx.reservas=[{id:1,inicio:'2026-10-05T09:00',status:'concluido',preco:45,comissao_pct:40,cliente_nome:'Jo�o',cliente_telefone:'(61) 98888-0000'},{id:2,inicio:'2026-10-05T10:00',status:'cancelado',preco:99,cliente_nome:'Jo�o',cliente_telefone:'5561988880000'},{id:3,inicio:'2026-10-06T11:00',status:'agendado',preco:70,cliente_nome:'Jo�o atualizado',cliente_telefone:'61988880000'}];
 run('homeProducts={total_centavos:3050,vendas:1,estoque_baixo:[]}');await ctx.renderHome(false);
 assert.equal(metrics.find(x=>x[0]==='Faturamento hoje')[1],'75.50');assert.equal(metrics.find(x=>x[0]==='Vendas de produtos')[1],'30.50');
 metrics.length=0;
 run('homeProducts.assinaturas_centavos=8990');ctx.reservas[0].incluido_assinatura=true;
 await ctx.renderHome(false);assert.equal(metrics.find(x=>x[0]==='Faturamento hoje')[1],'120.40');assert.equal(ctx.clientGroups()[0].total,0);
 delete ctx.reservas[0].incluido_assinatura;
 assert.throws(()=>ctx.monthly.completion({protecao_assinatura:true}),/autorização/);
 ctx.api=async()=>({permissoes:{assinaturas_ver:true,assinaturas_utilizar:true},dono:true});await ctx.monthly.init();
 assert.equal(ctx.monthly.completion({protecao_assinatura:true,cliente_nome:'Cliente',servico_nome:'Corte',assinatura:{plano:'Premium'}}).use,true);
 assert.equal(ctx.monthly.completion({cliente_nome:'Cliente'}).use,false);
 ctx.api=async()=>{throw Error('offline');};await ctx.monthly.init();
 const clients=ctx.clientGroups();assert.equal(clients.length,1);assert.equal(clients[0].nome,'Jo�o atualizado');assert.equal(clients[0].completed.length,1);assert.equal(clients[0].total,45);
 assert.equal(run("datePlus('2026-12-29',6)"),'2027-01-04');
 ctx.sessao.papel='barbeiro';run("caixaAccess={permissoes:{acessar_pdv:false}};perfilAtual={profissional:'Carlos'}");
 let ids=ctx.panelItems().map(x=>x.id);assert.deepEqual(Array.from(ids),['inicio','agenda','clientes','financeiro','notificacoes','perfil']);
 run('caixaAccess={permissoes:{acessar_pdv:true,ver_estoque:true,registrar_venda:false}}');ids=ctx.panelItems().map(x=>x.id);assert(ids.includes('estoque'));assert(!ids.includes('config'));assert(ctx.panelItems().find(x=>x.id==='caixa').href.endsWith('view=sales'));
 metrics.length=0;await ctx.renderHome(false);assert.equal(metrics.length,2);assert(!metrics.some(x=>x[0].includes('Faturamento')));
 // Every configured accent retains a readable foreground and link color.
 const vars={};ctx.document.body={style:{setProperty:(k,v)=>vars[k]=v}};vm.runInContext(fs.readFileSync(path.join(root,'design-system.js'),'utf8'),ctx);
 const lum=hex=>hex.match(/[a-f\d]{2}/gi).map(x=>parseInt(x,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
 for(const color of ['#000000','#ffffff','#ff0000','#0000ff','#dfa94d']){run(`UI.accent('${color}')`);const a=lum(vars['--gold']),b=lum(vars['--on-accent']);assert((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5);assert(lum(vars['--accent-text'])>=.3);}
 console.log('OK: painel por papel, centavos/reais, clientes normalizados, per�odo semanal e contraste.');
};
if(require.main===module)module.exports().catch(e=>{console.error(e);process.exitCode=1;});
