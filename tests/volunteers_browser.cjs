/* Local synthetic volunteer workflow checks. Requires Playwright on NODE_PATH. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const secrets = [];

async function main() {
  const root = path.resolve(__dirname, '..');
  const base = process.env.BASE_URL || 'http://127.0.0.1:8014';
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Use the local app for synthetic fixtures.');
  const demo = JSON.parse(fs.readFileSync(process.env.RESQ_DEMO_ACCOUNTS || path.join(root, '.runtime', 'docker-demo-accounts.json'), 'utf8'));
  const label = 'Synthetic volunteer browser ' + Date.now();
  const password = 'Synthetic-volunteer-' + crypto.randomUUID() + '!'; secrets.push(demo.password, password);
  const qa = path.join(root, '.runtime', 'qa'); fs.mkdirSync(qa, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const pages = {};
  const errors = [], accounts = [], shifts = [];
  for (const role of ['admin', 'citizen', 'outsider', 'team']) {
    const page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message)); pages[role] = page;
  }
  let adminToken, citizenToken, outsiderToken, teamToken, application, shift, signup;
  const unwrapApplication = response => response && Object.hasOwn(response, 'application') ? response.application : response;
  const unwrapShift = response => response?.shift ?? response;
  const unwrapSignup = response => response?.signup ?? response;

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
  async function login(page, email, secret) {
    await page.goto(base + '/login');
    await page.getByLabel('Email address', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(secret);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    await page.locator('#app-root[data-authenticated=true][data-user-id]').waitFor();
    const token = await page.evaluate(() => sessionStorage.getItem('resq-week1-session'));
    secrets.push(token); return token;
  }
  async function open(page, route) {
    await page.goto(base + route);
    await page.getByRole('heading', { name: 'Volunteer community', exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelector('.main-nav [data-nav=volunteers]')?.getAttribute('aria-current') === 'page' && !document.querySelector('.htmx-settling,.htmx-swapping'));
    await noOverflow(page, route);
  }
  async function noOverflow(page, route) {
    const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(dimensions.document <= dimensions.width + 1, route + ': horizontal overflow');
  }
  async function submit(page, form) {
    const action = await form.getAttribute('action'); assert.ok(action?.startsWith('/ui/volunteers'));
    const response = page.waitForResponse(r => new URL(r.url()).pathname === action && r.request().method() === 'POST');
    await form.locator('button[type=submit]').click();
    const result = await response;
    assert.equal(result.status(), 200, action + ' HX=' + Boolean(result.request().headers()['hx-request']) + ' bearer=' + Boolean(result.request().headers()['authorization']));
  }
  async function ownApplication(token = citizenToken) { return unwrapApplication(await api(token, '/api/volunteers/me')); }
  async function shiftList(token = adminToken) { const data = await api(token, '/api/volunteers/shifts'); return data.shifts; }
  async function currentShift(id) { return (await shiftList()).find(row => row.id === id); }
  const istInput = instant => new Date(instant.getTime() + 19800000).toISOString().slice(0, 16);

  try {
    for (const role of ['citizen', 'outsider']) {
      const auth = await api(null, '/api/auth/register', 'POST', { full_name: label + ' ' + role,
        email: 'volunteer-' + role + '-' + crypto.randomUUID() + '@example.com', password });
      accounts.push(auth.user); secrets.push(auth.access_token);
      if (role === 'citizen') citizenToken = await login(pages.citizen, auth.user.email, password);
      else outsiderToken = await login(pages.outsider, auth.user.email, password);
      await request(auth.access_token, '/api/auth/logout', 'POST');
    }
    adminToken = await login(pages.admin, demo.accounts.find(row => row.role === 'admin').email, demo.password);
    teamToken = await login(pages.team, demo.accounts.find(row => row.role === 'response_team').email, demo.password);
    const catalog = await api(citizenToken, '/api/volunteers/catalog'); assert.ok(catalog);
    assert.equal((await request(teamToken, '/api/volunteers/catalog')).status, 403);
    assert.equal((await request(citizenToken, '/api/volunteers/admin/applications')).status, 403);

    // Citizen applies through the actual HTMX form; account privileges remain citizen.
    await open(pages.citizen, '/volunteers?tab=application');
    const applicationForm = pages.citizen.locator('form').filter({ has: pages.citizen.locator('[name=ward]') });
    await applicationForm.locator('[name=district_id]').selectOption('ernakulam');
    const locality = applicationForm.locator('[name=locality_id]');
    if (await locality.count()) await locality.selectOption('ernakulam-aluva');
    await applicationForm.locator('[name=ward]').fill('Synthetic Ward 12');
    await applicationForm.locator('input[type=checkbox][value=logistics]').check();
    await applicationForm.locator('[name=availability]').fill(label + ': weekend mornings, synthetic exercise only');
    await applicationForm.locator('[name=consent]').check();
    await submit(pages.citizen, applicationForm);
    application = await ownApplication(); assert.equal(application.status, 'PENDING'); assert.equal(application.user_id, accounts[0].id);
    assert.equal((await api(citizenToken, '/api/users/me')).role, 'citizen');
    assert.equal(unwrapApplication(await api(outsiderToken, '/api/volunteers/me')), null, 'Another account has no application data');

    // An administrator reviews the named account and deliberately approves it.
    await open(pages.admin, '/volunteers?tab=applications');
    const reviewForm = pages.admin.locator(`form[action$="/${application.id}/review"]`);
    await reviewForm.locator('[name=decision]').selectOption('APPROVED');
    await reviewForm.locator('[name=note]').fill(label + ': reviewed synthetic volunteer application');
    await submit(pages.admin, reviewForm);
    application = await ownApplication(); assert.equal(application.status, 'APPROVED');
    const staleApproval = await request(adminToken, '/api/volunteers/admin/applications/' + application.id + '/review', 'POST', {
      expected_version: application.version - 1, decision: 'REJECTED', note: label + ' stale update must fail' });
    assert.equal(staleApproval.status, 409);

    // Administrator creates a future logistics shift with one slot through its HTMX form.
    await open(pages.admin, '/volunteers?tab=shifts');
    const shiftForm = pages.admin.locator('form').filter({ has: pages.admin.locator('[name=title]') });
    await shiftForm.locator('[name=title]').fill(label + ' relief shift');
    await shiftForm.locator('[name=kind]').selectOption('RELIEF');
    await shiftForm.locator('[name=place_id]').selectOption('ernakulam-aluva');
    const start = new Date(Date.now() + 36 * 3600000), end = new Date(start.getTime() + 2 * 3600000);
    await shiftForm.locator('[name=starts_at]').fill(istInput(start));
    await shiftForm.locator('[name=ends_at]').fill(istInput(end));
    await shiftForm.locator('[name=slots]').fill('1');
    await shiftForm.locator('input[type=checkbox][value=logistics]').check();
    await shiftForm.locator('[name=instructions]').fill(label + ': report to the synthetic relief desk');
    await submit(pages.admin, shiftForm);
    shift = (await shiftList()).find(row => row.title === label + ' relief shift'); assert.ok(shift); shifts.push(shift.id);
    assert.equal(shift.slots, 1);
    assert.equal((await request(outsiderToken, '/api/volunteers/shifts/' + shift.id + '/signup', 'POST', { expected_version: shift.version })).status, 409, 'Unapproved accounts cannot sign up');

    await open(pages.citizen, '/volunteers?tab=shifts');
    const joinForm = pages.citizen.locator(`form[action$="/${shift.id}/signup"]`);
    await submit(pages.citizen, joinForm);
    const ownShifts = await api(citizenToken, '/api/volunteers/shifts');
    signup = ownShifts.my_signups.find(row => row.shift_id === shift.id); assert.ok(signup); assert.equal(signup.status, 'REGISTERED');
    assert.equal((await request(outsiderToken, '/api/volunteers/admin/shifts/' + shift.id + '/roster')).status, 403);
    assert.equal((await request(teamToken, '/api/volunteers/shifts')).status, 403);
    const publicShifts = JSON.stringify(await api(outsiderToken, '/api/volunteers/shifts'));
    assert.equal(publicShifts.includes(accounts[0].email), false, 'Citizen shift listings expose no roster email');
    assert.equal(publicShifts.includes(application.availability), false, 'Citizen shift listings expose no private availability');

    await open(pages.admin, '/volunteers?tab=roster&shift_id=' + shift.id);
    await pages.admin.getByText(accounts[0].email, { exact: false }).waitFor();
    assert.equal((await request(adminToken, '/api/volunteers/admin/signups/' + signup.id + '/attendance', 'POST', {
      expected_version: signup.version, status: 'CHECKED_IN', note: label + ' early attendance must fail' })).status, 409);
    await pages.admin.screenshot({ path: path.join(qa, 'volunteer-roster-1440.png'), fullPage: true });

    // Only the signup owner may cancel; the slot is released exactly once.
    assert.equal((await request(outsiderToken, '/api/volunteers/signups/' + signup.id + '/cancel', 'POST', {
      expected_version: signup.version, note: label + ' outsider cancellation must fail' })).status, 404);
    await open(pages.citizen, '/volunteers?tab=shifts');
    const cancelForm = pages.citizen.locator(`form[action$="/${signup.id}/cancel"]`);
    await cancelForm.locator('[name=note]').fill(label + ' own signup cancellation');
    await submit(pages.citizen, cancelForm);
    signup = (await api(citizenToken, '/api/volunteers/shifts')).my_signups.find(row => row.id === signup.id);
    assert.equal(signup.status, 'CANCELLED');
    assert.equal((await request(citizenToken, '/api/volunteers/signups/' + signup.id + '/cancel', 'POST', {
      expected_version: signup.version - 1, note: label + ' repeated stale cancellation' })).status, 409);

    // Revising an approved application requires review again and releases future duties.
    const current = await currentShift(shift.id);
    signup = unwrapSignup(await api(citizenToken, '/api/volunteers/shifts/' + shift.id + '/signup', 'POST', { expected_version: current.version }));
    const repeated = unwrapSignup(await api(citizenToken, '/api/volunteers/shifts/' + shift.id + '/signup', 'POST', { expected_version: current.version }));
    assert.equal(repeated.id, signup.id); assert.equal(repeated.version, signup.version, 'Repeated join is idempotent');
    await open(pages.citizen, '/volunteers?tab=application');
    await applicationForm.locator('[name=availability]').fill(label + ': revised availability for a new administrator review');
    await applicationForm.locator('[name=consent]').check();
    await submit(pages.citizen, applicationForm);
    application = await ownApplication(); assert.equal(application.status, 'PENDING');
    signup = (await api(citizenToken, '/api/volunteers/shifts')).my_signups.find(row => row.id === signup.id);
    assert.equal(signup.status, 'CANCELLED');
    assert.equal((await currentShift(shift.id)).available_slots, 1);

    for (const width of [1440, 320]) {
      await pages.citizen.setViewportSize({ width, height: 950 });
      await open(pages.citizen, '/volunteers?tab=application');
      await pages.citizen.screenshot({ path: path.join(qa, 'volunteer-application-' + width + '.png'), fullPage: true });
      await open(pages.citizen, '/volunteers?tab=shifts');
      await pages.citizen.screenshot({ path: path.join(qa, 'volunteer-shifts-' + width + '.png'), fullPage: true });
      await pages.admin.setViewportSize({ width, height: 950 });
      await open(pages.admin, '/volunteers?tab=applications');
      await pages.admin.screenshot({ path: path.join(qa, 'volunteer-review-' + width + '.png'), fullPage: true });
      await open(pages.admin, '/volunteers?tab=roster&shift_id=' + shift.id);
    }
    assert.deepEqual(errors, []);
    console.log('Passed: citizen volunteer application, reviewed approval, admin shift creation, signup and own cancellation, stale versions, early attendance guard, role/privacy checks, and 1440/320 layouts.');
  } finally {
    try {
      if (adminToken) {
        for (const id of shifts) {
          const current = await currentShift(id);
          if (current?.status === 'OPEN') await api(adminToken, '/api/volunteers/shifts/' + id + '/cancel', 'POST', { expected_version: current.version, note: label + ' synthetic fixture cleanup' });
        }
        if (application) {
          const current = await ownApplication();
          if (['APPROVED', 'PENDING'].includes(current?.status)) await api(adminToken, '/api/volunteers/admin/applications/' + current.id + '/review', 'POST', {
            expected_version: current.version, decision: current.status === 'APPROVED' ? 'SUSPENDED' : 'REJECTED', note: label + ' completed synthetic exercise' });
        }
        for (const account of accounts) await api(adminToken, '/api/management/users/' + account.id, 'PATCH', { role: 'citizen', team_id: null, active: false });
      }
    } catch { console.log('Synthetic volunteer cleanup needs review; no real records were targeted.'); }
    for (const token of [citizenToken, outsiderToken, adminToken, teamToken]) if (token) await request(token, '/api/auth/logout', 'POST').catch(() => {});
    await browser.close();
  }
}

main().catch(error => { let output = String(error?.stack || error); for (const secret of secrets) if (secret) output = output.split(secret).join('[redacted]'); console.error(output); process.exitCode = 1; });
