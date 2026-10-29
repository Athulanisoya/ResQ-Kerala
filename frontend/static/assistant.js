(() => {
  let restoreComposerFocus = false;
  function sizeComposer(field) {
    field.style.height = 'auto';
    field.style.height = `${Math.min(180, Math.max(48, field.scrollHeight))}px`;
  }
  function initializeChat() {
    document.querySelectorAll('[data-chat-composer]').forEach(sizeComposer);
    document.querySelectorAll('.chat-messages:not([data-chat-ready])').forEach(messages => {
      messages.dataset.chatReady = 'true';
      if (messages.querySelector('.chat-message')) messages.scrollTop = messages.scrollHeight;
    });
  }
  document.addEventListener('click', event => {
    const prompt = event.target.closest('[data-chat-prompt]');
    if (!prompt) return;
    const field = prompt.closest('.chat-workspace')?.querySelector('[data-chat-composer]');
    if (!field) return;
    field.value = prompt.dataset.chatPrompt;
    sizeComposer(field);
    field.focus();
  });
  document.addEventListener('input', event => {
    if (event.target.matches('[data-chat-composer]')) sizeComposer(event.target);
  });
  document.addEventListener('keydown', event => {
    if (!event.target.matches('[data-chat-composer]') || event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    const form = event.target.form;
    if (event.target.value.trim().length >= 2 && !form.classList.contains('htmx-request')) form.requestSubmit();
  });
  document.addEventListener('htmx:beforeRequest', event => {
    if (event.detail.elt?.matches('[data-chat-form]')) restoreComposerFocus = true;
  });
  document.addEventListener('htmx:afterSettle', event => {
    if (!['main-content', 'app-root'].includes(event.detail.target.id)) return;
    initializeChat();
    if (restoreComposerFocus) document.querySelector('[data-chat-composer]')?.focus({ preventScroll: true });
    restoreComposerFocus = false;
  });
  document.addEventListener('DOMContentLoaded', initializeChat);
})();
