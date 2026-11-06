const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

async function setup() {
  const base = process.env.BASE_URL || 'http://127.0.0.1:8014';
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
  const root = path.resolve(__dirname, '..'), qa = path.join(root, '.runtime', 'qa');
  fs.mkdirSync(qa, { recursive: true });
  const demo = JSON.parse(fs.readFileSync(process.env.RESQ_DEMO_ACCOUNTS || path.join(root, '.runtime', 'docker-demo-accounts.json')));
  const password = 'Synthetic-features-' + crypto.randomUUID() + '!';
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const accounts = [], tokens = [], errors = [];
  async function request(token, route, method = 'GET', data) {
    const r = await context.request.fetch(base + route, { method, headers: token ? { Authorization: 'Bearer ' + token } : {}, ...(data === undefined ? {} : { data }) });
    let body; try { body = await r.json(); } catch {}
    return { status: r.status(), body };
  }
  async function api(token, route, method = 'GET', data) {
    const r = await request(token, route, method, data);
    assert.ok(r.status >= 200 && r.status < 300, method + ' ' + route + ' HTTP ' + r.status);
    return r.body;
  }
  const admin = await api(null, '/api/auth/login', 'POST', { email: demo.accounts.find(x => x.role === 'admin').email, password: demo.password });
  tokens.push(admin.access_token);
  async function citizen(label) {
    const auth = await api(null, '/api/auth/register', 'POST', { full_name: label, email: 'feature-' + crypto.randomUUID() + '@example.com', password });
    accounts.push(auth.user); tokens.push(auth.access_token); return auth;
  }
  async function page(auth) {
    const p = await context.newPage(); p.setDefaultTimeout(15000); p.on('pageerror', e => errors.push(e.message));
    await p.goto(base + '/login');
    await p.getByLabel('Email address', { exact: true }).fill(auth.user.email);
    await p.getByLabel('Password', { exact: true }).fill(auth === admin ? demo.password : password);
    await p.getByRole('button', { name: 'Sign in', exact: true }).click();
    await p.waitForURL(base + '/dashboard'); await p.locator('#app-root[data-authenticated=true][data-user-id]').waitFor();
    return p;
  }
  async function open(p, route, heading) {
    await p.goto(base + route); await p.getByRole('heading', { name: heading, exact: true }).waitFor();
    await p.waitForFunction(() => !document.querySelector('.htmx-swapping,.htmx-settling') && Boolean(document.querySelector('.canopy-shell-header')));
  }
  async function submit(p, f) {
    const action = await f.getAttribute('action');
    const promise = p.waitForResponse(r => new URL(r.url()).pathname === action && r.request().method() === 'POST');
    await f.locator('button[type=submit]').click(); const r = await promise;
    assert.equal(r.status(), 200, action);
    await p.waitForFunction(() => !document.querySelector('.htmx-request,.htmx-settling,.htmx-swapping'));
  }
  async function screenshot(p, name) {
    const sizes = await p.evaluate(() => ({ w: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(sizes.document <= sizes.w + 1, name + ' has horizontal overflow');
    await p.screenshot({ path: path.join(qa, name + '.png'), fullPage: true });
  }
  async function close() {
    for (const a of accounts) await request(admin.access_token, '/api/management/users/' + a.id, 'PATCH', { role: 'citizen', active: false, team_id: null });
    for (const token of tokens) await request(token, '/api/auth/logout', 'POST').catch(() => {});
    await browser.close();
  }
  return { base, context, admin, request, api, citizen, page, open, submit, screenshot, close, errors, assert };
}
module.exports = { setup };
