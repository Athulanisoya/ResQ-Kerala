/* Real local API + synthetic fixtures; failures are confined to browser requests. */
const { setup } = require('./features_browser_helpers.cjs');
const crypto = require('node:crypto');

async function main() {
  const h = await setup(), assert = h.assert;
  const label = 'Synthetic unstable reporting ' + Date.now();
  let citizen, outsider, page, otherPage, resumedPage;
  const queued = new Set(), drafts = new Set(), createdReports = new Set(), trapped = [];
  let cleanupTeam, cleanupAccount, cleanupToken, releaseFirstResponse;
  const cleanupPassword = 'Synthetic-cleanup-' + crypto.randomUUID() + '!';

  async function records(p = page) {
    return p.evaluate(() => new Promise((resolve, reject) => {
      const open = indexedDB.open('resq-offline-v1', 1);
      open.onerror = () => reject(new Error('Unable to inspect test queue'));
      open.onsuccess = () => {
        const tx = open.result.transaction('reports'), get = tx.objectStore('reports').getAll();
        get.onsuccess = () => resolve(get.result);
        get.onerror = () => reject(new Error('Unable to read test queue'));
        tx.oncomplete = () => open.result.close();
      };
    }));
  }
  async function until(predicate, description, timeout = 45000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      let value;
      try { value = await predicate(); }
      catch (error) {
        // A successful foreground submission can navigate to its receipt.
        // Poll the new document rather than treating that navigation as failure.
        if (!/Execution context was destroyed|Cannot find context|most likely because of a navigation/.test(error.message)) throw error;
      }
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail(description);
  }
  async function state(id, expected, p = page, timeout) {
    const row = await until(async () => {
      const found = (await records(p)).find(x => x.id === id);
      return found?.state === expected ? found : false;
    }, 'Report did not reach ' + expected, timeout);
    if (row.state === 'SENT') createdReports.add(row.serverId);
    return row;
  }
  async function reporter(p = page) {
    await h.open(p, '/reports/new', 'Report an incident');
    await p.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    await p.waitForFunction(() => sessionStorage.getItem('resq-offline-owner-v1') === document.querySelector('#app-root')?.dataset.userId);
  }
  async function fill(marker, p = page) {
    await p.getByLabel('Location', { exact: false }).fill(label + ' ' + marker + ', Aluva');
    await p.getByLabel('What is happening?', { exact: false }).fill(label + ' ' + marker + ': synthetic exercise, no real emergency.');
    await p.getByLabel('Number of people affected', { exact: false }).fill('2');
    await p.getByLabel('Help needed', { exact: false }).fill('Synthetic unstable-network exercise only');
  }
  async function save(marker, send = true, p = page) {
    await fill(marker, p);
    await p.getByRole('button', { name: send ? 'Submit report' : 'Save draft', exact: true }).click();
    const row = await until(async () => (await records(p)).find(x => x.owner === citizen.user.id && x.payload?.message.includes(label + ' ' + marker + ':')),
      'Local save did not finish independently of the network', 4000);
    await p.waitForFunction(() => document.querySelector('[data-offline-form]')?.getAttribute('aria-busy') !== 'true', null, { timeout: 2000 });
    (send ? queued : drafts).add(row.id);
    return row.id;
  }
  async function actualReports() {
    return (await h.api(citizen.access_token, '/api/incidents/')).filter(x => x.message.startsWith(label));
  }
  async function releaseTrapped() {
    for (const item of trapped.splice(0)) {
      await item.route.abort('timedout').catch(() => {});
      item.release();
    }
  }

  try {
    citizen = await h.citizen(label + ' citizen');
    outsider = await h.citizen(label + ' other account');
    page = await h.page(citizen);
    await reporter();
    assert.equal(await page.evaluate(() => navigator.onLine), true);

    // The network indicator stays online while the server rejects requests.
    // Hold the first response to prove another local draft/submission is not blocked.
    let releaseFirst, firstStarted;
    const firstHeld = new Promise(resolve => { releaseFirst = resolve; releaseFirstResponse = resolve; });
    const firstSeen = new Promise(resolve => { firstStarted = resolve; });
    const transient = [503, 408, 425, 429], transientSeen = [];
    let postAttempts = 0;
    await page.route('**/api/incidents/', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      postAttempts++;
      if (postAttempts === 1) { firstStarted(); await firstHeld; }
      if (transient.length) {
        const status = transient.shift(); transientSeen.push(status);
        return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic temporary interruption' }) });
      }
      return route.continue();
    });
    const first = await save('always-online-a');
    await Promise.race([firstSeen, new Promise((_, reject) => setTimeout(() => reject(new Error('Submission never attempted')), 10000))]);
    await page.waitForFunction(() => document.querySelector('[data-offline-form]')?.getAttribute('aria-busy') !== 'true', null, { timeout: 2000 });
    const localDraft = await save('draft-during-network-wait', false);
    const second = await save('always-online-b');
    await state(localDraft, 'DRAFT');
    const firstRejected = page.waitForResponse(response => new URL(response.url()).pathname === '/api/incidents/' && response.status() === 503);
    releaseFirst(); await firstRejected;
    await h.open(page, '/community', 'News and donations');
    await state(first, 'SENT'); await state(second, 'SENT');
    assert.deepEqual(transientSeen, [503, 408, 425, 429]);
    assert.equal(await page.evaluate(() => navigator.onLine), true, 'Recovery must not require an online event');
    assert.equal((await actualReports()).length, 2);
    await state(localDraft, 'DRAFT');
    await page.unroute('**/api/incidents/');
    console.log('Passed: always-online transient errors retry automatically away from the report page; concurrent local saves stay responsive.');

    // A stalled identity check must time out, leaving local saving usable. The
    // original /me request stays trapped until a later request has succeeded.
    let hangIdentity = true, identityAttempts = 0, identityStarted;
    const identitySeen = new Promise(resolve => { identityStarted = resolve; });
    await page.route('**/api/users/me', async route => {
      identityAttempts++;
      if (!hangIdentity) return route.continue();
      identityStarted();
      return new Promise(resolve => trapped.push({ route, release: resolve }));
    });
    await reporter();
    const stalled = await save('stalled-identity');
    await Promise.race([identitySeen, new Promise((_, reject) => setTimeout(() => reject(new Error('Identity check never attempted')), 10000))]);
    const stalledDraft = await save('draft-during-stalled-identity', false);
    await state(stalledDraft, 'DRAFT');
    hangIdentity = false;
    await state(stalled, 'SENT');
    assert.ok(identityAttempts >= 2, 'A bounded identity check must permit a later retry');
    await releaseTrapped(); await page.unroute('**/api/users/me');
    console.log('Passed: stalled authentication requests cannot block drafts and recover automatically after the request deadline.');

    // Queue offline, survive reload, leave the app before restoration, and
    // return directly to Overview. No reporting-page visit or manual sync occurs.
    await reporter(); await h.context.setOffline(true);
    const offline = await save('offline-reopen');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Report an incident', exact: true }).waitFor();
    await state(offline, 'QUEUED');
    await page.goto('about:blank');
    await h.context.setOffline(false);
    await h.open(page, '/dashboard', 'Together, we look after Kerala.');
    await state(offline, 'SENT');
    console.log('Passed: an offline submission survives reload and sends when the signed-in app reopens directly on Overview.');

    // Keep the queued payload through session revocation. A different signed-in
    // account cannot display or send it; signing back in as its owner resumes it.
    await reporter();
    const revoked = await page.evaluate(() => sessionStorage.getItem('resq-week1-session'));
    await h.api(revoked, '/api/auth/logout', 'POST');
    await h.context.setOffline(true);
    const expired = await save('expired-session');
    const denied = page.waitForResponse(r => new URL(r.url()).pathname === '/api/users/me' && [401, 403].includes(r.status()));
    await h.context.setOffline(false); await denied;
    await state(expired, 'QUEUED');
    assert.equal((await actualReports()).some(x => x.client_submission_id === expired), false);
    otherPage = await h.page(outsider); await reporter(otherPage);
    assert.equal(await otherPage.locator('[data-offline-records] article').count(), 0);
    assert.equal((await h.api(outsider.access_token, '/api/incidents/')).length, 0);
    await state(expired, 'QUEUED');
    resumedPage = await h.page(citizen);
    await state(expired, 'SENT', resumedPage);
    const received = (await actualReports()).filter(x => x.client_submission_id === expired);
    assert.equal(received.length, 1); assert.equal(received[0].user_id, citizen.user.id);
    console.log('Passed: session renewal preserves the queue, isolates other accounts and resumes delivery only for its owner.');

    // Commit once, drop its receipt, then let automatic retry recover the same
    // UUID while the browser continues to report an online connection.
    page = resumedPage; await reporter();
    let dropped = false, malformed = false;
    await page.route('**/api/incidents/', async route => {
      if (route.request().method() !== 'POST' || malformed) return route.continue();
      const result = await route.fetch(); assert.equal(result.status(), 201);
      createdReports.add((await result.json()).id);
      if (!dropped) { dropped = true; await route.abort('connectionreset'); }
      else { malformed = true; await route.fulfill({ status: 201, contentType: 'application/json', body: '{"ok":true}' }); }
    });
    const lost = await save('lost-receipt');
    await state(lost, 'SENT');
    assert.ok(dropped && malformed);
    const allReports = await actualReports();
    assert.equal(allReports.filter(x => x.client_submission_id === lost).length, 1);
    assert.equal(allReports.length, queued.size);
    for (const id of drafts) await state(id, 'DRAFT');
    assert.deepEqual(h.errors, []);
    console.log('Passed: lost and malformed successful receipts retry without duplicate reports, while unsubmitted drafts remain local.');
  } finally {
    releaseFirstResponse?.();
    await h.context.setOffline(false).catch(() => {});
    await releaseTrapped();
    try {
      if (citizen) for (const row of await actualReports()) createdReports.add(row.id);
      if (createdReports.size) {
        cleanupTeam = await h.api(h.admin.access_token, '/api/management/teams', 'POST', { name: label + ' cleanup', team_type: 'Rescue' });
        cleanupAccount = await h.api(h.admin.access_token, '/api/management/team-accounts', 'POST', {
          full_name: label + ' cleanup member', email: 'unstable-cleanup-' + crypto.randomUUID() + '@example.com', password: cleanupPassword, team_id: cleanupTeam.id });
        cleanupToken = (await h.api(null, '/api/auth/login', 'POST', { email: cleanupAccount.email, password: cleanupPassword })).access_token;
        for (const id of createdReports) {
          const row = await h.api(h.admin.access_token, '/api/incidents/' + id);
          assert.ok(row.message.startsWith(label));
          if (row.status === 'SUBMITTED') await h.api(h.admin.access_token, '/api/incidents/' + id + '/status', 'PATCH', { status: 'VERIFIED', note: label + ' fixture verification' });
          await h.api(h.admin.access_token, '/api/incidents/admin/assign-team', 'POST', { incident_id: id, team_id: cleanupTeam.id, assignment_note: label + ' fixture cleanup' });
          await h.api(cleanupToken, '/api/operations/incidents/' + id + '/accept', 'POST', { note: label + ' synthetic cleanup' });
          for (const status of ['EN_ROUTE', 'IN_PROGRESS', 'RESOLVED']) await h.api(cleanupToken, '/api/operations/incidents/' + id + '/progress', 'POST', { status, note: label + ' synthetic cleanup' });
          await h.api(h.admin.access_token, '/api/incidents/' + id + '/close', 'POST', { reason: label + ' synthetic exercise complete' });
        }
      }
      if (cleanupAccount) await h.api(h.admin.access_token, '/api/management/users/' + cleanupAccount.id, 'PATCH', { role: 'response_team', team_id: cleanupTeam.id, active: false });
      if (cleanupTeam) await h.api(h.admin.access_token, '/api/management/teams/' + cleanupTeam.id, 'PATCH', { name: cleanupTeam.name, status: 'OFFLINE' });
      if (cleanupToken) await h.request(cleanupToken, '/api/auth/logout', 'POST');
    } catch (error) {
      console.error('Synthetic cleanup needs review: ' + error.message);
      process.exitCode = 1;
    }
    await h.close();
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
