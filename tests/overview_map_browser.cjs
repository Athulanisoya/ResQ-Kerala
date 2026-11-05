/* Local Docker end-to-end checks; creates timestamp-labelled synthetic fixtures only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const secretsToRedact = [];

async function main() {
  const root = path.resolve(__dirname, '..');
  const base = process.env.BASE_URL || process.env.RESQ_TEST_URL || 'http://127.0.0.1:8014';
  const demoPath = process.env.RESQ_DEMO_ACCOUNTS || path.join(root, '.runtime', 'docker-demo-accounts.json');
  const demo = JSON.parse(fs.readFileSync(demoPath, 'utf8'));
  const qa = path.join(root, '.runtime', 'qa');
  fs.mkdirSync(qa, { recursive: true });
  const stamp = Date.now();
  const label = `Synthetic map browser ${stamp}`;
  const password = `Synthetic-map-${crypto.randomUUID()}!`;
  secretsToRedact.push(demo.password, password);
  const errors = [];
  const createdAlerts = [];
  let fixtureShelter;
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const pages = {};
  for (const role of ['citizen', 'admin', 'response_team', 'shelter_staff']) {
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.status() >= 500) errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
    });
    pages[role] = page;
  }
  const { citizen, admin, response_team: team, shelter_staff: staff } = pages;
  async function login(page, email, secret) {
    await page.goto(base + '/login');
    await page.getByLabel('Email address').fill(email);
    await page.getByLabel('Password', { exact: true }).fill(secret);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    await mapReady(page);
  }
  async function request(page, route, method = 'GET', body) {
    return page.evaluate(async ({ route, method, body }) => {
      const response = await fetch(route, {
        method,
        headers: {
          Authorization: 'Bearer ' + sessionStorage.getItem('resq-week1-session'),
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      return { status: response.status, data: await response.json() };
    }, { route, method, body });
  }
  async function api(page, route, method = 'GET', body) {
    const response = await request(page, route, method, body);
    assert.ok(response.status >= 200 && response.status < 300, `${method} ${route}: HTTP ${response.status}`);
    return response.data;
  }
  async function mapReady(page) {
    await page.locator('[data-map-status]').filter({ hasText: 'Map checked' }).waitFor();
    assert.equal(await page.locator('[data-map-canvas] .leaflet-container').count(), 0);
    assert.equal(await page.locator('[data-map-canvas].leaflet-container').count(), 1);
    assert.equal(await page.locator('[data-district]').count(), 14);
  }
  async function refresh(page) {
    const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/overview/map' && response.status() === 200);
    await page.getByRole('button', { name: 'Refresh map data', exact: true }).click();
    const payload = await (await response).json();
    await mapReady(page);
    return payload;
  }
  async function noOverflow(page, stage) {
    const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(dimensions.document <= dimensions.width + 1, `${stage}: ${dimensions.document}px document exceeds ${dimensions.width}px viewport`);
  }
  async function mapScreenshot(page, filename) {
    await page.locator('[data-overview-map]').screenshot({
      path: path.join(qa, filename),
      // A tall element crop otherwise catches the sticky header over its first rows.
      style: '.canopy-shell-header { position: static !important; }',
    });
  }
  async function checkPaint(page) {
    const payload = await api(page, '/api/overview/map');
    assert.equal(payload.districts.length, 14);
    for (const district of payload.districts) {
      assert.equal(await page.locator(`[data-district="${district.id}"]`).getAttribute('data-alert-level'), district.level);
    }
    return payload;
  }
  async function reserve(size, shelter) {
    await citizen.getByLabel('People in your group, including you', { exact: true }).fill(String(size));
    await citizen.getByLabel('Your current district', { exact: true }).selectOption('ernakulam');
    await citizen.getByLabel('Your current locality or landmark', { exact: true }).fill('Synthetic Aluva origin');
    await citizen.getByLabel('Contact phone or email', { exact: false }).fill(`private-map-${stamp}@example.com`);
    await citizen.getByLabel('Your latitude', { exact: false }).fill('10.1076');
    await citizen.getByLabel('Your longitude', { exact: false }).fill('76.3516');
    await citizen.getByLabel('Support needs', { exact: false }).fill(label + ' private support note');
    const saved = citizen.waitForResponse(response => new URL(response.url()).pathname === `/ui/shelters/${shelter.id}/registrations` && response.request().method() === 'POST');
    await citizen.getByRole('button', { name: 'Reserve shelter spaces', exact: true }).click();
    assert.equal((await saved).status(), 200);
    await citizen.getByText('Your spaces are reserved.', { exact: false }).waitFor();
    const rows = await api(citizen, `/api/shelters/${shelter.id}/registrations`);
    const registration = rows.find(row => row.status === 'RESERVED');
    assert.ok(registration);
    assert.equal(registration.party_size, size);
    assert.equal((await api(citizen, `/api/shelters/${shelter.id}`)).occupied, size);
    return registration;
  }
  async function statusClick(page, id, button, expected) {
    await page.locator(`#registration-${id}`).getByRole('button', { name: button, exact: true }).click();
    await page.locator(`#registration-${id} .status`).filter({ hasText: new RegExp(`^${expected}$`, 'i') }).waitFor();
  }
  try {
    for (const role of ['citizen', 'admin', 'response_team']) {
      await login(pages[role], demo.accounts.find(account => account.role === role).email, demo.password);
      await checkPaint(pages[role]);
    }
    assert.equal((await context.request.get(base + '/api/overview/map')).status(), 401);
    assert.equal((await context.request.get(base + '/api/overview/district-boundaries')).status(), 401);

    const shelterTeam = await api(admin, '/api/management/teams', 'POST', { name: label + ' reception', team_type: 'Shelter' });
    const staffEmail = `map-reception-${stamp}@resq.example.com`;
    await api(admin, '/api/management/team-accounts', 'POST', {
      full_name: label + ' reception member', email: staffEmail, password, team_id: shelterTeam.id,
    });
    const shelter = await api(admin, '/api/shelters', 'POST', {
      name: label + ' shelter', location: 'Synthetic Aluva exercise site', district: 'Ernakulam', locality: 'Aluva',
      address: 'Synthetic fixture only — not a real shelter address', capacity: 8, occupied: 0, team_id: shelterTeam.id,
      contact: 'Synthetic reception contact', source_name: 'Synthetic browser regression fixture',
      latitude: 10.1076, longitude: 76.3516,
    });
    fixtureShelter = shelter;
    await login(staff, staffEmail, password);
    const now = Date.now();
    async function alert(place, level, startOffset = -60000, endOffset = 3600000) {
      const result = await api(admin, '/api/alerts', 'POST', {
        title: `${label} ${place} ${level}`, message: 'Synthetic browser exercise only; not an operational alert.',
        place_id: place, level, starts_at: new Date(now + startOffset).toISOString(), expires_at: new Date(now + endOffset).toISOString(),
      });
      createdAlerts.push(result.id);
      return result;
    }
    const districtAlert = await alert('ernakulam', 'ORANGE');
    const localAlert = await alert('ernakulam-aluva', 'RED');
    const expiredAlert = await alert('kollam', 'RED', -7200000, -3600000);
    const scheduledAlert = await alert('kannur', 'RED', 3600000, 7200000);
    for (const page of [citizen, admin, team]) {
      await refresh(page);
      const payload = await checkPaint(page);
      const district = payload.districts.find(row => row.id === 'ernakulam');
      assert.equal(district.level, 'RED');
      assert.ok(district.alerts.some(row => row.id === districtAlert.id));
      const aluva = payload.localities.find(row => row.id === 'ernakulam-aluva');
      assert.equal(aluva.own_level, 'RED');
      const visibleIds = payload.districts.flatMap(row => row.alerts.map(alert => alert.id));
      assert.ok(!visibleIds.includes(expiredAlert.id) && !visibleIds.includes(scheduledAlert.id));
      const publicMap = JSON.stringify(payload);
      assert.ok(!publicMap.includes('citizen_id') && !publicMap.includes('password'));
      await page.getByLabel('Explore a district', { exact: true }).selectOption('ernakulam');
      await page.getByLabel('Explore a locality', { exact: true }).selectOption('ernakulam-aluva');
      await page.locator('[data-map-details]').getByRole('heading', { name: 'Aluva', exact: true }).waitFor();
      await page.locator('[data-map-zoom-note]').filter({ hasText: 'Coloured dots' }).waitFor();
      assert.ok(await page.locator('.leaflet-overlay-pane path.leaflet-interactive').count() > 14, 'Zoom should expose locality points');
      // Leaflet briefly retains fading tooltip nodes while the marker set repaints.
      await page.waitForFunction(() => {
        const labels = [...document.querySelectorAll('.map-locality-label')].filter(node => node.textContent.startsWith('Aluva ·'));
        return labels.length === 1 && Number(getComputedStyle(labels[0]).opacity) > .5;
      }, null, { timeout: 3000 });
      await page.locator('.map-locality-label').filter({ hasText: /^Aluva ·/ }).waitFor();
      assert.equal(await page.locator('.overview-map-sea').isVisible(), false, 'Sea annotation should be hidden in detailed locality view');
      const shelterDetails = page.locator('[data-map-details] .map-shelter-item').filter({ hasText: shelter.name });
      assert.match(await shelterDetails.innerText(), /km straight-line from Aluva centre/);
    }
    await mapScreenshot(citizen, 'overview-locality-1440.png');
    await citizen.locator(`[title^="${shelter.name} ·"]`).click();
    const popup = citizen.locator('.map-shelter-popup').filter({ hasText: shelter.name });
    await popup.getByRole('heading', { name: shelter.name, exact: true }).waitFor();
    assert.ok((await popup.innerText()).includes('Record updated:'));
    await mapScreenshot(citizen, 'overview-shelter-pin-1440.png');
    await popup.getByRole('link', { name: 'Register to join', exact: true }).click();
    await citizen.waitForURL(new RegExp(`/shelters/${shelter.id}/join`));
    await citizen.getByRole('heading', { name: 'Reserve your group’s spaces', exact: true }).waitFor();
    assert.equal(await citizen.getByLabel('Your current district', { exact: true }).inputValue(), 'ernakulam');
    assert.equal(await citizen.getByLabel('Your current locality or landmark', { exact: true }).inputValue(), 'Aluva');
    const cancelled = await reserve(3, shelter);
    const reservedMap = await refresh(admin);
    assert.equal(reservedMap.shelters.find(row => row.id === shelter.id).available_capacity, 5);
    assert.ok(!JSON.stringify(reservedMap).includes(`private-map-${stamp}`));
    assert.equal((await request(team, `/api/shelters/${shelter.id}/registrations`)).status, 403);
    assert.equal((await request(citizen, `/api/shelter-registrations/${cancelled.id}/status`, 'PATCH', { status: 'ARRIVED', expected_version: cancelled.version })).status, 403);
    const secondCitizenEmail = `map-other-${stamp}@resq.example.com`;
    const otherRegistration = await context.request.post(base + '/api/auth/register', {
      data: { full_name: label + ' other citizen', email: secondCitizenEmail, password },
    });
    assert.equal(otherRegistration.status(), 201);
    const otherLogin = await context.request.post(base + '/api/auth/login', { data: { email: secondCitizenEmail, password } });
    assert.equal(otherLogin.status(), 200);
    const otherToken = (await otherLogin.json()).access_token;
    const privateList = await context.request.get(base + `/api/shelters/${shelter.id}/registrations`, { headers: { Authorization: 'Bearer ' + otherToken } });
    assert.deepEqual(await privateList.json(), []);
    const privateChange = await context.request.patch(base + `/api/shelter-registrations/${cancelled.id}/status`, {
      headers: { Authorization: 'Bearer ' + otherToken }, data: { status: 'CANCELLED', expected_version: cancelled.version },
    });
    assert.equal(privateChange.status(), 404);
    await statusClick(citizen, cancelled.id, 'Cancel reservation and release spaces', 'Cancelled');
    assert.equal((await api(citizen, `/api/shelters/${shelter.id}`)).occupied, 0);
    const arrived = await reserve(2, shelter);
    await staff.goto(base + `/shelters/${shelter.id}/join`);
    await staff.getByRole('heading', { name: 'Reception register', exact: true }).waitFor();
    await statusClick(staff, arrived.id, 'Confirm arrival', 'Arrived');
    assert.equal((await api(staff, `/api/shelters/${shelter.id}`)).occupied, 2);
    await statusClick(staff, arrived.id, 'Record departure and release spaces', 'Departed');
    assert.equal((await api(staff, `/api/shelters/${shelter.id}`)).occupied, 0);
    const history = await api(citizen, `/api/shelters/${shelter.id}/registrations`);
    assert.deepEqual(history.find(row => row.id === arrived.id).history.map(row => row.status), ['RESERVED', 'ARRIVED', 'DEPARTED']);
    assert.equal(history.find(row => row.id === cancelled.id).status, 'CANCELLED');

    await api(admin, `/api/alerts/${localAlert.id}/expire`, 'POST');
    const expired = await refresh(admin);
    assert.ok(!expired.districts.flatMap(row => row.alerts).some(row => row.id === localAlert.id));

    // HTMX navigation must dispose the old map and create exactly one replacement.
    await citizen.locator('[data-nav="dashboard"]').click();
    await citizen.waitForURL(base + '/dashboard');
    await mapReady(citizen);
    for (let round = 0; round < 2; round++) {
      await citizen.locator('[data-nav="shelters"]').click();
      await citizen.waitForURL(base + '/shelters');
      await citizen.locator('[data-nav="dashboard"]').click();
      await citizen.waitForURL(base + '/dashboard');
      await mapReady(citizen);
    }
    for (const width of [1440, 320]) {
      for (const [role, page] of [['citizen', citizen], ['admin', admin], ['response_team', team]]) {
        await page.setViewportSize({ width, height: 1000 });
        await page.getByRole('button', { name: 'All Kerala', exact: true }).click();
        await noOverflow(page, `${role} Overview at ${width}`);
      }
      await mapScreenshot(citizen, `overview-map-${width}.png`);
      await citizen.goto(base + `/shelters/${shelter.id}/join`);
      await citizen.getByRole('heading', { name: 'Register for a shelter', exact: true }).waitFor();
      await noOverflow(citizen, `shelter registration at ${width}`);
      await citizen.screenshot({ path: path.join(qa, `shelter-registration-${width}.png`), fullPage: true });
      await citizen.goto(base + '/dashboard');
      await mapReady(citizen);
    }

    await citizen.route('**/api/overview/map', route => route.abort('failed'));
    await citizen.getByRole('button', { name: 'Refresh map data', exact: true }).click();
    await citizen.locator('[data-overview-map].overview-map-unavailable').waitFor();
    await citizen.locator('[data-map-details]').getByText('Current alert and shelter data could not be checked.', { exact: false }).waitFor();
    assert.equal(await citizen.getByLabel('Explore a district', { exact: true }).isDisabled(), true);
    const fills = await citizen.locator('[data-district]').evaluateAll(paths => paths.map(path => path.getAttribute('fill')));
    assert.equal(fills.length, 14);
    assert.ok(fills.every(fill => fill === '#c7cec8'), 'Failed evidence must neutralize every retained alert colour');
    const announcements = await citizen.locator('[data-district]').evaluateAll(paths => paths.map(path => ({
      level: path.getAttribute('data-alert-level'), label: path.getAttribute('aria-label'),
    })));
    assert.ok(announcements.every(row => row.level === 'UNKNOWN' && /unknown/i.test(row.label)),
      'Failed evidence must also clear previous alert status from accessible district controls');
    await noOverflow(citizen, 'unavailable map at 320');
    await mapScreenshot(citizen, 'overview-map-unavailable-320.png');
    await citizen.unroute('**/api/overview/map');
    await refresh(citizen);
    await checkPaint(citizen);
    assert.deepEqual(errors, [], 'Browser and server errors');
    console.log('Overview map and shelter registration checks passed for 3 roles at 1440px and 320px.');
    console.log(`Synthetic fixture shelter #${shelter.id}; all reservations released and test alerts expired after verification.`);
  } finally {
    if (fixtureShelter) {
      try {
        const rows = await api(admin, `/api/shelters/${fixtureShelter.id}/registrations`);
        for (const row of rows.filter(row => ['RESERVED', 'ARRIVED'].includes(row.status))) {
          await api(admin, `/api/shelter-registrations/${row.id}/status`, 'PATCH', {
            status: row.status === 'ARRIVED' ? 'DEPARTED' : 'CANCELLED', expected_version: row.version,
            note: 'Synthetic browser regression cleanup',
          });
        }
      } catch { /* Preserve the original test failure; records remain clearly labelled. */ }
    }
    // Expire only this run's synthetic alerts; retain labelled records for audit.
    for (const id of createdAlerts) {
      try { await api(admin, `/api/alerts/${id}/expire`, 'POST'); } catch { /* Preserve the original test failure. */ }
    }
    await browser.close();
  }
}

main().catch(error => {
  let message = error.message;
  for (const secret of secretsToRedact.filter(Boolean)) message = message.split(secret).join('[REDACTED]');
  console.error(message);
  process.exitCode = 1;
});
