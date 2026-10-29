/* Run with the local app/demo accounts and Playwright available on NODE_PATH. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const root = path.resolve(__dirname, '..');
  const demo = JSON.parse(fs.readFileSync(path.join(root, '.runtime', 'demo-accounts.json'), 'utf8'));
  const base = process.env.RESQ_TEST_URL || 'http://127.0.0.1:8013';
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let release;
  try {
    await page.goto(base + '/login');
    await page.getByLabel('Email address').fill(demo.accounts.find(item => item.role === 'citizen').email);
    await page.getByLabel('Password', { exact: true }).fill(demo.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    await page.getByRole('link', { name: 'Safety assistant', exact: true }).click();
    await page.getByRole('heading', { name: 'How can I help you today?', exact: true }).waitFor();
    const field = page.getByLabel('Message Safety Assistant', { exact: true });
    await page.getByRole('button', { name: /Track my report/ }).click();
    assert.equal(await field.inputValue(), 'What is the status of my report?');
    await field.press('Shift+Enter');
    assert.ok((await field.inputValue()).includes('\n'));
    assert.equal(await page.locator('.chat-message-user').count(), 0);
    const question = 'How do I submit a report?';
    await field.fill(question);
    const gate = new Promise(resolve => { release = resolve; });
    await page.route('**/ui/assistant/chat', async route => { await gate; await route.continue(); });
    await field.press('Enter');
    await page.getByText('Thinking…', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Send message', exact: true }).isDisabled(), true);
    release();
    await page.waitForURL(/\/assistant\?session_id=\d+$/);
    const saved = page.url();
    await page.locator('.chat-message-user').getByText(question, { exact: true }).waitFor();
    await page.locator('.chat-message-assistant').waitFor();
    assert.equal(await field.inputValue(), '');
    await page.unroute('**/ui/assistant/chat');
    await page.getByRole('link', { name: 'New chat', exact: true }).click();
    await page.getByRole('heading', { name: 'How can I help you today?', exact: true }).waitFor();
    await page.locator(`.chat-history-item[href="${new URL(saved).pathname + new URL(saved).search}"]`).click();
    await page.locator('.chat-message-assistant').waitFor();
    for (const [width, height] of [[1440, 900], [800, 600], [390, 844], [320, 568]]) {
      await page.setViewportSize({ width, height });
      await page.reload();
      await page.locator('.chat-message-assistant').waitFor();
      await page.waitForLoadState('networkidle');
      const layout = await page.locator('[data-chat-composer]').evaluate(element => {
        const box = element.getBoundingClientRect();
        return { overflow: document.documentElement.scrollWidth > innerWidth,
                 composerInView: box.bottom <= innerHeight && box.top >= 0 };
      });
      assert.equal(layout.overflow, false, `Horizontal overflow at ${width}x${height}`);
      assert.equal(layout.composerInView, true, `Composer offscreen at ${width}x${height}`);
    }
    assert.deepEqual(errors, []);
    console.log('PASS: chat prompts, multiline composition, Enter send, pending state, private history reopen and desktop/mobile layout.');
  } finally {
    if (release) release();
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
