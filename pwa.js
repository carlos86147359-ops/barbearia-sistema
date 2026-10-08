(() => {
  let installation;
  const button = document.getElementById('instalar-app');
  const help = document.getElementById('ajuda-app');
  const section = document.getElementById('instalacao-app');
  const publicBooking = document.body?.dataset?.publicBooking === 'true';
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (standalone && section) section.hidden = true;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    if (publicBooking || !button || !help || !section) return;
    installation = event;
    button.textContent = 'Instalar aplicativo';
  });
  if (!publicBooking && button && help && section) {
    button.onclick = async () => {
      if (!installation) { help.hidden = !help.hidden; return; }
      const prompt = installation; installation = null;
      try { await prompt.prompt(); await prompt.userChoice; }
      catch { help.hidden = false; }
      button.textContent = 'Como instalar no celular';
    };
    window.addEventListener('appinstalled', () => { section.hidden = true; });
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
  const notice = document.getElementById('conexao-app');
  if (notice) {
    const update = () => { notice.hidden = navigator.onLine; };
    window.addEventListener('online', update); window.addEventListener('offline', update); update();
  }
})();
