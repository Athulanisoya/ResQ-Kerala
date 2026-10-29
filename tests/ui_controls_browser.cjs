/* Run against the local demo app with Playwright available on NODE_PATH. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const root = path.resolve(__dirname, '..');
  const demo = JSON.parse(fs.readFileSync(path.join(root, '.runtime', 'demo-accounts.json'), 'utf8'));
  const base = process.env.RESQ_TEST_URL || 'http://127.0.0.1:8013';
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const context = await browser.newContext();
  context.setDefaultTimeout(15000);
  const errors = [];
  const pages = {};
  async function login(role) {
    const page = await context.newPage();
    pages[role] = page;
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.status() >= 500) errors.push(`${response.status()} ${response.url()}`);
    });
    const account = demo.accounts.find(item => item.role === role);
    await page.goto(base + '/login');
    await page.getByLabel('Email address').fill(account.email);
    await page.getByLabel('Password', { exact: true }).fill(demo.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    return page;
  }
  async function assertVisibleLogout(page, role) {
    await page.bringToFront();
    for (const [width, height] of [[1440, 900], [1280, 600], [800, 600], [390, 844], [320, 568]]) {
      await page.setViewportSize({ width, height });
      await page.reload();
      await page.getByRole('heading', { level: 1 }).waitFor();
      await page.waitForLoadState('networkidle');
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const button = page.getByRole('button', { name: 'Sign out', exact: true });
      assert.equal(await button.count(), 1);
      const position = await button.evaluate(element => {
        const box = element.getBoundingClientRect();
        const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
        return {
          inViewport: box.top >= 0 && box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight,
          clickable: hit === element || element.contains(hit),
          label: element.textContent.trim(),
          overflow: document.documentElement.scrollWidth > innerWidth,
        };
      });
      assert.equal(position.inViewport, true, `${role} logout outside ${width}x${height}`);
      assert.equal(position.clickable, true, `${role} logout obscured at ${width}x${height}`);
      assert.equal(position.label, 'Sign out');
      assert.equal(position.overflow, false, `${role} horizontal overflow at ${width}x${height}`);
    }
  }
  try {
    const admin = await login('admin');
    const citizen = await login('citizen');
    const team = await login('response_team');
    for (const [role, page] of Object.entries(pages)) await assertVisibleLogout(page, role);

    // General support is available before any campaign is created.
    await citizen.bringToFront();
    await citizen.setViewportSize({ width: 390, height: 844 });
    await citizen.getByRole('link', { name: 'Community', exact: true }).click();
    const general = citizen.locator('form[action="/ui/community/pledges"]');
    await general.getByRole('button', { name: 'Add donation pledge', exact: true }).waitFor();
    const generalName = `Synthetic general pledge ${Date.now()}`;
    await general.getByLabel('Support', { exact: true }).selectOption('');
    await general.getByLabel('Offer type', { exact: true }).selectOption('SUPPLIES');
    await general.getByLabel('What will you offer?', { exact: true }).fill(generalName);
    await general.getByLabel('Quantity or amount', { exact: true }).fill('2');
    await general.getByLabel('Unit', { exact: false }).fill('packets');
    await general.getByRole('button', { name: 'Add donation pledge', exact: true }).click();
    await citizen.getByText(generalName, { exact: true }).waitFor();

    await admin.bringToFront();
    await admin.setViewportSize({ width: 1440, height: 900 });
    await admin.getByRole('link', { name: 'Community', exact: true }).click();
    await admin.getByRole('heading', { name: 'News and donations', exact: true }).waitFor();
    await admin.locator('[data-nav="community"][aria-current="page"]').waitFor();
    const campaignName = `Synthetic UI control check ${Date.now()}`;
    const pledgeName = `Synthetic browser pledge for ${campaignName}`;
    const campaign = admin.locator('form[action="/ui/community/campaigns"]');
    assert.equal(await campaign.getByRole('button', { name: 'Create campaign', exact: true }).isVisible(), true);
    await campaign.getByLabel('Title', { exact: true }).fill(campaignName);
    await campaign.getByLabel('Description', { exact: true }).fill('Synthetic browser verification of visible pledge controls.');
    await campaign.getByRole('button', { name: 'Create campaign', exact: true }).click();
    await admin.getByRole('heading', { name: campaignName, exact: true }).waitFor();

    await citizen.bringToFront();
    await citizen.setViewportSize({ width: 390, height: 844 });
    await citizen.getByRole('link', { name: 'Community', exact: true }).click();
    const card = citizen.locator('article.operation-history-item').filter({
      has: citizen.getByRole('heading', { name: campaignName, exact: true }),
    });
    await card.getByRole('heading', { name: campaignName, exact: true }).waitFor();
    await citizen.locator('[data-nav="community"][aria-current="page"]').waitFor();
    const pledge = citizen.locator('form[action="/ui/community/pledges"]');
    assert.equal(await pledge.getByRole('button', { name: 'Add donation pledge', exact: true }).isVisible(), true);
    assert.equal(await pledge.evaluate(element => element.closest('details') === null), true);
    await pledge.getByLabel('Support', { exact: true }).selectOption({ label: campaignName });
    await pledge.getByLabel('Offer type', { exact: true }).selectOption('MONEY');
    await pledge.getByLabel('What will you offer?', { exact: true }).fill(pledgeName);
    await pledge.getByLabel('Quantity or amount', { exact: true }).fill('100');
    assert.equal(await pledge.getByLabel('Unit', { exact: false }).inputValue(), 'INR');
    await pledge.getByRole('button', { name: 'Add donation pledge', exact: true }).click();
    await citizen.getByText(pledgeName, { exact: true }).waitFor();
    assert.equal(await citizen.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);

    // Closing only the campaign created here leaves other demo campaigns intact.
    await admin.bringToFront();
    await admin.reload();
    const ownCampaign = admin.locator('article.operation-history-item').filter({
      has: admin.getByRole('heading', { name: campaignName, exact: true }),
    });
    await ownCampaign.getByRole('button', { name: 'Close campaign', exact: true }).click();
    await admin.getByRole('heading', { name: campaignName, exact: true }).waitFor();

    for (const [role, page] of Object.entries(pages)) {
      await page.bringToFront();
      const token = await page.evaluate(() => sessionStorage.getItem('resq-week1-session'));
      assert.ok(token, `${role} session should be present before logout`);
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.waitForURL(base + '/login?notice=signed-out');
      await page.getByText('You have signed out. Your server session has been revoked.', { exact: true }).waitFor();
      assert.equal(await page.evaluate(() => sessionStorage.getItem('resq-week1-session')), null, `${role} session not cleared`);
      if (token) {
        const response = await page.request.get(base + '/api/users/me', { headers: { Authorization: `Bearer ${token}` } });
        assert.equal(response.status(), 401, `${role} session was not revoked`);
      }
    }
    assert.deepEqual(errors, []);
    console.log('PASS: visible logout at five sizes; campaign and general relief pledge submission on mobile; logout revocation.');
  } finally {
    await context.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
