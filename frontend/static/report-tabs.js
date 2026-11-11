(() => {
  const detailSelector = '[data-report-detail]';
  const panelSelector = '[data-report-panel]';
  const tabSelector = 'a[data-report-tab]';

  function activatePanel(detail, key) {
    const panels = Array.from(detail.querySelectorAll(panelSelector));
    const selected = panels.find(panel => panel.dataset.reportPanel === key);
    if (!selected) return null;

    for (const panel of panels) panel.hidden = panel !== selected;
    for (const tab of detail.querySelectorAll(tabSelector)) {
      if (tab.dataset.reportTab === key) tab.setAttribute('aria-current', 'location');
      else tab.removeAttribute('aria-current');
    }
    return selected;
  }

  function hashTarget() {
    if (!window.location.hash) return null;
    try {
      return document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    } catch {
      return null;
    }
  }

  function revealSection(detail, anchor) {
    const panel = anchor?.closest(panelSelector);
    const belongsToReport = panel && detail.contains(panel);
    activatePanel(detail, belongsToReport ? panel.dataset.reportPanel : 'overview');
    if (belongsToReport && anchor !== panel) {
      anchor.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  function syncFromLocation() {
    const detail = document.querySelector(detailSelector);
    if (detail) revealSection(detail, hashTarget());
  }

  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const tab = event.target.closest?.(tabSelector);
    const detail = tab?.closest(detailSelector);
    if (!detail) return;
    const panel = activatePanel(detail, tab.dataset.reportTab);
    if (!panel) return;

    event.preventDefault();
    window.history.replaceState(window.history.state, '', `#${panel.id}`);
  });

  document.addEventListener('DOMContentLoaded', syncFromLocation);
  window.addEventListener('hashchange', syncFromLocation);
  document.addEventListener('htmx:afterSettle', event => {
    const detail = document.querySelector(detailSelector);
    const target = event.detail?.target;
    if (!detail || !target) return;

    // An analysis or attachment fragment can contain a linked ID that did not
    // exist when the report first rendered.
    const anchor = hashTarget();
    if (target.id === 'app-root' || target.id === 'main-content' ||
        target.contains(detail) || (anchor && detail.contains(anchor) && target.contains(anchor))) {
      revealSection(detail, anchor);
    }
  }, true);

  document.addEventListener('htmx:beforeOnLoad', event => {
    if (event.defaultPrevented || event.detail?.requestConfig?.verb !== 'post') return;
    const form = event.detail.elt?.closest?.('form');
    const panel = form?.closest(panelSelector);
    const detail = panel?.closest(detailSelector);
    const xhr = event.detail.xhr;
    if (!detail || !/^\d+$/.test(detail.dataset.reportDetail) || xhr.status < 200 || xhr.status >= 300) return;

    const redirect = xhr.getResponseHeader('HX-Redirect');
    if (!redirect) return;
    let destination;
    try {
      destination = new URL(redirect, window.location.href);
    } catch {
      return;
    }
    const reportPath = `/reports/${detail.dataset.reportDetail}`;
    if (window.location.pathname !== reportPath || destination.origin !== window.location.origin || destination.pathname !== reportPath) return;

    event.preventDefault();
    destination.hash ||= panel.id;
    window.history.replaceState(window.history.state, '', destination);
    window.location.reload();
  });
})();
