(() => {
  let token = null;
  function populate() {
    const form = document.querySelector('#recovery-reset');
    if (!form) return;
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    if (fragment.has('token')) {
      token = fragment.get('token');
      history.replaceState(history.state, '', window.location.pathname + window.location.search);
    }
    const field = document.querySelector('#recovery-token');
    if (field && token) field.value = token;
  }
  document.addEventListener('DOMContentLoaded', populate);
  document.addEventListener('htmx:afterSwap', populate);
})();
