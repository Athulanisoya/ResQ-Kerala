/* Local synthetic end-to-end checks. RESQ_DOCKER_FIXTURES=1 enables two guarded timestamp fixtures. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const redact = [];

async function main() {
  const root = path.resolve(__dirname, '..');
  const base = process.env.BASE_URL || 'http://127.0.0.1:8014';
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Use a local application for these synthetic fixtures.');
  const demo = JSON.parse(fs.readFileSync(process.env.RESQ_DEMO_ACCOUNTS || path.join(root, '.runtime', 'docker-demo-accounts.json'), 'utf8'));
  const qa = path.join(root, '.runtime', 'qa'); fs.mkdirSync(qa, { recursive: true });
  const stamp = Date.now();
  const label = 'Synthetic automation browser ' + stamp;
  const password = 'Synthetic-automation-' + crypto.randomUUID() + '!';
  redact.push(demo.password, password);
  const errors = [], alerts = [], subscriptions = [];
  let shelter, incident, rescue, rescueEmail, reservation, waiting, completed = false;
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const pages = {};
  for (const role of ['admin', 'citizen', 'outsider', 'staff', 'team', 'rescue']) {
    const page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 500) errors.push(response.status() + ' ' + new URL(response.url()).pathname); });
    pages[role] = page;
  }
  const { admin, citizen, outsider, staff, team } = pages;

  async function request(page, route, method = 'GET', body) {
    return page.evaluate(async ({ route, method, body }) => {
      const response = await fetch(route, { method, headers: {
        Authorization: 'Bearer ' + sessionStorage.getItem('resq-week1-session'),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      const text = await response.text(); let data; try { data = JSON.parse(text); } catch { data = null; }
      return { status: response.status, data };
    }, { route, method, body });
  }
  async function api(page, route, method = 'GET', body) {
    const response = await request(page, route, method, body);
    assert.ok(response.status >= 200 && response.status < 300, method + ' ' + route + ': HTTP ' + response.status);
    return response.data;
  }
  async function open(page, route, heading) {
    await page.goto(base + route);
    if (heading) await page.getByRole('heading', { name: heading, exact: true }).waitFor();
    await noOverflow(page, route);
  }
  async function login(page, email, secret) {
    await open(page, '/login', 'Welcome back.');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(secret);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    await page.locator('[data-map-status]').filter({ hasText: 'Map checked' }).waitFor();
  }
  async function noOverflow(page, stage) {
    const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(dimensions.document <= dimensions.width + 1, stage + ': horizontal overflow');
  }
  async function submit(page, locator, route) {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === route && r.request().method() === 'POST');
    await locator.click();
    assert.equal((await response).status(), 200, route);
  }
  async function checks(viaUI = false) {
    if (viaUI) {
      await open(admin, '/automation-settings', 'Automation settings');
      await submit(admin, admin.getByRole('button', { name: 'Run checks now', exact: true }), '/ui/automation-settings/run');
      await admin.getByText('Checks completed. Review the latest status below.', { exact: true }).waitFor();
    } else await api(admin, '/api/admin/automations/run', 'POST');
    const state = await api(admin, '/api/admin/automations');
    assert.equal(state.runtime.has_error, false, 'Automatic jobs must complete successfully.');
  }
  async function notifications(page) { return (await api(page, '/api/communication/notifications?limit=100')).notifications; }
  async function ownAlertNotifications(alert) { return (await notifications(citizen)).filter(row => row.message.includes('Administrator-issued alert #' + alert.id + '.')); }
  async function shelterRecord() { return api(admin, '/api/shelters/' + shelter.id); }
  async function capacity(occupied, status = 'OPEN') {
    const current = await shelterRecord();
    return api(admin, '/api/shelters/' + shelter.id, 'PATCH', { capacity: current.capacity, occupied, status,
      expected_version: current.version, note: label + ' capacity test update' });
  }
  async function currentWaitlist(page = citizen) { return api(page, '/api/shelters/' + shelter.id + '/waitlist'); }
  async function timestampFixture(kind, id) {
    assert.equal(process.env.RESQ_DOCKER_FIXTURES, '1', 'Set RESQ_DOCKER_FIXTURES=1 for guarded synthetic time fixtures.');
    assert.equal(new URL(base).port, '8014', 'Timestamp fixtures are scoped to the local Docker app on port 8014.');
    const code = [
      'import sys', 'from datetime import datetime,timedelta,timezone',
      'from sqlalchemy import select', 'from backend.database.connection import SessionLocal',
      'from backend.models.shelter import Shelter', 'from backend.models.shelter_waitlist import ShelterWaitlist',
      'kind, identity, prefix=sys.argv[1], int(sys.argv[2]), sys.argv[3]',
      "assert prefix.startswith('Synthetic automation browser ')",
      'with SessionLocal() as db:',
      " row=db.get(ShelterWaitlist,identity) if kind=='expire-offer' else None",
      " shelter=db.scalar(select(Shelter).where(Shelter.id==(row.shelter_id if row else identity)).with_for_update())",
      ' assert shelter is not None and shelter.name.startswith(prefix)',
      " if kind=='age-confirmation': shelter.capacity_confirmed_at=datetime.now(timezone.utc)-timedelta(days=8)",
      " elif kind=='expire-offer':",
      "  assert row is not None and row.status=='OFFERED'",
      '  row.offer_expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)',
      " else: raise ValueError('Unknown fixture action')",
      ' db.commit()',
      "print('Synthetic timestamp fixture applied.')",
    ].join('\n');
    const output = execFileSync('docker', ['compose', '--env-file', '.env.docker', 'exec', '-T', 'app', 'python', '-c', code, kind, String(id), label], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 30000 });
    assert.ok(output.includes('Synthetic timestamp fixture applied.'));
  }
  async function waitlistForm(page, size) {
    await page.getByLabel('People in your group, including you', { exact: true }).fill(String(size));
    await page.getByLabel('Your current district', { exact: true }).selectOption('ernakulam');
    await page.getByLabel('Your current locality or landmark', { exact: true }).fill('Synthetic Aluva origin');
    await page.getByLabel('Support needs', { exact: false }).fill(label + ' private waiting-list note');
  }
  async function screenshot(page, file) {
    await noOverflow(page, file);
    await page.screenshot({ path: path.join(qa, file), fullPage: true });
  }

  try {
    await login(admin, demo.accounts.find(row => row.role === 'admin').email, demo.password);
    await login(team, demo.accounts.find(row => row.role === 'response_team').email, demo.password);
    const citizenEmail = `automation-citizen-${stamp}@example.com`, otherEmail = `automation-other-${stamp}@example.com`;
    for (const email of [citizenEmail, otherEmail]) await api(admin, '/api/auth/register', 'POST', { full_name: label + ' citizen', email, password });
    await login(citizen, citizenEmail, password); await login(outsider, otherEmail, password);
    const shelterTeam = await api(admin, '/api/management/teams', 'POST', { name: label + ' Shelter', team_type: 'Shelter' });
    const staffEmail = `automation-staff-${stamp}@example.com`;
    await api(admin, '/api/management/team-accounts', 'POST', { full_name: label + ' reception', email: staffEmail, password, team_id: shelterTeam.id });
    await login(staff, staffEmail, password);
    shelter = await api(admin, '/api/shelters', 'POST', { name: label + ' shelter', location: 'Synthetic Aluva hall', district: 'Ernakulam', locality: 'Aluva',
      address: 'Synthetic fixture — not a real shelter', contact: 'Synthetic reception contact', capacity: 3, occupied: 3, team_id: shelterTeam.id,
      latitude: 10.10764, longitude: 76.35158 });

    // Follow overlapping areas through the actual form and verify one delivery per alert transition.
    await open(citizen, '/alert-subscriptions', 'Follow alert areas');
    for (const place of ['ernakulam', 'ernakulam-aluva']) {
      await citizen.getByLabel('District or locality', { exact: true }).selectOption(place);
      await submit(citizen, citizen.getByRole('button', { name: 'Follow area', exact: true }), '/ui/alert-subscriptions');
      await citizen.getByText('Area followed. Current matching alerts and future changes appear in Notifications.', { exact: true }).waitFor();
    }
    subscriptions.push(...await api(citizen, '/api/alert-subscriptions'));
    assert.equal(subscriptions.length, 2);
    const starts = new Date(Date.now() + 8000).toISOString();
    const alert = await api(admin, '/api/alerts', 'POST', { title: label + ' area alert', message: 'Synthetic warning for automation testing only.',
      level: 'ORANGE', place_id: 'ernakulam-aluva', starts_at: starts, expires_at: new Date(Date.now() + 3600000).toISOString() });
    alerts.push(alert);
    await checks(); assert.equal((await ownAlertNotifications(alert)).length, 0);
    await citizen.waitForFunction(start => Date.now() >= Date.parse(start), starts, { timeout: 15000 });
    await checks(true); assert.equal((await ownAlertNotifications(alert)).length, 1);
    await checks(); assert.equal((await ownAlertNotifications(alert)).length, 1);
    await api(admin, '/api/alerts/' + alert.id, 'PATCH', { level: 'RED', message: 'Synthetic changed warning for automation testing only.' });
    await checks(); assert.equal((await ownAlertNotifications(alert)).length, 2);
    await api(admin, '/api/alerts/' + alert.id + '/expire', 'POST');
    await checks(); assert.equal((await ownAlertNotifications(alert)).length, 3);
    await checks(); assert.equal((await ownAlertNotifications(alert)).length, 3);
    await open(citizen, '/updates', 'My updates');
    assert.equal(await citizen.locator('.update-item').filter({ hasText: label + ' area alert' }).count(), 3);
    assert.equal((await request(outsider, `/api/alert-subscriptions/${subscriptions[0].id}/unsubscribe`, 'POST')).status, 404);

    // Old confirmation triggers staff and administrator reminders without changing occupied counts.
    await timestampFixture('age-confirmation', shelter.id);
    await checks(true);
    const staffReminder = (await notifications(staff)).filter(row => row.title === 'Shelter capacity needs confirmation' && row.message.includes(shelter.name));
    const adminReminder = (await notifications(admin)).filter(row => row.title === 'Shelter capacity review overdue' && row.message.includes(shelter.name));
    assert.equal(staffReminder.length, 1); assert.equal(adminReminder.length, 1);
    await checks();
    assert.equal((await notifications(staff)).filter(row => row.title === 'Shelter capacity needs confirmation' && row.message.includes(shelter.name)).length, 1);
    assert.equal((await shelterRecord()).occupied, 3);
    await open(staff, '/updates', 'My updates');
    await staff.getByRole('heading', { name: 'Shelter capacity needs confirmation', exact: true }).waitFor();
    await screenshot(staff, 'automation-reminder-1440.png');

    // Full shelter -> waiting entry -> capacity release -> temporary offer -> explicit acceptance.
    await open(citizen, '/shelters/' + shelter.id + '/waitlist', 'Shelter waiting list');
    await waitlistForm(citizen, 2);
    await submit(citizen, citizen.getByRole('button', { name: 'Join waiting list', exact: true }), `/ui/shelters/${shelter.id}/waitlist`);
    waiting = (await currentWaitlist())[0]; assert.equal(waiting.status, 'WAITING');
    assert.equal((await currentWaitlist(outsider)).length, 0);
    assert.equal((await request(team, '/api/shelters/' + shelter.id + '/waitlist')).status, 403);
    const staleConfirmation = (await shelterRecord()).capacity_confirmed_at;
    assert.equal(Date.parse(staleConfirmation) < Date.now() - 7 * 86400000, true);
    await capacity(1); await checks();
    waiting = (await currentWaitlist())[0]; assert.equal(waiting.status, 'OFFERED');
    assert.equal((await shelterRecord()).occupied, 3);
    const rejection = await request(outsider, '/api/shelters/' + shelter.id + '/registrations', 'POST', {
      party_size: 1, origin_district: 'ernakulam', origin_locality: 'Synthetic outsider', request_key: crypto.randomUUID(),
    });
    assert.equal(rejection.status, 409);
    assert.equal((await request(outsider, '/api/shelter-waitlist/' + waiting.id + '/accept', 'POST', { expected_version: waiting.version })).status, 404);
    await open(citizen, '/shelters/' + shelter.id + '/waitlist', 'Shelter waiting list');
    await citizen.locator('#waitlist-' + waiting.id).getByText('Offered', { exact: true }).waitFor();
    await screenshot(citizen, 'automation-offer-1440.png');
    const acceptance = `/ui/shelters/${shelter.id}/waitlist/${waiting.id}/accept`;
    await submit(citizen, citizen.getByRole('button', { name: 'Accept offer and reserve spaces', exact: true }), acceptance);
    waiting = (await currentWaitlist())[0]; assert.equal(waiting.status, 'ACCEPTED');
    assert.equal((await shelterRecord()).occupied, 3, 'Acceptance must not reserve the same spaces twice.');
    reservation = (await api(citizen, '/api/shelters/' + shelter.id + '/registrations')).find(row => row.id === waiting.registration_id);
    assert.equal(reservation.status, 'RESERVED');
    await api(citizen, '/api/shelter-registrations/' + reservation.id + '/status', 'PATCH', { status: 'CANCELLED', expected_version: reservation.version });
    assert.equal((await shelterRecord()).occupied, 1);

    // A second offer genuinely expires in the durable worker, without touching accepted reservations.
    const next = await api(citizen, '/api/shelters/' + shelter.id + '/waitlist', 'POST', {
      party_size: 2, origin_district: 'ernakulam', origin_locality: 'Synthetic expiry origin', request_key: crypto.randomUUID(),
    });
    assert.equal(next.status, 'OFFERED');
    await timestampFixture('expire-offer', next.id); await checks();
    assert.equal((await currentWaitlist()).find(row => row.id === next.id).status, 'EXPIRED');
    assert.equal((await shelterRecord()).occupied, 1);

    // Administrator supplies coverage/capability, reviews a ranked candidate and deliberately assigns.
    rescue = await api(admin, '/api/management/teams', 'POST', { name: label + ' Rescue', team_type: 'Rescue' });
    rescueEmail = `automation-rescue-${stamp}@example.com`;
    await api(admin, '/api/management/team-accounts', 'POST', { full_name: label + ' rescue member', email: rescueEmail, password, team_id: rescue.id });
    await open(admin, '/team-coverage/' + rescue.id, 'Team operating areas');
    await admin.getByText('Choose specific localities', { exact: true }).click();
    await admin.locator('input[name="area:ernakulam-aluva"]').check();
    await admin.locator('input[name="capability:water_rescue"]').check();
    await admin.getByLabel('Operating note', { exact: false }).fill(label + ' declared water rescue area');
    await submit(admin, admin.getByRole('button', { name: 'Save operating areas', exact: true }), '/ui/teams/' + rescue.id + '/coverage');
    await admin.getByText('Team operating areas and capabilities saved.', { exact: true }).waitFor();
    incident = await api(citizen, '/api/incidents/', 'POST', { message: label + ' synthetic flood in Aluva', location: 'Aluva, Ernakulam', people_affected: 2, help_required: 'Synthetic rescue exercise' });
    await api(admin, '/api/incidents/' + incident.id + '/status', 'PATCH', { status: 'VERIFIED', note: label + ' verified fixture' });
    await open(admin, '/reports/' + incident.id, 'Incident details');
    await admin.locator('#team-recommendations').getByRole('heading', { name: 'Suggested response teams', exact: true }).waitFor();
    await admin.getByLabel('Required capability', { exact: false }).selectOption('water_rescue');
    const filtered = admin.waitForResponse(r => new URL(r.url()).pathname === `/ui/reports/${incident.id}/team-recommendations` && r.status() === 200);
    await admin.getByRole('button', { name: 'Refresh suggestions', exact: true }).click(); await filtered;
    const candidate = admin.locator(`[data-recommended-team="${rescue.id}"]`);
    await candidate.getByRole('button', { name: 'Assign ' + rescue.name, exact: true }).waitFor();
    await screenshot(admin, 'automation-recommendations-1440.png');
    assert.equal((await api(admin, '/api/incidents/' + incident.id)).assigned_team_id, null);
    const assignedNavigation = admin.waitForNavigation({ waitUntil: 'domcontentloaded' });
    await submit(admin, candidate.getByRole('button', { name: 'Assign ' + rescue.name, exact: true }), `/ui/reports/${incident.id}/assign`);
    await assignedNavigation;
    await admin.getByRole('heading', { name: 'Incident details', exact: true }).waitFor();
    assert.equal((await api(admin, '/api/incidents/' + incident.id)).assigned_team_id, rescue.id);
    assert.equal((await request(citizen, `/api/admin/incidents/${incident.id}/team-recommendations`)).status, 403);

    for (const width of [1440, 320]) {
      await citizen.setViewportSize({ width, height: 950 });
      await open(citizen, '/alert-subscriptions', 'Follow alert areas'); await screenshot(citizen, `automation-follows-${width}.png`);
      await open(citizen, '/shelters/' + shelter.id + '/waitlist', 'Shelter waiting list'); await screenshot(citizen, `automation-waitlist-${width}.png`);
      await admin.setViewportSize({ width, height: 950 });
      await open(admin, '/team-coverage/' + rescue.id, 'Team operating areas'); await screenshot(admin, `automation-coverage-${width}.png`);
      await open(admin, '/automation-settings', 'Automation settings'); await screenshot(admin, `automation-settings-${width}.png`);
    }
    assert.deepEqual(errors, []);
    completed = true;
    console.log('Passed: area alert timing/deduplication, staff/admin capacity reminders, waiting offers/acceptance/expiry, reviewed team recommendations, privacy, and 1440/320 layouts.');
  } finally {
    // Recoverable cleanup is scoped to the fixtures created by this invocation.
    try {
      for (const alert of alerts) await api(admin, '/api/alerts/' + alert.id + '/expire', 'POST');
      for (const follow of subscriptions) await api(citizen, '/api/alert-subscriptions/' + follow.id + '/unsubscribe', 'POST');
      if (shelter) {
        for (const entry of await currentWaitlist()) if (['WAITING', 'OFFERED'].includes(entry.status)) await api(citizen, '/api/shelter-waitlist/' + entry.id + '/cancel', 'POST', { expected_version: entry.version });
        for (const entry of await api(citizen, '/api/shelters/' + shelter.id + '/registrations')) if (entry.status === 'RESERVED') await api(citizen, '/api/shelter-registrations/' + entry.id + '/status', 'PATCH', { status: 'CANCELLED', expected_version: entry.version });
        await capacity(0, 'CLOSED');
      }
      if (incident && rescueEmail) {
        const record = await api(admin, '/api/incidents/' + incident.id);
        if (record.assigned_team_id === rescue.id && record.status === 'ASSIGNED') {
          await login(pages.rescue, rescueEmail, password);
          await api(pages.rescue, `/api/operations/incidents/${incident.id}/accept`, 'POST', { note: label + ' test cleanup' });
          for (const status of ['EN_ROUTE', 'IN_PROGRESS', 'RESOLVED']) await api(pages.rescue, `/api/operations/incidents/${incident.id}/progress`, 'POST', { status, note: label + ' test cleanup' });
          await api(admin, '/api/incidents/' + incident.id + '/close', 'POST', { reason: label + ' completed synthetic exercise' });
        }
      }
    } catch { console.log('Synthetic cleanup needs review; no real records were targeted.'); }
    await browser.close();
    if (!completed && errors.length) console.log('Browser errors:', JSON.stringify(errors));
  }
}

main().catch(error => {
  let output = String(error?.stack || error);
  for (const value of redact) if (value) output = output.split(value).join('[redacted]');
  console.error(output); process.exitCode = 1;
});
