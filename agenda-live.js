/* Atualização compartilhada pela agenda do dono e do profissional. */
const AgendaLive=(()=>{
 let stopCurrent=()=>{};
 function start({active,fetchRows,current,render,status,expired}){
  stopCurrent();let stopped=false,busy=false,timer=null,controller=null,failures=0;
  const schedule=()=>{clearTimeout(timer);if(!stopped)timer=setTimeout(refresh,Math.min(60000,10000*2**failures));};
  async function refresh(){
   if(stopped||busy)return;
   clearTimeout(timer);
   if(document.hidden||!active()){schedule();return;}
   if(navigator.onLine===false){status('Sem conexão. A agenda será atualizada ao reconectar.');schedule();return;}
   busy=true;controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000);
   try{
    const rows=await fetchRows(controller.signal);
    if(stopped||document.hidden||!active())return;
    if(JSON.stringify(rows)!==JSON.stringify(current()))render(rows);
    failures=0;status('Atualização automática · conferida às '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}));
   }catch(err){
    if(stopped)return;
    if(err.status===401){stop();expired();return;}
    failures=Math.min(failures+1,3);status('Não foi possível conferir a agenda. Tentaremos novamente automaticamente.');
   }finally{clearTimeout(timeout);controller=null;busy=false;schedule();}
  }
  const resume=()=>{if(!document.hidden)refresh();};
  const offline=()=>status('Sem conexão. A agenda será atualizada ao reconectar.');
  const pause=()=>{clearTimeout(timer);controller?.abort();};
  function stop(){stopped=true;clearTimeout(timer);controller?.abort();document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);window.removeEventListener('offline',offline);window.removeEventListener('pagehide',pause);window.removeEventListener('pageshow',resume);}
  document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);window.addEventListener('offline',offline);window.addEventListener('pagehide',pause);window.addEventListener('pageshow',resume);
  stopCurrent=stop;status('Atualização automática a cada 10 segundos.');schedule();return {refresh,stop};
 }
 return {start,stop:()=>stopCurrent()};
})();
