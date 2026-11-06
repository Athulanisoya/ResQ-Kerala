/* Local synthetic end-to-end checks. Requires Playwright on NODE_PATH and local demo accounts. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const secrets = [];

async function main() {
  const root = path.resolve(__dirname, '..');
  const base = process.env.BASE_URL || 'http://127.0.0.1:8014';
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Run against the local app only.');
  const demo = JSON.parse(fs.readFileSync(process.env.RESQ_DEMO_ACCOUNTS || path.join(root, '.runtime', 'docker-demo-accounts.json'), 'utf8'));
  const label = 'Synthetic offline browser ' + Date.now();
  const password = 'Synthetic-offline-' + crypto.randomUUID() + '!';
  secrets.push(demo.password, password);
  const qa = path.join(root, '.runtime', 'qa'); fs.mkdirSync(qa, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const page = await context.newPage(), outsiderPage = await context.newPage();
  page.setDefaultTimeout(20000); outsiderPage.setDefaultTimeout(20000);
  const errors = []; for (const p of [page, outsiderPage]) p.on('pageerror', error => errors.push(error.message));
  const createdReports = new Set(), localReports = new Set();
  let citizenToken, adminToken, outsider, cleanupTeam, cleanupAccount, cleanupToken;

  async function request(token, route, method = 'GET', body) {
    const response = await context.request.fetch(base + route, { method, headers: token ? { Authorization: 'Bearer ' + token } : {},
      ...(body === undefined ? {} : { data: body }) });
    let data = null; try { data = await response.json(); } catch {}
    return { status: response.status(), data };
  }
  async function api(token, route, method = 'GET', body) {
    const response = await request(token, route, method, body);
    assert.ok(response.status >= 200 && response.status < 300, method + ' ' + route + ': HTTP ' + response.status);
    return response.data;
  }
  async function login(p, email, secret) {
    await p.goto(base + '/login');
    await p.getByLabel('Email address', { exact: true }).fill(email);
    await p.getByLabel('Password', { exact: true }).fill(secret);
    await p.getByRole('button', { name: 'Sign in', exact: true }).click();
    await p.waitForURL(base + '/dashboard');
    await p.locator('#app-root[data-authenticated=true][data-user-id]').waitFor();
    await p.waitForFunction(() => sessionStorage.getItem('resq-offline-owner-v1') === document.querySelector('#app-root')?.dataset.userId);
    return p.evaluate(() => sessionStorage.getItem('resq-week1-session'));
  }
  async function openReporter(p, route = '/reports/new') {
    await p.goto(base + route);
    await p.locator('[data-offline-form]').waitFor();
    await p.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
  }
  async function fill(marker) {
    await page.getByLabel('Location', { exact: false }).fill(label + ' ' + marker + ', Aluva');
    await page.getByLabel('What is happening?', { exact: false }).fill(label + ' ' + marker + ': synthetic exercise, no real emergency.');
    await page.getByLabel('Number of people affected', { exact: false }).fill('2');
    await page.getByLabel('Help needed', { exact: false }).fill('Synthetic offline-reporting exercise only');
  }
  async function overflow(p) {
    const dimensions = await p.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(dimensions.document <= dimensions.width + 1, 'No horizontal overflow');
  }
  const records = p => p.locator('[data-offline-records] article');
  async function rowBy(marker) { return records(page).filter({ hasText: label + ' ' + marker }); }
  async function track(locator) {
    await locator.waitFor(); const id = await locator.getAttribute('data-offline-id'); localReports.add(id); return id;
  }
  async function stored(p) {
    return p.evaluate(async () => new Promise((resolve, reject) => {
      const open = indexedDB.open('resq-offline-v1', 1); open.onerror = () => reject(new Error('Cannot inspect offline database'));
      open.onsuccess = () => { const tx = open.result.transaction('reports'); const get = tx.objectStore('reports').getAll();
        get.onsuccess = () => resolve(get.result); tx.oncomplete = () => open.result.close(); };
    }));
  }
  async function waitState(id, expected) {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      try {
        const row = (await stored(page)).find(item => item.id === id);
        if (row?.state === expected) return;
      } catch (error) {
        if (!/Execution context was destroyed|Cannot find context|navigation/i.test(error.message)) throw error;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail('Stored report did not reach ' + expected);
  }

  try {
    citizenToken = await login(page, demo.accounts.find(row => row.role === 'citizen').email, demo.password);
    secrets.push(citizenToken);
    const adminAuth = await api(null, '/api/auth/login', 'POST', { email: demo.accounts.find(row => row.role === 'admin').email, password: demo.password });
    adminToken = adminAuth.access_token; secrets.push(adminToken);
    outsider = await api(null, '/api/auth/register', 'POST', { full_name: label + ' outsider', email: 'offline-outsider-' + crypto.randomUUID() + '@example.com', password });
    secrets.push(outsider.access_token);
    await openReporter(page);
    assert.equal(await page.locator('a[href="/offline-report"]').count(), 0, 'No separate offline navigation remains');
    await page.getByRole('heading', { name: 'Drafts and waiting reports', exact: true }).waitFor();
    assert.equal(await page.locator('.form-card [data-offline-panel]').count(), 1, 'Drafts are part of the incident form card');
    await fill('private-draft');
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    const draft = await rowBy('private-draft'), draftId = await track(draft);
    await draft.getByText('Draft · not sent', { exact: true }).waitFor();
    assert.equal(await page.locator('[data-character-count=message]').innerText(), '0 / 5,000', 'Saving resets the regular form character counter');
    await page.locator('[data-offline-panel]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(qa, 'incident-reporting-preview.png'), fullPage: false });
    assert.equal((await api(citizenToken, '/api/incidents/')).filter(row => row.message.startsWith(label)).length, 0, 'A draft does not create a server report');

    // Drafts belong to normal incident reporting, including navigation from My reports.
    await page.goto(base + '/reports');
    await page.getByRole('heading', { name: 'My reports', exact: true }).waitFor();
    await page.waitForFunction(() => !document.querySelector('.htmx-settling,.htmx-swapping'));
    await context.setOffline(true);
    await page.getByRole('link', { name: 'New report', exact: true }).click();
    await page.getByRole('heading', { name: 'Report an incident', exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/reports/new');
    await page.locator(`[data-offline-id="${draftId}"]`).waitFor();
    await draft.getByRole('button', { name: 'Edit draft', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-offline-status]')?.textContent.startsWith('Editing the saved draft.'));
    await page.getByLabel('What is happening?', { exact: false }).fill(label + ' private-draft: saved while offline; synthetic exercise.');
    const offlineMessage = await page.locator('[name=message]').inputValue();
    assert.equal(await page.locator('[data-character-count=message]').innerText(), offlineMessage.length.toLocaleString() + ' / 5,000', 'The shared form counter works offline');
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await page.locator(`[data-offline-id="${draftId}"]`).getByText('saved while offline', { exact: false }).waitFor();
    await fill('queued');
    await page.getByRole('button', { name: 'Submit report', exact: true }).click();
    const queued = await rowBy('queued'), queuedId = await track(queued);
    await queued.getByText('Waiting to send', { exact: true }).waitFor();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Report an incident', exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/reports/new', 'Offline reload keeps the normal reporting URL');
    await page.locator(`[data-offline-id="${draftId}"]`).waitFor();
    await page.locator(`[data-offline-id="${queuedId}"]`).getByText('Waiting to send', { exact: true }).waitFor();
    await page.setViewportSize({ width: 320, height: 900 }); await overflow(page);
    await page.screenshot({ path: path.join(qa, 'offline-reporter-320.png'), fullPage: true });
    await context.setOffline(false);
    await waitState(queuedId, 'SENT');
    const receipt = (await stored(page)).find(row => row.id === queuedId);
    const submitted = await api(citizenToken, '/api/incidents/' + receipt.serverId);
    createdReports.add(submitted.id);
    assert.equal(submitted.client_submission_id, queuedId);
    assert.ok(submitted.message.startsWith(label), 'The queued report retains its original incident details');
    let reports = (await api(citizenToken, '/api/incidents/')).filter(row => row.message.startsWith(label));
    assert.equal(reports.length, 1, 'Reconnection submits one queued report and keeps the private draft unsent');
    createdReports.add(reports[0].id);
    assert.equal(reports[0].client_submission_id, queuedId);
    await page.getByRole('button', { name: 'Send waiting reports', exact: true }).click();
    assert.equal((await api(citizenToken, '/api/incidents/')).filter(row => row.message.startsWith(label)).length, 1, 'Repeated synchronization does not duplicate the report');
    console.log('Passed core: offline save/edit/queue, cached reload,320layout, reconnect server receipt and duplicate-free repeated sync.');

    await login(outsiderPage, outsider.user.email, password);
    await openReporter(outsiderPage);
    assert.equal(await outsiderPage.locator('a[href="/offline-report"]').count(), 0);
    assert.equal(await records(outsiderPage).count(), 0, 'Another account sees no private draft or receipt');
    assert.equal((await outsiderPage.locator('#main-content').innerText()).includes(label), false, 'The reporting form shows no other account’s draft content');
    assert.equal((await request(outsider.access_token, '/api/incidents/' + reports[0].id)).status, 403, 'Server report is also private');

    // Let the server commit the POST, then deliberately lose its 201 response.
    let dropped = false;
    await page.route('**/api/incidents/', async route => {
      if (route.request().method() !== 'POST' || dropped) return route.continue();
      const upstream = await route.fetch(); assert.equal(upstream.status(), 201);
      dropped = true; const saved = await upstream.json(); createdReports.add(saved.id);
      await route.abort('connectionreset');
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await fill('lost-response');
    await page.getByRole('button', { name: 'Submit report', exact: true }).click();
    const lost = await rowBy('lost-response'), lostId = await track(lost);
    await page.waitForFunction(() => document.querySelector('[data-offline-status]')?.textContent.includes('Connection interrupted'));
    assert.equal(dropped, true);
    await lost.getByText('Waiting to send', { exact: true }).waitFor();
    assert.equal(await lost.getByRole('button', { name: 'Edit draft', exact: true }).count(), 0, 'Ambiguous submissions stay immutable');
    await page.unroute('**/api/incidents/');
    // Recovery now delivers automatically and may navigate to the server receipt.
    await waitState(lostId, 'SENT');
    await openReporter(page);
    reports = (await api(citizenToken, '/api/incidents/')).filter(row => row.message.startsWith(label));
    reports.forEach(row => createdReports.add(row.id));
    assert.equal(reports.length, 2, 'Lost response plus retry creates exactly one additional report');
    assert.equal(reports.filter(row => row.client_submission_id === lostId).length, 1);
    assert.equal((await api(citizenToken, '/api/incidents/' + reports.find(row => row.client_submission_id === lostId).id + '/history')).length, 1, 'Retry does not repeat creation history');

    // Cache storage must hold only the public copy of the regular form and known static resources.
    const cached = await page.evaluate(async () => {
      const output = [];
      for (const name of await caches.keys()) {
        if (!name.startsWith('resq-offline-report-')) continue;
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
          const response = await cache.match(request), type = response.headers.get('content-type') || '';
          output.push({ pathname: new URL(request.url).pathname, text: /html|javascript|css/.test(type) ? await response.text() : '' });
        }
      }
      return output;
    });
    assert.ok(cached.some(row => row.pathname === '/offline/report-form'));
    for (const row of cached) {
      assert.ok(row.pathname === '/offline/report-form' || row.pathname.startsWith('/static/'), 'No authenticated route cached');
      for (const value of [label, citizenToken, adminToken, outsider.user.email]) assert.equal(row.text.includes(value), false, 'No personal data or bearer credentials cached');
    }
    const persisted = JSON.stringify(await stored(page));
    for (const secret of secrets) assert.equal(persisted.includes(secret), false, 'IndexedDB stores no bearer tokens or passwords');
    for (const row of await stored(page)) if (row.state === 'SENT' && localReports.has(row.id)) assert.equal('payload' in row, false, 'Submitted receipts discard incident details');
    await overflow(page); await page.screenshot({ path: path.join(qa, 'offline-reporter-1440.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Passed: offline drafts and queue survive reload, reconnect and lost-response retries submit once, account isolation, public-only caches, credential-free storage, and 320/1440 layouts.');
  } finally {
    await context.setOffline(false).catch(() => {});
    // Close only this invocation's synthetic reports through ordinary reviewed response workflow.
    try {
      if (citizenToken) for (const record of await api(citizenToken, '/api/incidents/')) if (record.message.startsWith(label)) createdReports.add(record.id);
      if (adminToken && createdReports.size) {
        cleanupTeam = await api(adminToken, '/api/management/teams', 'POST', { name: label + ' cleanup', team_type: 'Rescue' });
        cleanupAccount = await api(adminToken, '/api/management/team-accounts', 'POST', { full_name: label + ' cleanup member', email: 'offline-cleanup-' + crypto.randomUUID() + '@example.com', password, team_id: cleanupTeam.id });
        cleanupToken = (await api(null, '/api/auth/login', 'POST', { email: cleanupAccount.email, password })).access_token; secrets.push(cleanupToken);
        for (const id of createdReports) {
          let record = await api(adminToken, '/api/incidents/' + id); assert.ok(record.message.startsWith(label));
          if (record.status === 'SUBMITTED') await api(adminToken, '/api/incidents/' + id + '/status', 'PATCH', { status: 'VERIFIED', note: label + ' synthetic cleanup verification' });
          await api(adminToken, '/api/incidents/admin/assign-team', 'POST', { incident_id: id, team_id: cleanupTeam.id, assignment_note: label + ' synthetic exercise cleanup' });
          await api(cleanupToken, '/api/operations/incidents/' + id + '/accept', 'POST', { note: label + ' synthetic cleanup' });
          for (const status of ['EN_ROUTE', 'IN_PROGRESS', 'RESOLVED']) await api(cleanupToken, '/api/operations/incidents/' + id + '/progress', 'POST', { status, note: label + ' synthetic cleanup' });
          await api(adminToken, '/api/incidents/' + id + '/close', 'POST', { reason: label + ' synthetic exercise complete' });
        }
      }
      if (cleanupAccount) await api(adminToken, '/api/management/users/' + cleanupAccount.id, 'PATCH', { role: 'response_team', team_id: cleanupTeam.id, active: false });
      if (cleanupTeam) await api(adminToken, '/api/management/teams/' + cleanupTeam.id, 'PATCH', { name: cleanupTeam.name, status: 'OFFLINE' });
      if (outsider && adminToken) await api(adminToken, '/api/management/users/' + outsider.user.id, 'PATCH', { role: 'citizen', team_id: null, active: false });
      for (const id of localReports) {
        const article = page.locator(`[data-offline-id="${id}"]`);
        if (await article.count()) { page.once('dialog', dialog => dialog.accept()); await article.getByRole('button', { name: /Remove .*device/ }).click(); await article.waitFor({ state: 'detached' }); }
      }
    } catch { console.log('Synthetic cleanup needs review; no real records were targeted.'); }
    for (const auth of [citizenToken, adminToken, outsider?.access_token, cleanupToken]) if (auth) await request(auth, '/api/auth/logout', 'POST').catch(() => {});
    await browser.close();
  }
}

main().catch(error => { let output = String(error?.stack || error); for (const secret of secrets) if (secret) output = output.split(secret).join('[redacted]'); console.error(output); process.exitCode = 1; });
