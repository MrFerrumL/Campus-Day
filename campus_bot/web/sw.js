// Lets the installed app open its shell without a network. Only the app's own
// files are cached; API answers (schedule, tasks, payments) never are.
const CACHE = 'campus-shell-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  const scope = new URL(self.registration.scope).pathname;
  const path = url.pathname.slice(scope.length);
  if (path.startsWith('api/') || path === 'health') return;
  // Network first, so a new release shows up at once; the cached copy is only a fallback.
  event.respondWith(fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  }).catch(() => caches.match(request, { ignoreSearch: true })));
});
