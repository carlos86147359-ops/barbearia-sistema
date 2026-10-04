const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.join(__dirname,'..');const ctx={document:{getElementById:()=>({})},window:{addEventListener(){}},Date,URLSearchParams,console};vm.createContext(ctx);
let source=fs.readFileSync(path.join(root,'produtos.js'),'utf8').replace("if(typeof window!=='undefined')boot();",'');vm.runInContext(source,ctx);
const run=s=>vm.runInContext(s,ctx);
assert.equal(run("CashMath.cents('19,90')"),1990);assert.equal(run("CashMath.cents('0.01')"),1);assert.equal(run("CashMath.total([{preco_centavos:1990,quantidade:3}],91)"),5879);
for(const value of ['-1','NaN','10.999','1e3','1.000,50'])assert.throws(()=>run(`CashMath.cents(${JSON.stringify(value)})`));
assert.throws(()=>run('CashMath.total([{preco_centavos:100,quantidade:1}],101)'));
assert.equal(run("JSON.stringify(CashMath.attrs('Cor=Preto; Tamanho=M'))"),'{"Cor":"Preto","Tamanho":"M"}');assert.throws(()=>run("CashMath.attrs('Cor=Preto; Cor=Azul')"));assert.throws(()=>run("CashMath.attrs('Tamanho')"));
console.log('OK: centavos, desconto, carrinho e variações genéricas.');

(async()=>{
 const storage=new Map(),elements={payment:{value:'credito'},discount:{value:'1.00'}},button={disabled:false};
 const messages=[],requests=[];let draft,details,freeze=0;
 ctx.document.getElementById=id=>id==='checkout'?{elements}:button;
 ctx.sessionStorage={setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)};
 ctx.crypto={randomUUID:()=> 'same-request-identifier-12345'};
 ctx.notice=(text,error)=>messages.push({text,error});
 ctx.freezePending=()=>freeze++;
 ctx.renderCartTotal=()=>{};
 ctx.newSale=value=>{draft=value;};
 ctx.show=async()=>{};
 ctx.saleDetails=value=>{details=value;};
 run("storageKey='test-user';cart=[{id:'a',preco_centavos:1000,quantidade:1}];catalog=[{variantes:[{id:'a',preco_centavos:1500}]}]");
 ctx.api=async(path,options)=>{if(path.endsWith('catalogo'))return run('catalog');requests.push(JSON.parse(options.body));const e=Error('Preço mudou');e.status=409;throw e;};
 await ctx.checkout();
 assert.equal(draft.pagamento,'credito');assert.equal(draft.desconto_centavos,100);
 assert.equal(run('cart[0].preco_centavos'),1500);assert.equal(run('pending'),null);assert.equal(storage.size,0);
 // A response lost after commit keeps the same request through retry AND reload.
 ctx.api=async(path,options)=>{requests.push(JSON.parse(options.body));const e=Error('Resposta perdida');e.uncertain=true;throw e;};
 await ctx.checkout();assert.equal(freeze,1);assert.equal(storage.size,1);
 const request=run('JSON.stringify(pending)');
 run('pending=null;cart=[];restorePending()');assert.equal(run('JSON.stringify(pending)'),request);assert.equal(run('cart.length'),1);
 ctx.api=async(path,options)=>{requests.push(JSON.parse(options.body));return {id:'sale-a',status:'confirmada'};};
 // A catalog failure after successful commit must never say that the sale failed.
 ctx.show=async()=>{throw Error('Catálogo indisponível');};
 await ctx.checkout();
 assert.deepEqual(requests.at(-1),JSON.parse(request));assert.equal(run('pending'),null);assert.equal(run('cart.length'),0);assert.equal(storage.size,0);assert.equal(details.id,'sale-a');
 assert.match(messages.at(-1).text,/Venda registrada/);
 // The record for another logged-in user must not be resumed.
 storage.set('test-user',JSON.stringify({estoque:{idempotencia:'stock-request-123456789',variante_id:'a'},cart:[]}));
 run("storageKey='other-user';restorePending()");assert.equal(run('pendingStock'),null);
 run("storageKey='test-user';restorePending()");assert.equal(run('pendingStock.variante_id'),'a');
 console.log('OK: preço atualizado preserva pagamento/desconto; resposta perdida/recarregamento não duplica venda; estoque pendente separado por usuário.');
})().catch(e=>{console.error(e);process.exitCode=1;});
