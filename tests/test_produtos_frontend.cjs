const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.join(__dirname,'..');const ctx={document:{getElementById:()=>({})},window:{addEventListener(){}},Date,URLSearchParams,console};vm.createContext(ctx);
let source=fs.readFileSync(path.join(root,'produtos.js'),'utf8').replace("if(typeof window!=='undefined')boot();",'');vm.runInContext(source,ctx);
const run=s=>vm.runInContext(s,ctx);
assert.equal(run("CashMath.cents('19,90')"),1990);assert.equal(run("CashMath.cents('0.01')"),1);assert.equal(run("CashMath.total([{preco_centavos:1990,quantidade:3}],91)"),5879);
for(const value of ['-1','NaN','10.999','1e3','1.000,50'])assert.throws(()=>run(`CashMath.cents(${JSON.stringify(value)})`));
assert.throws(()=>run('CashMath.total([{preco_centavos:100,quantidade:1}],101)'));
assert.equal(run("JSON.stringify(CashMath.attrs('Cor=Preto; Tamanho=M'))"),'{"Cor":"Preto","Tamanho":"M"}');assert.throws(()=>run("CashMath.attrs('Cor=Preto; Cor=Azul')"));assert.throws(()=>run("CashMath.attrs('Tamanho')"));
console.log('OK: centavos, desconto, carrinho e variações genéricas.');
