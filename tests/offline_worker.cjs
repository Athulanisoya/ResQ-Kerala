/* Deterministic service-worker fault/privacy checks. Run: node tests/offline_worker.cjs
 * Uses only Node built-ins; no running server, browser, or network is required.
 * Browser integration is covered separately by offline_reports_browser.cjs.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'static', 'offline-worker.js'), 'utf8');
const origin = 'http://127.0.0.1:8014';
const cacheName = 'resq-offline-report-v5';
const core = ['/offline/report-form', '/static/offline-reporting.js', '/static/offline.css', '/static/app.css', '/static/coast-canopy.css'];

function harness() {
  const listeners = {}, stores = new Map(), calls = [], deadlines = [];
  let network = async () => new Response('network'), skipped = 0, claimed = 0;
  const key = input => new URL(typeof input === 'string' ? input : input.url, origin).pathname;
  const open = async name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const entries = stores.get(name);
    return {
      put: async (input, response) => entries.set(key(input), {
        body: await response.arrayBuffer(), status: response.status, headers: [...response.headers],
      }),
      match: async input => {
        const data = entries.get(key(input));
        return data ? new Response(data.body.slice(0), { status: data.status, headers: data.headers }) : undefined;
      },
    };
  };
  const context = vm.createContext({
    self: {
      location: { origin }, addEventListener: (name, fn) => { listeners[name] = fn; },
      skipWaiting: () => { skipped++; }, clients: { claim: () => { claimed++; } },
    },
    caches: { open, keys: async () => [...stores.keys()], delete: async name => stores.delete(name) },
    fetch: async (input, options) => { calls.push(key(input)); return network(input, options); },
    Request, Response, Headers, URL, AbortController,
    // Exercise the real abort path promptly while retaining the configured deadlines.
    setTimeout: (fn, ms) => { deadlines.push(ms); return setTimeout(fn, Math.min(ms, 100)); },
    clearTimeout,
  });
  vm.runInContext(source, context, { filename: 'offline-worker.js' });
  return {
    stores, calls, deadlines,
    setNetwork(fn) { network = fn; },
    get skipped() { return skipped; },
    get claimed() { return claimed; },
    async life(name) {
      let pending;
      listeners[name]({ waitUntil(promise) { pending = promise; } });
      return pending;
    },
    async request(url, options = {}) {
      let answer;
      const waits = [];
      // The browser supplies navigation requests; the public Request constructor
      // deliberately cannot construct mode=navigate, so model that event directly.
      const request = {
        url: new URL(url, origin).href, method: options.method || 'GET',
        mode: options.mode || 'cors', headers: new Headers(options.headers || {}),
      };
      listeners.fetch({ request, respondWith(promise) { answer = promise; }, waitUntil(promise) { waits.push(promise); } });
      if (answer === undefined) return undefined;
      const response = await answer;
      await Promise.all(waits);
      return response;
    },
  };
}

async function main() {
  const results = [];
  const h = harness();
  h.setNetwork(async input => {
    const pathname = new URL(input.url).pathname;
    if (pathname.includes('favicon') || pathname.includes('/images/')) throw new Error('Optional asset unavailable');
    return new Response('public:' + pathname);
  });
  await h.life('install');
  assert.equal(h.skipped, 1);
  assert.deepEqual(h.calls.slice().sort(), core.slice().sort());
  assert.equal(h.stores.get(cacheName).size, core.length);
  results.push('installation succeeds without decorative background or favicon');

  h.stores.set('resq-offline-report-v4', new Map());
  h.stores.set('unrelated', new Map());
  await h.life('activate');
  assert(!h.stores.has('resq-offline-report-v4'));
  assert(h.stores.has('unrelated'));
  assert.equal(h.claimed, 1);
  results.push('activation removes obsolete report caches and preserves unrelated caches');

  h.setNetwork(async () => new Response('temporary', { status: 503 }));
  const form = await h.request('/reports/new', { mode: 'navigate' });
  assert.equal(form.status, 200);
  assert.equal(await form.text(), 'public:/offline/report-form');
  for (const asset of core.slice(1)) {
    const response = await h.request(asset);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), 'public:' + asset);
  }
  results.push('HTTP503 falls back to the cached incident form and every required asset');

  for (const status of [408, 425, 429, 500, 502, 504]) {
    h.setNetwork(async () => new Response('temporary', { status }));
    assert.equal(await (await h.request('/reports/new', { mode: 'navigate' })).text(), 'public:/offline/report-form');
  }
  results.push('HTTP408/425/429/500/502/504 navigation falls back to the cached form');

  const before = h.calls.length;
  for (const [url, options] of [
    ['/reports/new', { mode: 'navigate', headers: { Authorization: 'Bearer synthetic' } }],
    ['/static/app.css', { headers: { Authorization: 'Bearer synthetic' } }],
    ['/api/reports', {}],
    ['/api/reports', { headers: { Authorization: 'Bearer synthetic' } }],
    ['/api/reports', { method: 'POST' }],
    ['https://example.invalid/static/app.css', {}],
  ]) assert.equal(await h.request(url, options), undefined);
  assert.equal(h.calls.length, before);
  results.push('bearer requests, API data, POSTs and cross-origin requests are not intercepted');

  h.setNetwork(async () => new Response('Unauthorized', { status: 401 }));
  assert.equal((await h.request('/reports/new', { mode: 'navigate' })).status, 401);
  h.setNetwork(async () => new Response('PRIVATE_SYNTHETIC_MARKER'));
  assert.equal(await (await h.request('/reports/new', { mode: 'navigate' })).text(), 'PRIVATE_SYNTHETIC_MARKER');
  for (const entries of h.stores.values()) {
    assert(!entries.has('/reports/new'));
    for (const entry of entries.values()) assert(!Buffer.from(entry.body).toString().includes('PRIVATE_SYNTHETIC_MARKER'));
  }
  assert.equal(h.stores.get(cacheName).size, core.length);
  results.push('unauthorized navigation remains unauthorized and workspace HTML is never cached');

  const requestsBeforeRedirect = h.calls.length;
  const redirect = await h.request('/offline-report', { mode: 'navigate' });
  assert.equal(redirect.status, 303);
  assert.equal(redirect.headers.get('location'), origin + '/reports/new');
  assert.equal(h.calls.length, requestsBeforeRedirect);
  results.push('legacy offline route redirects to regular incident reporting without a network request');

  h.setNetwork(async (_input, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('headers aborted')), { once: true });
  }));
  assert.equal(await (await h.request('/reports/new', { mode: 'navigate' })).text(), 'public:/offline/report-form');
  h.setNetwork(async (_input, options) => new Response(new ReadableStream({
    start(controller) {
      options.signal.addEventListener('abort', () => controller.error(new Error('body aborted')), { once: true });
    },
  })));
  assert.equal(await (await h.request('/static/offline.css')).text(), 'public:/static/offline.css');
  assert(h.deadlines.includes(4000));
  assert(h.deadlines.includes(10000));
  results.push('stalled headers and stalled response bodies reach bounded cached fallback');

  const failing = harness();
  failing.stores.set('resq-offline-report-v4', new Map());
  failing.setNetwork(async input => new Response('asset', {
    status: new URL(input.url).pathname === '/static/offline.css' ? 503 : 200,
  }));
  await assert.rejects(failing.life('install'));
  assert.equal(failing.skipped, 0);
  assert(failing.stores.has('resq-offline-report-v4'));
  results.push('missing required asset rejects installation and retains the previous worker cache');

  for (const result of results) console.log('PASS ' + result);
  console.log(results.length + ' service-worker fault/privacy checks passed.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
