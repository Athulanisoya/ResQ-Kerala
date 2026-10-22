(() => {
  const SESSION_KEY = 'resq-week1-session';
  if (window.htmx) {
    window.htmx.config.historyCacheSize = 0;
    window.htmx.config.refreshOnHistoryMiss = true;
  }
  function readToken() {
    try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; }
  }
  function clearToken() {
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* Storage may be unavailable. */ }
  }
  function signedOut(notice) {
    clearToken();
    window.location.assign(`/login?notice=${notice === 'logout-unconfirmed' ? notice : 'signed-out'}`);
  }
  function showNetworkError(message) {
    const main = document.getElementById('main-content') || document.getElementById('app-root');
    if (!main || main.querySelector('[data-network-error]')) return;
    const alert = document.createElement('div');
    alert.className = 'alert alert-error'; alert.role = 'alert'; alert.dataset.networkError = 'true';
    alert.textContent = message;
    main.prepend(alert);
    let retry = main.querySelector('[data-retry-bootstrap]');
    if (!retry && !document.getElementById('main-content')) {
      retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'button button-secondary';
      retry.dataset.retryBootstrap = 'true'; retry.textContent = 'Try again';
      main.append(retry);
    }
    if (retry) retry.hidden = false;
  }
  function bootstrap() {
    if (!window.htmx) return;
    window.htmx.ajax('GET', window.location.pathname + window.location.search, {
      target: '#app-root', select: '#app-root', swap: 'outerHTML',
      headers: { 'X-ResQ-Page': 'true', 'X-ResQ-Bootstrap': 'true' },
    }).catch(() => showNetworkError('Unable to reach the server. Please try again.'));
  }
  document.addEventListener('htmx:configRequest', event => {
    event.detail.headers['X-ResQ-Page'] = 'true';
    const token = readToken();
    if (token) event.detail.headers.Authorization = `Bearer ${token}`;
  });
  document.addEventListener('htmx:beforeOnLoad', event => {
    if (isLogoutRequest(event) && event.detail.xhr.status !== 204) {
      event.preventDefault();
      signedOut('logout-unconfirmed');
      return;
    }
    if (event.detail.xhr.getResponseHeader('X-ResQ-Session') === 'expired') clearToken();
  });
  document.addEventListener('resq:authenticated', event => {
    try {
      sessionStorage.setItem(SESSION_KEY, event.detail.access_token);
      window.location.assign('/dashboard');
    } catch {
      showNetworkError('Allow session storage in this browser to sign in.');
    }
  });
  document.addEventListener('resq:signed-out', event => signedOut(event.detail.notice));
  document.addEventListener('click', event => {
    if (event.target.closest('[data-sign-in-again]')) {
      clearToken(); window.location.assign('/login');
    } else if (event.target.closest('[data-retry-bootstrap]')) bootstrap();
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) {
      const root = document.getElementById('app-root');
      if (root) root.textContent = 'Rechecking your session…';
      bootstrap();
    }
  });
  function refreshPage() {
    const root = document.getElementById('app-root');
    if (root) document.body.className = root.dataset.authenticated === 'true' ? 'workspace' : 'auth-page';
    const path = window.location.pathname;
    const active = path === '/reports/new' ? 'new' : path.startsWith('/reports') ? 'reports' : path === '/alerts' ? 'alerts' : path === '/account' ? 'account' : path === '/permissions' ? 'permissions' : path === '/updates' ? 'updates' : path === '/operations' ? 'operations' : path === '/assignments-history' ? 'history' : 'dashboard';
    document.querySelectorAll('[data-nav]').forEach(link => {
      const selected = link.dataset.nav === active;
      link.classList.toggle('active', selected);
      if (selected) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    document.querySelectorAll('[data-character-count]').forEach(counter => {
      const field = document.getElementById(counter.dataset.characterCount);
      if (!field) return;
      const update = () => { counter.textContent = `${field.value.length.toLocaleString()} / 5,000`; };
      if (!field.dataset.counterReady) { field.addEventListener('input', update); field.dataset.counterReady = 'true'; }
      update();
    });
  }
  document.addEventListener('DOMContentLoaded', () => {
    refreshPage();
    if (document.querySelector('[data-session-bootstrap]')) bootstrap();
  });
  document.addEventListener('htmx:afterSettle', event => {
    refreshPage();
    if (event.detail.target.id === 'main-content') {
      // The sidebar survives main-content swaps; HTMX owns its single polling timer.
      if (window.htmx) window.htmx.trigger(document.body, 'resq:refresh-updates');
      document.getElementById('main-content').focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'instant' });
      const heading = document.querySelector('#main-content h1, #main-content h2');
      if (heading) document.title = `${heading.textContent.trim()} · ResQ Kerala`;
    }
  });
  document.addEventListener('htmx:beforeSwap', event => {
    if ([400, 401, 403, 404, 409, 422, 503].includes(event.detail.xhr.status) && (event.detail.xhr.getResponseHeader('Content-Type') || '').includes('text/html')) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
  document.addEventListener('htmx:responseError', event => {
    showNetworkError('The request could not be completed. Please try again.');
  });
  function isLogoutRequest(event) {
    return event.detail?.requestConfig?.path === '/ui/logout' || event.detail?.elt?.getAttribute('action') === '/ui/logout';
  }
  function connectionFailed(event) {
    if (isLogoutRequest(event)) {
      signedOut('logout-unconfirmed');
    } else showNetworkError('Connection interrupted. Your form is still here; please try again.');
  }
  document.addEventListener('htmx:sendError', connectionFailed);
  document.addEventListener('htmx:timeout', connectionFailed);
})();
