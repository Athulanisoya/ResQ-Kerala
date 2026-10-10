/* Run after scripts/start.ps1 with Playwright available on NODE_PATH. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

async function main() {
  const root = path.resolve(__dirname, '..');
  const runtime = path.join(root, '.runtime');
  const demo = JSON.parse(fs.readFileSync(path.join(runtime, 'demo-accounts.json'), 'utf8'));
  const qa = path.join(runtime, 'qa');
  fs.mkdirSync(qa, { recursive: true });
  const base = process.env.RESQ_TEST_URL || 'http://127.0.0.1:8013';
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const errors = [];
  const contexts = [];
  async function page(width = 1440, height = 1000) {
    const context = await browser.newContext({ viewport: { width, height } });
    contexts.push(context);
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', r => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`); });
    return page;
  }
  async function login(page, role) {
    const account = demo.accounts.find(a => a.role === role);
    await page.goto(base + '/login');
    await page.getByLabel('Email address').fill(account.email);
    await page.getByLabel('Password', { exact: true }).fill(demo.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
  }
  try {
    const citizen = await page();
    await citizen.goto(base + '/login');
    assert.equal(await citizen.evaluate(() => typeof htmx), 'object');
    await citizen.screenshot({ path: path.join(qa, 'login-desktop.png'), fullPage: true });
    await citizen.getByRole('link', { name: 'Create an account', exact: true }).click();
    await citizen.waitForURL(base + '/register');
    const email = `week1.browser.${Date.now()}@example.com`;
    const password = crypto.randomBytes(24).toString('base64url');
    await citizen.getByLabel('Full name').fill('Week 1 Browser Check');
    await citizen.getByLabel('Email address').fill(email);
    await citizen.getByLabel('Password', { exact: true }).fill(password);
    await citizen.getByRole('button', { name: 'Create my account', exact: true }).click();
    await citizen.waitForURL(base + '/dashboard');
    const initial = await citizen.evaluate(() => performance.timeOrigin);
    await citizen.getByRole('link', { name: 'New report', exact: true }).click();
    await citizen.waitForURL(base + '/reports/new');
    assert.equal(await citizen.evaluate(() => performance.timeOrigin), initial, 'HTMX navigation should not reload the page');
    await citizen.getByLabel('Location', { exact: false }).fill('Chengannur — near the bridge');
    await citizen.getByLabel('What is happening?', { exact: false }).fill('Browser verification: flood water entered a house near the bridge. Four people need evacuation.');
    await citizen.getByLabel('Number of people affected', { exact: false }).fill('4');
    await citizen.getByLabel('Help needed', { exact: false }).fill('Evacuation assistance');
    await citizen.getByRole('button', { name: 'Submit report', exact: true }).click();
    await citizen.waitForURL(/\/reports\/\d+$/);
    const reportPath = new URL(citizen.url()).pathname;
    const reportId = Number(reportPath.split('/').at(-1));
    fs.writeFileSync(path.join(qa, 'browser-record.json'), JSON.stringify({ email, report_id: reportId }));
    await citizen.reload();
    await citizen.getByRole('heading', { name: 'Incident details', exact: true }).waitFor();
    const admin = await page();
    await login(admin, 'admin');
    await admin.goto(base + reportPath);
    await admin.getByLabel('Next status', { exact: true }).selectOption('UNDER_REVIEW');
    await admin.getByLabel('Review note', { exact: false }).fill('Browser check: report details reviewed.');
    await admin.getByRole('button', { name: 'Update status', exact: true }).click();
    await admin.waitForLoadState('networkidle');
    await admin.getByLabel('Next status', { exact: true }).selectOption('VERIFIED');
    await admin.getByLabel('Review note', { exact: false }).fill('Browser check: location and help request verified.');
    await admin.getByRole('button', { name: 'Update status', exact: true }).click();
    await admin.getByRole('heading', { name: 'Assign a team', exact: true }).waitFor();
    const teamId = await admin.locator('#team_id option').evaluateAll(options => options.find(o => o.value)?.value);
    assert.ok(teamId, 'A response team must be available');
    await admin.getByLabel('Response team', { exact: true }).selectOption(teamId);
    await admin.getByRole('button', { name: 'Assign team', exact: true }).click();
    await admin.getByText('ASSIGNED TO THIS INCIDENT', { exact: true }).waitFor();
    await admin.screenshot({ path: path.join(qa, 'admin-assigned-desktop.png'), fullPage: true });
    await citizen.reload();
    await citizen.getByText('ASSIGNED TO THIS INCIDENT', { exact: true }).waitFor();
    const states = await citizen.locator('.timeline-event h3').allTextContents();
    assert.deepEqual(states, ['Submitted', 'Under Review', 'Verified', 'Assigned']);
    await citizen.screenshot({ path: path.join(qa, 'citizen-status-desktop.png'), fullPage: true });
    await citizen.setViewportSize({ width: 390, height: 844 });
    await citizen.screenshot({ path: path.join(qa, 'citizen-status-mobile.png'), fullPage: true });
    assert.equal(await citizen.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'Mobile should not have horizontal overflow');
    const team = await page();
    await login(team, 'response_team');
    await team.goto(base + '/reports');
    await team.getByRole('link', { name: /Chengannur/ }).first().click();
    await team.getByRole('heading', { name: 'Incident details', exact: true }).waitFor();
    await team.screenshot({ path: path.join(qa, 'team-assignment-desktop.png'), fullPage: true });
    await citizen.getByRole('button', { name: 'Sign out', exact: true }).click();
    await citizen.waitForURL(base + '/login');
    await citizen.goto(base + '/dashboard');
    await citizen.waitForURL(base + '/login');
    assert.deepEqual(errors, [], `Browser errors: ${errors.join('; ')}`);
    fs.writeFileSync(path.join(qa, 'browser-result.json'), JSON.stringify({ passed: true, report_id: reportId,
      checks: ['registration', 'HTMX navigation without reload', 'report submission', 'session reload', 'admin review', 'verification', 'team assignment', 'citizen timeline', 'team view', 'mobile overflow', 'logout'], screenshots: 5, browser_errors: errors }, null, 2));
    console.log('Browser workflow passed: registration -> report -> review -> verified -> assigned -> citizen/team tracking -> logout. Desktop/mobile screenshots saved in .runtime/qa.');
  } finally {
    for (const context of contexts) await context.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error.message); process.exit(1); });
