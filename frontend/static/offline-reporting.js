/* The queue contains incident data, never credentials. Authentication stays per tab. */
(() => {
  'use strict';
  const TOKEN = 'resq-week1-session', OWNER = 'resq-offline-owner-v1';
  const REQUEST_TIMEOUT = 10000, RETRY_MIN = 1000, RETRY_MAX = 30000;
  let database, syncing = false, editing = null, editingRevision = null, signingOut = false;
  let retryTimer = null, retryAt = 0, retryDelay = RETRY_MIN, syncAgain = false;
  let rejectedToken = null, redirectCandidate = null, currentStatus = '', lastOwner = null;
  let preparing = false, prepared = false;
  let activeRequest = null;
  const labels = { DRAFT: 'Draft · not sent', QUEUED: 'Waiting to send', ERROR: 'Needs attention', SENT: 'Submitted' };
  const form = () => document.querySelector('[data-offline-form]');
  const token = () => { try { return sessionStorage.getItem(TOKEN); } catch { return null; } };
  function owner() {
    try {
      const root = document.getElementById('app-root');
      if (root?.dataset.userId) {
        if (root.dataset.userRole !== 'citizen') { sessionStorage.removeItem(OWNER); return null; }
        const id = Number(root.dataset.userId);
        sessionStorage.setItem(OWNER, String(id));
        return id;
      }
      const bearer = token(), saved = Number(sessionStorage.getItem(OWNER)) || null;
      if (!bearer || !saved) return null;
      // This unverified claim is only a device-display hint. The server's /me
      // result is mandatory before sending. It prevents a replaced tab token
      // from opening a previously signed-in account's local queue.
      const claims = JSON.parse(atob(bearer.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return Number(claims.sub) === saved ? saved : null;
    } catch { return null; }
  }
  function status(message) {
    currentStatus = message;
    document.querySelectorAll('[data-offline-status]').forEach(node => { node.textContent = message; });
  }
  function updateCharacterCount() {
    const message = form()?.elements.namedItem('message');
    const counter = document.querySelector('[data-character-count="message"]');
    if (message && counter) counter.textContent = `${message.value.length.toLocaleString()} / 5,000`;
  }
  function db() {
    if (!database) database = new Promise((resolve, reject) => {
      if (!window.indexedDB) return reject(new Error('Offline storage is unavailable in this browser.'));
      const request = indexedDB.open('resq-offline-v1', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('reports', { keyPath: 'id' });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('Offline storage could not be opened. Your form has not been sent.'));
      request.onblocked = () => reject(new Error('Close older ResQ tabs to prepare offline storage.'));
    });
    return database;
  }
  async function transaction(mode, action) {
    const connection = await db();
    return new Promise((resolve, reject) => {
      const tx = connection.transaction('reports', mode), request = action(tx.objectStore('reports'));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = tx.onabort = () => reject(new Error('The device could not save this report. Free storage and try again; keep this form open.'));
    });
  }
  const all = async id => (await transaction('readonly', store => store.getAll())).filter(row => row.owner === id).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const remove = id => transaction('readwrite', store => store.delete(id));
  async function changeRecord(id, userId, change, create = false) {
    const connection = await db();
    return new Promise((resolve, reject) => {
      const tx = connection.transaction('reports', 'readwrite'), records = tx.objectStore('reports');
      const read = records.get(id); let result = null, failure;
      read.onsuccess = () => {
        const current = read.result;
        if ((!current && !create) || (current && current.owner !== userId)) return;
        try {
          result = change(current);
          if (result) { result.revision = (current?.revision || 0) + 1; records.put(result); }
        } catch (error) { failure = error; tx.abort(); }
      };
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(failure || new Error('The device could not save this report. Keep this form open and try again.'));
    });
  }
  function samePayload(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  async function requestJson(url, options) {
    const controller = new AbortController();
    activeRequest = controller;
    const deadline = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    try {
      const response = await fetch(url, { ...options, cache: 'no-store', signal: controller.signal });
      // Keep the deadline until the complete body arrives, not just its headers.
      const data = response.ok ? await response.json() : null;
      // Error bodies are not displayed. Stop a stalled stream before retrying.
      if (!response.ok) controller.abort();
      return { response, data };
    } finally { clearTimeout(deadline); if (activeRequest === controller) activeRequest = null; }
  }
  function requestSync({ immediate = false, reset = false } = {}) {
    if (signingOut) return;
    if (reset) retryDelay = RETRY_MIN;
    if (syncing) { syncAgain = true; return; }
    const delay = immediate ? 0 : retryDelay, due = Date.now() + delay;
    if (retryTimer && retryAt <= due) return;
    clearTimeout(retryTimer); retryAt = due;
    retryTimer = setTimeout(() => { retryTimer = null; void sync(); }, delay);
  }
  function payloadFromForm(node) {
    const data = new FormData(node), affected = String(data.get('people_affected') || '').trim();
    return { disaster_type: 'Flood', location: String(data.get('location') || '').trim(),
      message: String(data.get('message') || '').trim(), people_affected: affected === '' ? null : Number(affected),
      help_required: String(data.get('help_required') || '').trim() || null };
  }
  function validate(payload) {
    return payload.location.length >= 2 && payload.location.length <= 255 && payload.message.length >= 5 && payload.message.length <= 5000
      && (payload.people_affected === null || (Number.isInteger(payload.people_affected) && payload.people_affected >= 0 && payload.people_affected <= 100000))
      && (!payload.help_required || payload.help_required.length <= 255);
  }
  async function save(queued) {
    const node = form(), id = owner();
    if (node?.getAttribute('aria-busy') === 'true') return;
    if (!node || !id || !token()) { status('Sign in online with your citizen account before saving or sending a report.'); return; }
    if (queued && !node.reportValidity()) return;
    const payload = payloadFromForm(node);
    if (queued && !validate(payload)) { status('Check the location, description, and number of people before sending.'); return; }
    node.setAttribute('aria-busy', 'true');
    try {
      const rows = await all(id), previous = rows.find(row => row.id === editing);
      if (previous?.locked) throw new Error('This report has already been attempted. Retry it from the waiting list to avoid duplicate submissions.');
      if (!previous && rows.length >= 30) throw new Error('This device has 30 stored reports. Remove submitted receipts or unwanted drafts to make room.');
      const row = { id: previous?.id || crypto.randomUUID(), owner: id, payload, state: queued ? 'QUEUED' : 'DRAFT',
        createdAt: previous?.createdAt || new Date().toISOString(), updatedAt: new Date().toISOString(), locked: false };
      const saved = await changeRecord(row.id, id, current => {
        if (previous && (!current || current.locked || !['DRAFT', 'ERROR'].includes(current.state)
            || (current.revision || 0) !== editingRevision)) throw new Error('This draft changed in another tab. Reload the saved draft before editing it again.');
        if (!previous && current) throw new Error('This saved report already exists. Reload before trying again.');
        return row;
      }, !previous);
      if (!saved) throw new Error('This draft was removed or changed. Keep the form open and save a new draft.');
      editing = null; editingRevision = null; node.reset(); updateCharacterCount();
      redirectCandidate = queued && navigator.onLine ? row.id : null;
      status(queued ? 'Report saved in the waiting queue. It is not submitted until a server receipt is shown.' : 'Draft saved on this device. It has not been sent.');
      await render();
      if (queued) requestSync({ immediate: true, reset: true });
    } catch (error) { status(error.message); }
    finally { node.removeAttribute('aria-busy'); }
  }
  function element(tag, text, className) {
    const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node;
  }
  async function render() {
    const lists = document.querySelectorAll('[data-offline-records]'); if (!lists.length) return;
    const id = owner(), bearer = token();
    lists.forEach(node => node.replaceChildren());
    if (!id || !token()) { status('Sign in online with a citizen account to open your drafts.'); return; }
    try {
      const rows = await all(id);
      if (owner() !== id || token() !== bearer) return;
      for (const list of lists) {
        if (!rows.length) list.append(element('p', 'No reports stored for this account on this device.', 'empty-copy'));
        for (const row of rows) {
          const article = element('article', '', 'offline-record'); article.dataset.offlineId = row.id;
          article.append(element('span', labels[row.state] || 'Needs attention', 'offline-state'));
          article.append(element('h3', row.state === 'SENT' ? row.reference || 'Submitted report' : row.payload.location || 'Untitled draft'));
          if (row.payload) article.append(element('p', row.payload.message.slice(0, 180) || 'No description yet.'));
          article.append(element('p', `Saved ${new Date(row.updatedAt).toLocaleString()}`));
          if (row.error) article.append(element('p', row.error));
          const actions = element('div', '', 'offline-record-actions');
          const button = (label, action) => { const node = element('button', label, 'button button-secondary'); node.type = 'button'; node.dataset.offlineAction = action; node.dataset.id = row.id; actions.append(node); };
          if (!row.locked && ['DRAFT', 'ERROR'].includes(row.state)) button('Edit draft', 'edit');
          if (row.state !== 'SENT') button(row.state === 'DRAFT' ? 'Send this draft' : 'Retry submission', 'send');
          if (row.state === 'SENT') { const link = element('a', 'View report', 'button button-primary'); link.href = `/reports/${Number(row.serverId)}`; actions.append(link); }
          button(row.state === 'SENT' ? 'Remove receipt from device' : 'Remove from device', 'remove');
          article.append(actions); list.append(article);
        }
      }
    } catch (error) { status(error.message); }
  }
  async function sync() {
    if (syncing) { syncAgain = true; return; }
    const id = owner(), bearer = token();
    if (!id || !bearer || signingOut) return;
    if (rejectedToken === bearer) { status('Sign in again with the same citizen account to deliver your saved waiting reports.'); return; }
    syncing = true; syncAgain = false;
    let retry = false, hadWork = false;
    const unchangedAttempt = (current, attempt) => current?.state === 'QUEUED' && samePayload(current.payload, attempt.payload);
    async function waitingError(attempt, message) {
      await changeRecord(attempt.id, id, current => unchangedAttempt(current, attempt) ? { ...current, error: message, locked: true } : null);
      status(message); retry = true;
    }
    try {
      const waiting = (await all(id)).filter(row => row.state === 'QUEUED').reverse();
      hadWork = waiting.length > 0;
      if (!hadWork) { retryDelay = RETRY_MIN; return; }
      if (!navigator.onLine) { status('You are offline. Waiting reports are saved and will send automatically when the connection returns.'); return; }
      const { response: me, data: user } = await requestJson('/api/users/me', { headers: { Authorization: `Bearer ${bearer}` } });
      if ([401, 403].includes(me.status)) {
        rejectedToken = bearer;
        status('Your session needs renewal. Sign in with the same citizen account; waiting reports remain saved and resume after sign-in.'); return;
      }
      if (!me.ok || !user || !Number.isSafeInteger(user.id) || typeof user.role !== 'string') throw new Error('Connection check unavailable');
      if (Number(user.id) !== id || user.role !== 'citizen') {
        rejectedToken = bearer;
        status('Waiting reports belong to the original citizen account. Sign in with that account to deliver them.'); return;
      }
      if (owner() !== id || token() !== bearer) return;
      rejectedToken = null;
      for (const snapshot of waiting) {
        if (signingOut || owner() !== id || token() !== bearer) break;
        // Atomic transitions prevent another tab's receipt or removal from
        // being overwritten by this tab's late retry/error response.
        const latest = await changeRecord(snapshot.id, id, current => current?.state === 'QUEUED'
          ? { ...current, locked: true, error: null } : null);
        if (!latest) continue;
        let response, report;
        try {
          ({ response, data: report } = await requestJson('/api/incidents/', { method: 'POST',
            headers: { Authorization: `Bearer ${bearer}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...latest.payload, client_submission_id: latest.id }) }));
        } catch {
          await waitingError(latest, 'Connection interrupted. This report stays waiting and will retry automatically using the same submission ID.'); break;
        }
        if (response.status === 201) {
          if (!report || !Number.isSafeInteger(report.id) || report.id <= 0 || Number(report.user_id) !== id
              || report.client_submission_id !== latest.id || typeof report.report_reference !== 'string') {
            await waitingError(latest, 'The server receipt could not be verified. Your report remains waiting and will be checked again automatically.'); break;
          }
          await changeRecord(latest.id, id, current => unchangedAttempt(current, latest) ? {
            id: latest.id, owner: id, state: 'SENT', serverId: report.id, reference: report.report_reference,
            createdAt: latest.createdAt, updatedAt: new Date().toISOString(), locked: true } : null);
          retryDelay = RETRY_MIN;
          status('Report submitted. The server receipt is saved below.');
          const node = form(), input = node ? payloadFromForm(node) : null;
          const untouched = input && !input.message && !input.location && !input.help_required && input.people_affected === null && !editing;
          if (redirectCandidate === latest.id && untouched && window.location.pathname === '/reports/new'
              && document.visibilityState === 'visible' && owner() === id && token() === bearer) {
            redirectCandidate = null; window.location.assign(`/reports/${Number(report.id)}`); break;
          }
        } else if ([401, 403].includes(response.status)) {
          rejectedToken = bearer;
          status('Sign in again with the same citizen account. This waiting report is saved and will resume after sign-in.'); break;
        } else if (response.status >= 500 || [408, 425, 429].includes(response.status)) {
          await waitingError(latest, 'The service is temporarily unavailable. This report stays waiting and will retry automatically.'); break;
        } else {
          const message = response.status === 409 ? 'The submission ID conflicts with an existing report. Check My reports before creating a replacement.'
            : 'The server could not accept these details. Review the draft and try again.';
          await changeRecord(latest.id, id, current => unchangedAttempt(current, latest)
            ? { ...current, state: 'ERROR', locked: response.status !== 422, error: message } : null);
          status(message);
        }
      }
    } catch {
      retry = true;
      status('Unable to confirm the connection. Waiting reports remain saved and will retry automatically.');
    } finally {
      syncing = false;
      await render();
      if (!signingOut && owner() === id && token() === bearer && rejectedToken !== bearer && navigator.onLine) {
        if (retry) {
          requestSync(); retryDelay = Math.min(RETRY_MAX, retryDelay * 2);
        } else if (syncAgain) requestSync({ immediate: true });
        else if (hadWork) {
          try { if ((await all(id)).some(row => row.state === 'QUEUED')) requestSync({ immediate: true }); }
          catch { /* A later retry will recheck storage; no form data is discarded. */ }
        }
      }
    }
  }
  document.addEventListener('submit', event => {
    if (event.target.matches('[data-offline-form]')) { event.preventDefault(); event.stopImmediatePropagation(); save(true); }
    if (event.target.getAttribute('action') === '/ui/logout') {
      signingOut = true; clearTimeout(retryTimer); activeRequest?.abort();
      try { sessionStorage.removeItem(OWNER); } catch {}
    }
  }, true);
  function preparedForNavigation() { return Boolean(navigator.serviceWorker?.controller); }
  function reportPath(path) {
    try { const url = new URL(path, window.location.href); return url.origin === window.location.origin && url.pathname === '/reports/new'; }
    catch { return false; }
  }
  // HTMX requests carry authentication and are deliberately never served from
  // cache. An offline New report click uses the same URL as a normal document
  // navigation so the worker can supply the public copy of this report form.
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        || (link.target && link.target !== '_self') || navigator.onLine || !preparedForNavigation() || !reportPath(link.href)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (form()) { form().scrollIntoView({ block: 'start' }); form().querySelector('[name=location]')?.focus(); }
    else window.location.assign('/reports/new');
  }, true);
  function openReportAfterConnectionFailure(event) {
    const config = event.detail?.requestConfig;
    const path = config?.path || event.detail?.elt?.getAttribute?.('hx-get');
    if (!path || String(config?.verb || 'get').toLowerCase() !== 'get' || !reportPath(path) || !preparedForNavigation()) return;
    event.stopImmediatePropagation();
    if (form()) status('Connection interrupted. Continue your incident report here and save a draft or submit it to the waiting queue.');
    else window.location.assign('/reports/new');
  }
  document.addEventListener('htmx:sendError', openReportAfterConnectionFailure, true);
  document.addEventListener('htmx:timeout', openReportAfterConnectionFailure, true);
  document.addEventListener('htmx:beforeRequest', event => {
    const config = event.detail?.requestConfig;
    if (config && String(config.verb).toLowerCase() === 'get' && reportPath(config.path) && event.detail.xhr) {
      event.detail.xhr.timeout = REQUEST_TIMEOUT;
    }
  });
  document.addEventListener('input', event => {
    if (document.querySelector('[data-offline-shell]') && event.target.matches?.('[name=message]')) updateCharacterCount();
  });
  document.addEventListener('click', async event => {
    if (event.target.closest('[data-offline-save]')) await save(false);
    else if (event.target.closest('[data-offline-sync]')) requestSync({ immediate: true, reset: true });
    else {
      const action = event.target.closest('[data-offline-action]'); if (!action) return;
      try {
        const row = (await all(owner())).find(item => item.id === action.dataset.id); if (!row) return;
        if (action.dataset.offlineAction === 'remove') {
          if (!confirm(row.locked && row.state !== 'SENT' ? 'Remove this waiting report from this device? It may already have reached the server. Check My reports before submitting again.' : 'Remove this stored report or receipt from this device? Server reports are kept.')) return;
          await remove(row.id); if (editing === row.id) { editing = null; editingRevision = null; } await render();
        } else if (action.dataset.offlineAction === 'edit' && !row.locked && ['DRAFT', 'ERROR'].includes(row.state) && form()) {
          editing = row.id; editingRevision = row.revision || 0; redirectCandidate = null;
          for (const [name, value] of Object.entries(row.payload)) if (form().elements.namedItem(name)) form().elements.namedItem(name).value = value ?? '';
          updateCharacterCount();
          form().scrollIntoView({ block: 'start' }); form().querySelector('[name=location]')?.focus(); status('Editing the saved draft. Save or submit to keep your changes.');
        } else if (action.dataset.offlineAction === 'send') {
          if (!validate(row.payload)) { status('Edit this draft and fill in a valid location and description before sending.'); return; }
          await changeRecord(row.id, owner(), current => current && current.state !== 'SENT' && validate(current.payload)
            ? { ...current, state: 'QUEUED', error: null, updatedAt: new Date().toISOString() } : null);
          await render(); requestSync({ immediate: true, reset: true });
        }
      } catch (error) { status(error.message); }
    }
  });
  function ready() {
    const id = owner();
    if (id !== lastOwner) { lastOwner = id; currentStatus = ''; redirectCandidate = null; }
    render(); updateCharacterCount();
    if (document.querySelector('[data-offline-panel]')) {
      status(currentStatus || (navigator.onLine ? 'Connected. Drafts stay on this device until you submit them.' : 'Offline. Save a draft or submit it to the waiting queue.'));
    }
    if (id && token()) requestSync({ immediate: true });
    preparationStatus();
  }
  function preparationStatus(message) {
    document.querySelectorAll('[data-offline-preparation]').forEach(node => {
      node.textContent = message || (prepared ? 'This device is ready to reopen the incident form offline.' : 'Preparing this device to reopen the incident form offline…');
    });
  }
  async function prepareOffline() {
    if (preparing) return;
    if (!('serviceWorker' in navigator) || !window.isSecureContext) {
      preparationStatus('You can save drafts in this open form. Offline page reload is unavailable in this browser.'); return;
    }
    preparing = true; let deadline;
    try {
      const registration = await Promise.race([
        (async () => { await navigator.serviceWorker.register('/offline-worker.js', { scope: '/' }); return navigator.serviceWorker.ready; })(),
        new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Preparation timed out')), REQUEST_TIMEOUT + 2000); }),
      ]);
      prepared = Boolean(registration.active); preparationStatus();
    } catch {
      if (!prepared) preparationStatus('Drafts can still be saved here. Offline page reload is not ready yet; keep this form open while the connection recovers.');
    } finally { clearTimeout(deadline); preparing = false; }
  }
  function resume() {
    requestSync({ immediate: true, reset: true });
    if (!prepared) void prepareOffline();
  }
  // Also retry when the network recovers without an online event, while on
  // another app page, or after reopening the app with a valid account session.
  setInterval(() => { if (navigator.onLine) { requestSync({ immediate: true }); if (!prepared) void prepareOffline(); } }, RETRY_MAX);
  window.addEventListener('online', () => { status('Connection restored. Checking saved waiting reports…'); resume(); });
  window.addEventListener('focus', resume);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') resume(); });
  window.addEventListener('offline', () => {
    activeRequest?.abort();
    status('Offline. Waiting reports are saved on this device and will send automatically when the connection returns.');
  });
  document.addEventListener('htmx:afterSettle', ready);
  document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('[data-offline-shell]') && window.location.pathname === '/offline-report') history.replaceState(null, '', '/reports/new');
    ready();
    void prepareOffline();
  });
})();
