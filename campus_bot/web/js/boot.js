// Telegram includes signed init data in the launch fragment. Send the original
// string to the API even if the optional SDK is blocked or slow.
(() => {
  const key = '__telegram__initParams';
  const launch = () => {
    const hash = location.hash.slice(1);
    const params = new URLSearchParams(hash.slice(hash.indexOf('?') + 1));
    return Object.fromEntries(params);
  };
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(key) || '{}') || {}; } catch { /* storage unavailable */ }

  const hasLaunch = params => ['tgWebAppData', 'tgWebAppPlatform', 'tgWebAppVersion'].some(name => name in params);
  const initial = launch();
  if (hasLaunch(initial)) {
    saved = initial;
    try {
      // Save only Telegram launch parameters, never browser sign-in links.
      const params = Object.fromEntries(Object.entries(initial).filter(([name]) => name.startsWith('tgWebApp')));
      sessionStorage.setItem(key, JSON.stringify(params));
    } catch { /* storage unavailable */ }
  }

  const sdk = () => window.Telegram?.WebApp;
  const initData = () => {
    const current = launch();
    if (hasLaunch(current)) return current.tgWebAppData || '';
    return sdk()?.initData || saved.tgWebAppData || '';
  };
  const native = () => window.TelegramWebviewProxy?.postEvent || window.external?.notify;
  const embedded = () => !!(initData() || hasLaunch(initial) || hasLaunch(saved) || native());

  function ready() {
    if (sdk()) return;
    try {
      if (window.TelegramWebviewProxy?.postEvent) {
        window.TelegramWebviewProxy.postEvent('web_app_ready', '');
      } else if (window.external?.notify) {
        window.external.notify(JSON.stringify({ eventType: 'web_app_ready', eventData: '' }));
      } else if (window.parent !== window) {
        window.parent.postMessage(JSON.stringify({ eventType: 'web_app_ready' }), 'https://web.telegram.org');
      }
    } catch { /* continue even if the client bridge is unavailable */ }
  }

  window.campusTelegram = { initData, embedded, ready };
  if (sdk() || (!embedded() && window.parent === window)) return;
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://telegram.org/js/telegram-web-app.js';
  script.addEventListener('load', () => window.dispatchEvent(new Event('campus-telegram-sdk')));
  document.head.append(script);
})();
