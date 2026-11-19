(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.createCampusTransport = factory;
})(globalThis, function createCampusTransport({fetchImpl = fetch, initData = () => '', timeoutMs = 25000} = {}) {
  async function once(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl('./api/' + path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
        cache: 'no-store', signal: controller.signal,
        headers: {'X-Telegram-Init-Data': initData(), 'X-Campus-Session': '1', 'Content-Type': 'application/json'},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})
      });
      let result;
      try { result = await response.json(); }
      catch { throw new Error('Сервер временно недоступен. Повторите запрос.'); }
      if (!response.ok) {
        const error = new Error(result.error || 'Не удалось выполнить запрос');
        error.status = response.status;
        throw error;
      }
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Соединение прервалось. Нажмите ↻, чтобы обновить.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  return async function request(path, body) {
    try { return await once(path, body); }
    catch (error) {
      // A 403 precedes mutation, so an authenticated retry cannot duplicate a save.
      // A refused login link is final: renewing the Telegram session cannot help it.
      if (error.status === 403 && path !== 'session' && path !== 'login') {
        await once('session', {});
        return once(path, body);
      }
      // Network failures after writes are ambiguous: never automatically replay them.
      if (body === undefined && !error.status) return once(path, body);
      throw error;
    }
  };
});
