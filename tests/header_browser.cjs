/* Read-only header checks; own sessions only. A badge-response mock stresses 10,000 unread updates without creating notifications. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const secrets = [];

async function main() {
  const root = path.resolve(__dirname, '..');
  const base = process.env.BASE_URL || 'http://127.0.0.1:8014';
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Run header tests against the local application.');
  const demo = JSON.parse(fs.readFileSync(process.env.RESQ_DEMO_ACCOUNTS || path.join(root, '.runtime', 'docker-demo-accounts.json'), 'utf8'));
  secrets.push(demo.password);
  const qa = path.join(root, '.runtime', 'qa'); fs.mkdirSync(qa, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  const errors = [], pages = [];
  const widths = [320, 390, 768, 1024, 1280, 1440, 1920];

  async function login(role) {
    const page = await context.newPage(); page.setDefaultTimeout(15000); pages.push(page);
    await page.route('**/ui/updates/count', route => route.fulfill({ status: 200, contentType: 'text/html',
      body: '<span class="notification-count" aria-label="10000 unread updates" title="10000 unread updates">99+</span>' }));
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 500) errors.push(response.status() + ' ' + new URL(response.url()).pathname); });
    await page.goto(base + '/login');
    await page.getByLabel('Email address', { exact: true }).fill(demo.accounts.find(row => row.role === role).email);
    await page.getByLabel('Password', { exact: true }).fill(demo.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    await page.locator('.canopy-shell-header').waitFor();
    await page.locator('[data-map-status]').filter({ hasText: 'Map checked' }).waitFor();
    await page.locator('#updates-count .notification-count').filter({ hasText: '99+' }).waitFor();
    assert.equal(await page.locator('#updates-count .notification-count').getAttribute('aria-label'), '10000 unread updates');
    return page;
  }

  async function headerReady(page) {
    await page.waitForFunction(() => {
      const header = document.querySelector('.canopy-shell-header');
      const stored = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--site-header-height'));
      return header && Math.abs(stored - Math.ceil(header.getBoundingClientRect().height)) <= 1;
    });
  }

  async function insideViewport(page, locator, description, { vertical = true } = {}) {
    assert.equal(await locator.isVisible(), true, description + ' must be visible');
    const bounds = await locator.boundingBox(); const viewport = page.viewportSize();
    assert.ok(bounds && bounds.x >= -1 && bounds.x + bounds.width <= viewport.width + 1, description + ' exceeds viewport width');
    if (vertical) assert.ok(bounds.y >= -1 && bounds.y + bounds.height <= viewport.height + 1, description + ' exceeds viewport height');
    return bounds;
  }

  async function assertHeader(page, role, width) {
    await headerReady(page);
    const header = page.locator('.canopy-shell-header');
    const bounds = await insideViewport(page, header, role + ' header at ' + width);
    assert.ok(bounds.height <= page.viewportSize().height * .65, 'The header leaves usable viewport space');
    for (const [locator, name] of [
      [header.getByRole('link', { name: 'Notifications', exact: true }), 'Notifications'],
      [header.getByRole('button', { name: 'Sign out', exact: true }), 'Sign out'],
      [header.locator('.brand'), 'Brand'],
      [header.locator('.canopy-more > summary'), 'More services'],
    ]) {
      const control = await insideViewport(page, locator, role + ' ' + name + ' at ' + width);
      assert.ok(control.height >= 35, name + ' retains a usable touch target');
    }
    const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(dimensions.document <= dimensions.width + 1, role + ' document overflows at ' + width);
  }

  async function openMenu(page) {
    const details = page.locator('.canopy-more');
    if (!(await details.getAttribute('open'))) {
      // Boolean attributes use the empty string, so inspect the DOM boolean too.
      if (!(await details.evaluate(node => node.open))) await details.locator('summary').click();
    }
    await page.waitForFunction(() => document.querySelector('.canopy-more')?.open === true);
    const menu = page.locator('.canopy-more-menu'); await menu.waitFor({ state: 'visible' });
    return { details, menu, summary: details.locator('summary') };
  }

  async function checkMenu(page, role, width, screenshot = false) {
    const { details, menu, summary } = await openMenu(page);
    await insideViewport(page, menu, role + ' menu at ' + width);
    const last = menu.getByRole('link').last();
    await last.scrollIntoViewIfNeeded();
    await insideViewport(page, last, role + ' last menu link at ' + width);
    await last.focus(); await page.keyboard.press('Escape');
    assert.equal(await details.evaluate(node => node.open), false, 'Escape closes the menu');
    assert.equal(await summary.evaluate(node => document.activeElement === node), true, 'Escape restores focus to the launcher');
    await openMenu(page);
    const utility = await page.locator('.canopy-utility').boundingBox();
    assert.ok(utility && utility.y >= 0, 'Utility strip provides a non-navigating outside click');
    await page.mouse.click(utility.x + 3, utility.y + 3);
    assert.equal(await details.evaluate(node => node.open), false, 'Outside click closes the menu');
    await openMenu(page);
    await last.focus(); await page.keyboard.press('Tab');
    await page.waitForFunction(() => !document.querySelector('.canopy-more')?.open);
    const focused = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'));
    assert.equal(focused, 'Notifications', 'Tab leaves the menu without trapping focus');
    if (screenshot) {
      await openMenu(page);
      await page.screenshot({ path: path.join(qa, `header-${role}-${width}x${page.viewportSize().height}.png`) });
      await page.keyboard.press('Escape');
    }
  }

  async function menuNavigate(page, route, heading) {
    const { menu } = await openMenu(page);
    await menu.locator(`a[href="${route}"]`).click();
    await page.waitForURL(base + route);
    await page.getByRole('heading', { name: heading, exact: true }).waitFor();
    await page.waitForFunction(route => {
      const link = document.querySelector(`.main-nav a[href="${route}"]`);
      return link?.getAttribute('aria-current') === 'page' && link.classList.contains('active');
    }, route);
    assert.equal(await page.locator('.canopy-more').evaluate(node => node.open), false, 'Navigation closes More services');
    assert.equal(await page.locator('.canopy-shell-header [aria-current="page"]').count(), 1, 'Exactly one header link identifies the current page');
    await headerReady(page);
  }

  try {
    for (const role of ['citizen', 'admin', 'response_team']) {
      const page = await login(role);
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(() => window.scrollTo(0, 0));
        await assertHeader(page, role, width);
        await checkMenu(page, role, width, [320, 768, 1280, 1920].includes(width));
      }
      await page.setViewportSize({ width: 768, height: 360 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await assertHeader(page, role, 768);
      await checkMenu(page, role, 768, true);
      const { menu } = await openMenu(page);
      assert.equal(await menu.evaluate(node => node.scrollHeight > node.clientHeight), true, 'Short viewport menu scrolls instead of clipping links');
      await page.keyboard.press('Escape');
      await page.setViewportSize({ width: 390, height: 844 });
      await menuNavigate(page, '/alert-subscriptions', 'Follow alert areas');
      if (role === 'citizen') await menuNavigate(page, '/shelter-waitlist', 'My shelter waiting lists');
      if (role === 'admin') await menuNavigate(page, '/automation-settings', 'Automation settings');
      await page.locator('.canopy-shell-header').getByRole('link', { name: 'Notifications', exact: true }).click();
      await page.waitForURL(base + '/updates'); await page.getByRole('heading', { name: 'My updates', exact: true }).waitFor();
      await page.waitForFunction(() => document.querySelector('.header-notifications')?.getAttribute('aria-current') === 'page');
      assert.equal(await page.locator('.header-notifications').getAttribute('aria-current'), 'page');
      await page.getByRole('link', { name: 'Overview', exact: true }).click();
      await page.waitForURL(base + '/dashboard');
      await page.locator('[data-map-status]').filter({ hasText: 'Map checked' }).waitFor();
      await page.evaluate(() => window.scrollTo(0, 500));
      await headerReady(page);
      const sticky = await insideViewport(page, page.locator('.canopy-shell-header'), role + ' sticky header');
      assert.ok(Math.abs(sticky.y) <= 1, 'Header remains at the top after scrolling');
      await insideViewport(page, page.locator('.header-notifications'), 'Sticky notifications');
      await insideViewport(page, page.getByRole('button', { name: 'Sign out', exact: true }), 'Sticky sign out');
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.waitForURL(/\/login(?:\?|$)/); await page.getByRole('heading', { name: 'Welcome back.', exact: true }).waitFor();
    }
    assert.deepEqual(errors, []);
    console.log('Passed: all three roles, seven header widths, short viewport scrolling, keyboard/outside dismissal, exact HTMX active links, sticky controls, and isolated logout.');
  } finally {
    for (const page of pages) {
      if (!page.isClosed()) await page.evaluate(async () => {
        const token = sessionStorage.getItem('resq-week1-session');
        if (token) await fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
      }).catch(() => {});
    }
    await browser.close();
  }
}

main().catch(error => {
  let message = String(error?.stack || error);
  for (const secret of secrets) if (secret) message = message.split(secret).join('[redacted]');
  console.error(message); process.exitCode = 1;
});
