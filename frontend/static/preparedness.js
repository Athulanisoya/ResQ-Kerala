(() => {
  let originals = null;
  function prepare() {
    if (originals || !document.querySelector('.preparedness-print-only')) return;
    const nodes = [document.documentElement, document.body, document.getElementById('app-root'),
      document.querySelector('.workspace-body'), document.getElementById('main-content')].filter(Boolean);
    originals = nodes.map(node => [node, node.getAttribute('style')]);
    // Chromium can retain the theme's canvas colour during print preview. Set
    // an explicit canvas and restore the exact inline styles after printing.
    nodes.forEach(node => {
      node.style.setProperty('background', '#fff', 'important');
      node.style.setProperty('background-image', 'none', 'important');
    });
    document.body.style.setProperty('isolation', 'auto', 'important');
  }
  function restore() {
    originals?.forEach(([node, value]) => {
      if (value === null) node.removeAttribute('style'); else node.setAttribute('style', value);
    });
    originals = null;
  }
  window.addEventListener('beforeprint', prepare);
  window.addEventListener('afterprint', restore);
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-print-plan]')) return;
    prepare();
    try { window.print(); } catch { restore(); }
  });
})();
