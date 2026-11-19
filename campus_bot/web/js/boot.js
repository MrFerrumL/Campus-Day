// Loads Telegram's Mini App script only when the page runs inside Telegram.
// In an ordinary browser the app does not need it, and an unreachable telegram.org
// would otherwise hold the whole page blank until the request times out.
// It must run before the modules, so it is a classic script that writes the tag in place.
(function () {
  var hash = location.hash + location.search;
  var saved = false;
  try { saved = !!sessionStorage.getItem('__telegram__initParams'); } catch (e) { /* storage blocked */ }
  var insideTelegram = /tgWebApp(Data|Platform|Version)/.test(hash) || saved
    || !!window.TelegramWebviewProxy || !!(window.external && 'notify' in window.external)
    || window.parent !== window;
  if (insideTelegram) {
    document.write('<script src="https://telegram.org/js/telegram-web-app.js"><\/script>');
  }
}());
