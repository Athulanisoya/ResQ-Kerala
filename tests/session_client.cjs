const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'static', 'app.js'), 'utf8');
const sessionKey = 'resq-week1-session';

// Each VM represents a browser tab with its own sessionStorage. The HTMX stub
// dispatches configRequest for every request, including an initial page load.
function createTab({ token = null, pathname = '/dashboard', search = '', bootstrapping = false, missingMain = false } = {}) {
  const storage = new Map([['draft-report', 'Keep this unfinished report']]);
  if (token) storage.set(sessionKey, token);
  const documentListeners = new Map();
  const windowListeners = new Map();
  const navigations = [];
  const requests = [];
  const triggers = [];
  let mainPresent = !missingMain;
  let failedRequests = 0;
  let rootText = 'Private report for the previous account';
  const root = {
    dataset: { authenticated: 'true' },
    children: [],
    get textContent() { return rootText; },
    set textContent(value) {
      rootText = String(value);
      this.children = [];
      // Setting a real ancestor's textContent removes its entire old subtree.
      mainPresent = false;
    },
    prepend(child) { this.children.unshift(child); },
    append(child) { this.children.push(child); },
    querySelector(selector) {
      if (selector === '[data-network-error]') return this.children.find(child => child.dataset.networkError) || null;
      if (selector === '[data-retry-bootstrap]') return this.children.find(child => child.dataset.retryBootstrap) || null;
      return null;
    },
  };
  const retry = { hidden: true };
  const main = {
    children: [],
    prepend(child) { this.children.unshift(child); },
    querySelector(selector) {
      if (selector === '[data-network-error]') return this.children.find(child => child.dataset.networkError) || null;
      if (selector === '[data-retry-bootstrap]') return retry;
      return null;
    },
    focus() {},
  };

  function addListener(listeners, name, callback) {
    if (!listeners.has(name)) listeners.set(name, []);
    listeners.get(name).push(callback);
  }
  function dispatch(listeners, name, event) {
    for (const callback of listeners.get(name) || []) callback(event);
    return event;
  }
  function emit(name, detail = {}, extra = {}) {
    return dispatch(documentListeners, name, {
      type: name, detail, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...extra,
    });
  }

  const document = {
    body: { className: '' },
    addEventListener(name, callback) { addListener(documentListeners, name, callback); },
    getElementById(id) { return id === 'app-root' ? root : id === 'main-content' && mainPresent ? main : null; },
    querySelector(selector) { return selector === '[data-session-bootstrap]' && bootstrapping ? {} : null; },
    querySelectorAll() { return []; },
    createElement(tagName) {
      return {
        tagName: tagName.toUpperCase(), dataset: {},
        closest(selector) { return selector === '[data-retry-bootstrap]' && this.dataset.retryBootstrap ? this : null; },
      };
    },
  };
  const htmx = {
    config: {},
    trigger(element, name) { triggers.push({ element, name }); },
    ajax(method, url, options = {}) {
      const detail = { headers: { ...options.headers } };
      emit('htmx:configRequest', detail);
      requests.push({ method, url, options, headers: detail.headers, visibleContent: root.textContent });
      if (failedRequests > 0) {
        failedRequests -= 1;
        return Promise.reject(new Error('Simulated connection failure'));
      }
      return Promise.resolve();
    },
  };
  const location = {
    pathname,
    search,
    assign(url) { navigations.push({ url, tokenAtNavigation: storage.get(sessionKey) || null }); },
  };
  const window = {
    htmx,
    location,
    scrollTo() {},
    addEventListener(name, callback) { addListener(windowListeners, name, callback); },
  };
  const sessionStorage = {
    getItem(key) { return storage.get(key) ?? null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  };
  vm.runInNewContext(source, { window, document, sessionStorage }, { filename: 'frontend/static/app.js' });

  return {
    emit,
    emitWindow(name, event = {}) { dispatch(windowListeners, name, { type: name, ...event }); },
    request(url = '/reports') { htmx.ajax('GET', url); return requests.at(-1); },
    token() { return storage.get(sessionKey) || null; },
    draft() { return storage.get('draft-report'); },
    failNextRequest() { failedRequests += 1; },
    hasMainContent() { return mainPresent; },
    root, main, retry, requests, triggers, navigations, config: htmx.config,
  };
}

function response(status, headers = {}) {
  return {
    status,
    getResponseHeader(name) {
      const match = Object.keys(headers).find(key => key.toLowerCase() === name.toLowerCase());
      return match ? headers[match] : null;
    },
  };
}

test('separate tabs send their own current credentials on each request', () => {
  const citizen = createTab({ token: 'citizen-session' });
  const admin = createTab({ token: 'admin-session' });
  assert.equal(citizen.request().headers.Authorization, 'Bearer citizen-session');
  assert.equal(admin.request().headers.Authorization, 'Bearer admin-session');
  citizen.emit('resq:authenticated', { access_token: 'new-citizen-session' });
  assert.equal(citizen.request().headers.Authorization, 'Bearer new-citizen-session');
  assert.equal(admin.request().headers.Authorization, 'Bearer admin-session');
  assert.equal(citizen.request().headers['X-ResQ-Page'], 'true');
});

test('successful authentication saves only the current tab before dashboard navigation', () => {
  const current = createTab();
  const other = createTab({ token: 'other-account-session' });
  current.emit('resq:authenticated', { access_token: 'created-account-session' });
  assert.equal(current.token(), 'created-account-session');
  assert.equal(current.navigations.at(-1).url, '/dashboard');
  assert.equal(current.navigations.at(-1).tokenAtNavigation, 'created-account-session');
  assert.equal(other.token(), 'other-account-session');
  assert.equal(other.navigations.length, 0);
});

test('confirmed logout removes current credentials and preserves other tabs and local drafts', () => {
  const current = createTab({ token: 'current-session' });
  const other = createTab({ token: 'other-session' });
  current.emit('resq:signed-out', { notice: 'signed-out' });
  assert.equal(current.token(), null);
  assert.equal(current.navigations.at(-1).url, '/login?notice=signed-out');
  assert.equal(current.navigations.at(-1).tokenAtNavigation, null);
  assert.equal(current.request().headers.Authorization, undefined);
  assert.equal(other.request().headers.Authorization, 'Bearer other-session');
  assert.equal(current.draft(), 'Keep this unfinished report');
});

test('server-reported unconfirmed logout clears current credentials and retains its warning', () => {
  const current = createTab({ token: 'current-session' });
  const other = createTab({ token: 'other-session' });
  current.emit('resq:signed-out', { notice: 'logout-unconfirmed' });
  assert.equal(current.token(), null);
  assert.equal(current.navigations.at(-1).url, '/login?notice=logout-unconfirmed');
  assert.equal(other.token(), 'other-session');
});

for (const failureEvent of ['htmx:sendError', 'htmx:timeout']) {
  test(`${failureEvent} during logout clears only the current tab and warns about revocation`, () => {
    const current = createTab({ token: 'current-session' });
    const other = createTab({ token: 'other-session' });
    current.emit(failureEvent, { requestConfig: { path: '/ui/logout' } });
    assert.equal(current.token(), null);
    assert.equal(current.navigations.at(-1).url, '/login?notice=logout-unconfirmed');
    assert.equal(other.token(), 'other-session');
    assert.equal(other.navigations.length, 0);
  });
}

test('a logout form network failure is recognized without a requestConfig path', () => {
  const current = createTab({ token: 'current-session' });
  const other = createTab({ token: 'other-session' });
  current.emit('htmx:sendError', { elt: { getAttribute(name) { return name === 'action' ? '/ui/logout' : null; } } });
  assert.equal(current.token(), null);
  assert.equal(current.navigations.at(-1).url, '/login?notice=logout-unconfirmed');
  assert.equal(other.token(), 'other-session');
});

for (const status of [500, 403]) {
  test(`HTTP ${status} during logout clears current credentials without rendering the response as confirmation`, () => {
    const current = createTab({ token: 'current-session' });
    const other = createTab({ token: 'other-session' });
    const event = current.emit('htmx:beforeOnLoad', {
      requestConfig: { path: '/ui/logout' },
      xhr: response(status, { 'Content-Type': 'text/html' }),
    });
    assert.equal(event.defaultPrevented, true);
    assert.equal(current.token(), null);
    assert.equal(current.navigations.at(-1).url, '/login?notice=logout-unconfirmed');
    assert.equal(current.navigations.at(-1).tokenAtNavigation, null);
    assert.equal(current.request().headers.Authorization, undefined);
    assert.equal(other.request().headers.Authorization, 'Bearer other-session');
    assert.equal(other.navigations.length, 0);
  });
}

test('a successful logout response remains available for the server signed-out event', () => {
  const current = createTab({ token: 'current-session' });
  const event = current.emit('htmx:beforeOnLoad', {
    requestConfig: { path: '/ui/logout' }, xhr: response(204),
  });
  assert.equal(event.defaultPrevented, false);
  assert.equal(current.navigations.length, 0);
  current.emit('resq:signed-out', { notice: 'signed-out' });
  assert.equal(current.token(), null);
  assert.equal(current.navigations.at(-1).url, '/login?notice=signed-out');
});

test('ordinary connection failure preserves both tab sessions and exposes a retry', () => {
  const current = createTab({ token: 'current-session' });
  const other = createTab({ token: 'other-session' });
  current.emit('htmx:sendError', { requestConfig: { path: '/reports' } });
  assert.equal(current.token(), 'current-session');
  assert.equal(other.token(), 'other-session');
  assert.equal(current.navigations.length, 0);
  assert.equal(current.retry.hidden, false);
  assert.match(current.main.children[0].textContent, /Connection interrupted/);
});

test('profile service failure renders recovery content without expiring either tab', () => {
  const current = createTab({ token: 'current-session' });
  const other = createTab({ token: 'other-session' });
  const xhr = response(503, { 'Content-Type': 'text/html' });
  current.emit('htmx:beforeOnLoad', { xhr });
  const swap = current.emit('htmx:beforeSwap', { xhr, shouldSwap: false, isError: true });
  assert.equal(swap.detail.shouldSwap, true);
  assert.equal(swap.detail.isError, false);
  assert.equal(current.token(), 'current-session');
  assert.equal(other.token(), 'other-session');
  assert.equal(current.navigations.length, 0);
});

test('an expired-session response clears only the affected tab before further requests', () => {
  const current = createTab({ token: 'expired-session' });
  const other = createTab({ token: 'valid-session' });
  current.emit('htmx:beforeOnLoad', { xhr: response(200, { 'X-ResQ-Session': 'expired' }) });
  assert.equal(current.token(), null);
  assert.equal(current.request().headers.Authorization, undefined);
  assert.equal(other.request().headers.Authorization, 'Bearer valid-session');
  assert.equal(current.draft(), 'Keep this unfinished report');
});

test('initial protected-page bootstrap sends tab authentication through the normal request hook', () => {
  const current = createTab({ token: 'current-session', pathname: '/reports', search: '?status=VERIFIED', bootstrapping: true });
  current.emit('DOMContentLoaded');
  assert.equal(current.requests.length, 1);
  const request = current.requests[0];
  assert.equal(request.method, 'GET');
  assert.equal(request.url, '/reports?status=VERIFIED');
  assert.equal(request.headers.Authorization, 'Bearer current-session');
  assert.equal(request.headers['X-ResQ-Page'], 'true');
  assert.equal(request.headers['X-ResQ-Bootstrap'], 'true');
  assert.equal(request.options.target, '#app-root');
  assert.equal(request.options.swap, 'outerHTML');
});

test('back-forward cache restoration removes previous private content before checking the tab session', () => {
  const current = createTab({ token: 'current-session', pathname: '/account' });
  const other = createTab({ token: 'other-session' });
  assert.equal(current.config.historyCacheSize, 0);
  assert.equal(current.config.refreshOnHistoryMiss, true);
  current.emitWindow('pageshow', { persisted: false });
  assert.equal(current.requests.length, 0);
  current.emitWindow('pageshow', { persisted: true });
  assert.equal(current.requests.length, 1);
  const request = current.requests[0];
  assert.doesNotMatch(request.visibleContent, /Private report/);
  assert.equal(request.url, '/account');
  assert.equal(request.headers.Authorization, 'Bearer current-session');
  assert.equal(request.headers['X-ResQ-Bootstrap'], 'true');
  assert.equal(other.token(), 'other-session');
});

test('a failed restored-page refresh leaves an accessible retry after the previous main content is removed', async () => {
  const current = createTab({ token: 'current-session', pathname: '/account' });
  const other = createTab({ token: 'other-session' });
  assert.equal(current.hasMainContent(), true);
  current.failNextRequest();
  current.emitWindow('pageshow', { persisted: true });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(current.hasMainContent(), false);
  assert.doesNotMatch(current.root.textContent, /Private report/);
  const alert = current.root.querySelector('[data-network-error]');
  const retryButton = current.root.querySelector('[data-retry-bootstrap]');
  assert.ok(alert);
  assert.equal(alert.role, 'alert');
  assert.match(alert.textContent, /Unable to reach the server/);
  assert.ok(retryButton);
  assert.equal(retryButton.tagName, 'BUTTON');
  assert.equal(retryButton.type, 'button');
  assert.equal(retryButton.textContent, 'Try again');
  assert.equal(retryButton.hidden, false);
  assert.equal(current.token(), 'current-session');
  assert.equal(other.token(), 'other-session');
  current.emit('click', {}, { target: retryButton });
  assert.equal(current.requests.length, 2);
  assert.equal(current.requests.at(-1).url, '/account');
  assert.equal(current.requests.at(-1).headers.Authorization, 'Bearer current-session');
  assert.equal(other.navigations.length, 0);
});

test('a restored protected page cannot reuse a token cleared by logout', () => {
  const current = createTab({ token: 'old-session' });
  const other = createTab({ token: 'other-session' });
  current.emit('resq:signed-out', { notice: 'signed-out' });
  current.emitWindow('pageshow', { persisted: true });
  assert.doesNotMatch(current.requests.at(-1).visibleContent, /Private report/);
  assert.equal(current.requests.at(-1).headers.Authorization, undefined);
  assert.equal(other.request().headers.Authorization, 'Bearer other-session');
});

test('choosing sign in again clears the current tab without affecting a parallel login', () => {
  const current = createTab({ token: 'current-session' });
  const other = createTab({ token: 'other-session' });
  current.emit('click', {}, { target: { closest(selector) { return selector === '[data-sign-in-again]' ? {} : null; } } });
  assert.equal(current.token(), null);
  assert.equal(current.navigations.at(-1).url, '/login');
  assert.equal(other.token(), 'other-session');
});

test('page swaps refresh unread updates without a badge response creating a refresh loop', () => {
  const current = createTab({ token: 'current-session', pathname: '/updates' });
  current.emit('htmx:afterSettle', { target: { id: 'main-content' } });
  assert.equal(current.triggers.length, 1);
  assert.equal(current.triggers[0].name, 'resq:refresh-updates');
  current.emit('htmx:afterSettle', { target: { id: 'updates-count' } });
  assert.equal(current.triggers.length, 1);
  assert.equal(current.request('/ui/updates/count').headers.Authorization, 'Bearer current-session');
});
