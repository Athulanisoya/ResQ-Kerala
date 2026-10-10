(() => {
  if (window.htmx) window.htmx.config.historyCacheSize = 0;
  function refreshPage() {
    const path = window.location.pathname;
    const active = path === '/reports/new' ? 'new' : path.startsWith('/reports') ? 'reports' : 'dashboard';
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
  document.addEventListener('DOMContentLoaded', refreshPage);
  document.addEventListener('htmx:afterSettle', event => {
    refreshPage();
    if (event.detail.target.id === 'main-content') {
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
    const main = document.getElementById('main-content');
    if (!main || main.querySelector('[data-network-error]')) return;
    const alert = document.createElement('div');
    alert.className = 'alert alert-error'; alert.role = 'alert'; alert.dataset.networkError = 'true';
    alert.textContent = 'The request could not be completed. Please try again.';
    main.prepend(alert);
  });
  document.addEventListener('htmx:sendError', () => {
    const main = document.getElementById('main-content');
    if (!main || main.querySelector('[data-network-error]')) return;
    const alert = document.createElement('div');
    alert.className = 'alert alert-error'; alert.role = 'alert'; alert.dataset.networkError = 'true';
    alert.textContent = 'Connection interrupted. Your form is still here; please try again.';
    main.prepend(alert);
  });
})();
