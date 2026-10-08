const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync('image-upload.js','utf8')+';this.crop=PhotoCropper;',ctx);
for(const [w,h] of [[1200,800],[800,1200],[400,400],[17,29]]){
 for(const zoom of [1,2,4])for(const cx of [-999,0,w/2,w,99999])for(const cy of [-999,0,h/2,h,99999]){
  const r=ctx.crop.rectangle(w,h,zoom,cx,cy);
  assert.ok(r.x>=0&&r.y>=0&&r.x+r.side<=w+.000001&&r.y+r.side<=h+.000001);
  assert.equal(r.side,Math.min(w,h)/zoom);
 }
}
const draws=[];let dimensions,attempts=0;
ctx.document={createElement:()=>{const c={getContext:()=>({drawImage:(...args)=>draws.push(args)}),toBlob:resolve=>{attempts++;resolve({type:'image/webp',size:attempts<5?120001:100000});}};dimensions=c;return c;}};
(async()=>{
 const image={width:1200,height:800},r=ctx.crop.rectangle(1200,800,2,900,400);
 const blob=await ctx.crop.encode(image,r);assert.ok(blob.size<=120000);
 assert.equal(dimensions.width,dimensions.height);assert.ok(dimensions.width<=512);
 for(const d of draws){assert.equal(d[3],d[4]);assert.equal(d[7],d[8]);assert.equal(d[1],r.x);assert.equal(d[2],r.y);}
 console.log('OK: recorte contido, zoom, posição, quadrado sem deformação e limite após enquadramento.');
})().catch(e=>{console.error(e);process.exit(1);});
