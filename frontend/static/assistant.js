(() => {
  let restoreComposerFocus = false;
  let retryForm = null;
  let pendingForm = null;
  const resumeUrl = '/assistant?widget=1&resume=1';
  let lastLoadUrl = resumeUrl;
  let loading = false;
  function widget() { return document.getElementById('assistant-widget'); }
  function panel() { return document.getElementById('assistant-widget-panel'); }
  function isWidgetRequest(event) {
    return event.detail?.target?.id === 'assistant-widget-content'
      || Boolean(event.detail?.elt?.closest?.('#assistant-widget'));
  }
  function requestForm(event) {
    const candidate = event.detail?.elt;
    if (candidate?.matches?.('[data-chat-form]')) return candidate;
    return pendingForm?.isConnected ? pendingForm : null;
  }
  function sizeComposer(field) {
    field.style.height = 'auto';
    const maximum = field.closest('#assistant-widget') ? 120 : 180;
    field.style.height = `${Math.min(maximum, Math.max(48, field.scrollHeight))}px`;
  }
  function showPendingTurn(form) {
    const field = form.querySelector('[data-chat-composer]');
    const messages = form.closest('.chat-workspace')?.querySelector('.chat-messages');
    if (!field || !messages || messages.querySelector('[data-chat-pending-turn]')) return;
    field.readOnly = true;
    const turn = document.createElement('article');
    turn.className = 'chat-message chat-message-user';
    turn.dataset.chatPendingTurn = '';
    turn.setAttribute('aria-label', 'Your pending message');
    const body = document.createElement('div');
    body.className = 'chat-message-body';
    const author = document.createElement('div');
    author.className = 'chat-message-author';
    author.textContent = 'You';
    const content = document.createElement('div');
    content.className = 'chat-message-content';
    content.textContent = field.value.trim();
    body.append(author, content);
    turn.append(body);
    messages.append(turn);
    messages.classList.add('chat-messages-sending');
    messages.scrollTop = messages.scrollHeight;
  }
  function finishPendingTurn(form) {
    if (!form) return;
    const field = form.querySelector('[data-chat-composer]');
    if (field) field.readOnly = false;
    const messages = form.closest('.chat-workspace')?.querySelector('.chat-messages');
    messages?.querySelector('[data-chat-pending-turn]')?.remove();
    messages?.classList.remove('chat-messages-sending');
  }
  function showNotice(message, form = null, retryable = true) {
    const root = widget();
    if (!root) return;
    retryForm = form;
    root.querySelector('[data-widget-notice-text]').textContent = message;
    root.querySelector('[data-widget-retry]').hidden = !retryable;
    root.querySelector('[data-widget-notice]').hidden = false;
  }
  function clearNotice() {
    const root = widget();
    if (root) root.querySelector('[data-widget-notice]').hidden = true;
    retryForm = null;
  }
  function minimize() {
    if (!widget()) return;
    panel().hidden = true;
    document.getElementById('assistant-widget-launcher').setAttribute('aria-expanded', 'false');
    document.getElementById('assistant-widget-launcher').focus({ preventScroll: true });
  }
  function loadConversation(url = lastLoadUrl) {
    const root = widget();
    if (!root || loading || !window.htmx) return;
    if (root.dataset.widgetPending === 'true') {
      showNotice('Please wait for this reply before switching conversations.', null, false);
      return;
    }
    lastLoadUrl = url;
    loading = true;
    root.dataset.widgetLoadState = 'loading';
    clearNotice();
    window.htmx.ajax('GET', url, {
      target: '#assistant-widget-content', swap: 'innerHTML',
      headers: { 'X-ResQ-Page': 'true' },
    }).catch(() => {
      loading = false;
      if (!root.isConnected) return;
      root.dataset.widgetLoadState = root.querySelector('[data-assistant-widget-response]') ? 'loaded' : 'empty';
      showNotice('Unable to open this conversation. Please try again.');
    });
  }
  function openWidget(url = null) {
    const root = widget();
    if (!root) return;
    panel().hidden = false;
    document.getElementById('assistant-widget-launcher').setAttribute('aria-expanded', 'true');
    initializeChat();
    if (url || root.dataset.widgetLoadState === 'empty') {
      root.querySelector('[data-widget-minimize]').focus({ preventScroll: true });
      loadConversation(url || lastLoadUrl);
    } else {
      const field = root.querySelector('[data-chat-composer]');
      (field || root.querySelector('[data-widget-minimize]')).focus({ preventScroll: true });
    }
  }
  function initializeChat() {
    document.querySelectorAll('[data-chat-composer]').forEach(sizeComposer);
    document.querySelectorAll('.chat-messages:not([data-chat-ready])').forEach(messages => {
      if (!messages.getClientRects().length) return;
      messages.dataset.chatReady = 'true';
      if (messages.querySelector('.chat-message')) messages.scrollTop = messages.scrollHeight;
    });
    const root = widget();
    if (!root || root.dataset.widgetAutoOpened) return;
    const query = new URLSearchParams(window.location.search);
    if (query.get('chat') !== '1') return;
    root.dataset.widgetAutoOpened = 'true';
    const sessionId = query.get('session_id');
    openWidget(/^[1-9]\d*$/.test(sessionId || '')
      ? `/assistant?widget=1&session_id=${encodeURIComponent(sessionId)}` : resumeUrl);
  }
  // Capture legacy assistant links before HTMX navigates the main workspace.
  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href]');
    const root = widget();
    if (!link || !root) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin || url.pathname !== '/assistant' || link.target === '_blank') return;
    if (link.closest('#assistant-widget')) {
      if (root.dataset.widgetPending === 'true') {
        event.preventDefault(); event.stopPropagation();
        showNotice('Please wait for this reply before switching conversations.', null, false);
      }
      return;
    }
    event.preventDefault(); event.stopPropagation();
    if (url.searchParams.has('session_id')) {
      url.searchParams.set('widget', '1');
      openWidget(url.pathname + url.search);
    } else openWidget();
  }, true);
  document.addEventListener('click', event => {
    if (event.target.closest('[data-widget-launcher]')) {
      if (panel()?.hidden) openWidget(); else minimize();
      return;
    }
    if (event.target.closest('[data-widget-minimize]')) { minimize(); return; }
    if (event.target.closest('[data-widget-retry]')) {
      const form = retryForm;
      clearNotice();
      if (form?.isConnected && !form.classList.contains('htmx-request')) form.requestSubmit();
      else loadConversation();
      return;
    }
    const historyToggle = event.target.closest('[data-widget-history-toggle]');
    if (historyToggle) {
      const history = document.getElementById('assistant-widget-history');
      history.hidden = !history.hidden;
      historyToggle.setAttribute('aria-expanded', history.hidden ? 'false' : 'true');
      return;
    }
    const prompt = event.target.closest('[data-chat-prompt]');
    if (!prompt) return;
    const field = prompt.closest('.chat-workspace')?.querySelector('[data-chat-composer]');
    if (!field || field.readOnly) return;
    field.value = prompt.dataset.chatPrompt;
    sizeComposer(field); field.focus();
  });
  document.addEventListener('input', event => {
    if (event.target.matches('[data-chat-composer]')) sizeComposer(event.target);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel()?.hidden && event.target.closest('#assistant-widget')) {
      event.preventDefault(); minimize(); return;
    }
    if (!event.target.matches('[data-chat-composer]') || event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    const form = event.target.form;
    if (!event.target.readOnly && event.target.value.trim().length >= 2 && !form.classList.contains('htmx-request')) form.requestSubmit();
  });
  document.addEventListener('htmx:configRequest', event => {
    if (isWidgetRequest(event) || event.detail.elt?.matches('[data-chat-form]')) event.detail.timeout ||= 60000;
  });
  document.addEventListener('htmx:beforeSend', event => {
    if (event.detail.elt?.matches('[data-chat-form]')) showPendingTurn(event.detail.elt);
  });
  document.addEventListener('htmx:beforeRequest', event => {
    if (event.detail.elt?.matches('[data-chat-form]')) restoreComposerFocus = true;
    if (!isWidgetRequest(event)) return;
    pendingForm = event.detail.elt?.matches?.('[data-chat-form]') ? event.detail.elt : null;
    clearNotice();
    const root = widget();
    if (root) {
      root.dataset.widgetPending = 'true';
      root.querySelectorAll('.chat-new, .chat-history-item').forEach(link => link.setAttribute('aria-disabled', 'true'));
    }
    const path = event.detail.requestConfig?.path;
    if (typeof path === 'string' && path.startsWith('/assistant')) lastLoadUrl = path;
  });
  document.addEventListener('htmx:beforeSwap', event => {
    if (!isWidgetRequest(event)) return;
    const xhr = event.detail.xhr;
    if (xhr.getResponseHeader('HX-Redirect')) return;
    const html = (xhr.getResponseHeader('Content-Type') || '').includes('text/html');
    if (html && xhr.responseText.includes('data-assistant-widget-response')) return;
    event.detail.shouldSwap = false; event.detail.isError = false; loading = false;
    const form = requestForm(event);
    showNotice(xhr.status === 403 ? 'Your form could not be verified. Your message is still here; reopen the conversation or sign in again.' : 'The assistant could not complete that request. Your message is still here.', form);
  });
  document.addEventListener('htmx:afterRequest', event => {
    if (event.detail.elt?.matches('[data-chat-form]')) finishPendingTurn(event.detail.elt);
    if (!isWidgetRequest(event)) return;
    loading = false;
    const root = widget();
    if (root) {
      root.dataset.widgetPending = 'false';
      root.dataset.widgetLoadState = root.querySelector('[data-assistant-widget-response]') ? 'loaded' : 'empty';
      root.querySelectorAll('.chat-new, .chat-history-item').forEach(link => link.removeAttribute('aria-disabled'));
    }
  });
  function connectionFailed(event) {
    if (!isWidgetRequest(event)) return;
    loading = false;
    const form = requestForm(event);
    showNotice(form ? 'Connection interrupted. Your message is still here; try sending it again.' : 'Unable to load your conversations. Please try again.', form);
  }
  document.addEventListener('htmx:sendError', connectionFailed);
  document.addEventListener('htmx:timeout', connectionFailed);
  document.addEventListener('htmx:sendAbort', connectionFailed);
  document.addEventListener('htmx:afterSettle', event => {
    if (!['main-content', 'app-root', 'assistant-widget-content'].includes(event.detail.target.id)) return;
    initializeChat();
    if (event.detail.target.id === 'assistant-widget-content') {
      clearNotice();
      pendingForm = null;
      const root = widget();
      if (root) {
        root.dataset.widgetLoadState = root.querySelector('[data-assistant-widget-response]') ? 'loaded' : 'empty';
        if (!panel().hidden && (restoreComposerFocus || root.contains(document.activeElement))) root.querySelector('[data-chat-composer]')?.focus({ preventScroll: true });
      }
    } else if (restoreComposerFocus && !widget()) document.querySelector('[data-chat-composer]')?.focus({ preventScroll: true });
    restoreComposerFocus = false;
  });
  document.addEventListener('DOMContentLoaded', initializeChat);
})();
