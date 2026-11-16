/* Public assets only: never cache bearer requests, API data, or workspace HTML. */
const CACHE = 'resq-offline-report-v6';
const SHELL = '/offline/report-form';
const CORE = [SHELL, '/static/offline-reporting.js', '/static/offline.css', '/static/app.css', '/static/coast-canopy.css', '/static/typography.css'];
// Decorative downloads must never prevent offline reporting from becoming ready.
const ASSETS = [...CORE, '/static/favicon.svg', '/static/images/kerala-coast-canopy.jpg'];
async function boundedResponse(request, timeout) {
  const controller = new AbortController(), deadline = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(request, { signal: controller.signal });
    const body = [204, 205, 304].includes(response.status) ? null : await response.arrayBuffer();
    const headers = new Headers(response.headers);
    headers.delete('content-encoding'); headers.delete('content-length');
    return new Response(body, { status: response.status, statusText: response.statusText, headers });
  } finally { clearTimeout(deadline); }
}
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => Promise.all(CORE.map(async url => {
    const response = await boundedResponse(new Request(new URL(url, self.location.origin), { cache: 'reload' }), 10000);
    if (!response.ok) throw new Error('The incident form could not be prepared offline.');
    await cache.put(url, response);
  }))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key =>
    key.startsWith('resq-offline-report-') && key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request, url = new URL(request.url);
  if (url.origin !== self.location.origin || request.method !== 'GET' || request.headers.has('Authorization')) return;
  if (request.mode === 'navigate' && url.pathname === '/offline-report') {
    event.respondWith(Promise.resolve(Response.redirect(new URL('/reports/new', self.location.origin).href, 303)));
  } else if (request.mode === 'navigate' && url.pathname === '/reports/new') {
    event.respondWith(boundedResponse(request, 4000).then(response => {
      if (response.status >= 500 || [408, 425, 429].includes(response.status)) throw new Error('Incident form temporarily unavailable');
      return response;
    }).catch(() => caches.open(CACHE).then(cache => cache.match(SHELL))));
  } else if (ASSETS.includes(url.pathname) && url.pathname !== SHELL) {
    event.respondWith(boundedResponse(request, CORE.includes(url.pathname) ? 4000 : 10000).then(response => {
      if (response.status >= 500 || [408, 425, 429].includes(response.status)) throw new Error('Public asset temporarily unavailable');
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(caches.open(CACHE).then(cache => cache.put(url.pathname, copy)).catch(() => {}));
      }
      return response;
    }).catch(() => caches.open(CACHE).then(cache => cache.match(url.pathname))));
  }
});
