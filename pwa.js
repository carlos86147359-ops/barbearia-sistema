(() => {
  let installation;
  const button = document.getElementById('instalar-app');
  const help = document.getElementById('ajuda-app');
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (standalone) document.getElementById('instalacao-app').hidden = true;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); installation = event;
    button.textContent = 'Instalar aplicativo';
  });
  button.onclick = async () => {
    if (!installation) { help.hidden = !help.hidden; return; }
    const prompt = installation; installation = null;
    try { await prompt.prompt(); await prompt.userChoice; }
    catch { help.hidden = false; }
    button.textContent = 'Como instalar no celular';
  };
  window.addEventListener('appinstalled', () => { document.getElementById('instalacao-app').hidden = true; });
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  const notice = document.getElementById('conexao-app');
  const update = () => { notice.hidden = navigator.onLine; };
  window.addEventListener('online', update); window.addEventListener('offline', update); update();
})();

