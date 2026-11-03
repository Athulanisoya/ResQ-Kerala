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
    const launcher = page.getByRole('button', { name: 'Open safety assistant', exact: true });
    const panel = page.locator('#assistant-widget-panel');
    const notifications = page.locator('[data-nav="updates"]');
    await notifications.waitFor({state:'visible'});
    assert.equal(await notifications.isVisible(), true);
    assert.equal(await notifications.evaluate(element => element.closest('details') === null), true);
    assert.equal(await page.locator('[data-nav="permissions"]').count(), 0);
    assert.equal(await page.locator('[data-nav="assistant"]').count(), 0);
    assert.equal(await panel.isVisible(), false);
    assert.equal(await launcher.getAttribute('aria-expanded'), 'false');

    let widgetLoads = 0;
    page.on('request', request => {
      if (request.method() === 'GET' && new URL(request.url()).pathname === '/assistant') widgetLoads += 1;
    });
    await launcher.click();
    await page.getByRole('heading', { name: 'How can I help you today?', exact: true }).waitFor();
    assert.equal(await launcher.getAttribute('aria-expanded'), 'true');
    const firstLoadCount = widgetLoads;
    const field = page.getByLabel('Message Safety Assistant', { exact: true });
    await page.getByRole('button', { name: /Track my report/ }).click();
    assert.equal(await field.inputValue(), 'What is the status of my report?');
    await field.press('Shift+Enter');
    assert.ok((await field.inputValue()).includes('\n'));
    assert.equal(await page.locator('.chat-message-user').count(), 0);

    const draft = 'Unsaved question that must survive navigation';
    await field.fill(draft);
    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();
    assert.equal(await panel.isVisible(), false);
    await page.getByRole('link', { name: 'Shelters', exact: true }).click();
    await page.getByRole('heading', { name: 'Shelters', exact: true }).waitFor();
    await launcher.click();
    assert.equal(await field.inputValue(), draft);
    assert.equal(widgetLoads, firstLoadCount, 'Opening an already loaded widget must preserve its draft');
    await field.press('Escape');
    assert.equal(await panel.isVisible(), false);
    assert.equal(await launcher.evaluate(element => document.activeElement === element), true);
    await page.getByRole('link', { name: 'Overview', exact: true }).click();
    await page.getByRole('link', { name: 'Ask the safety assistant', exact: true }).click();
    assert.equal(await field.inputValue(), draft, 'A general assistant shortcut restores the current draft');
    assert.equal(widgetLoads, firstLoadCount, 'A general assistant shortcut must not start a new conversation');

    const question = 'How do I submit a report?';
    await field.fill(question);
    const gate = new Promise(resolve => { release = resolve; });
    await page.route('**/ui/assistant/chat', async route => { await gate; await route.continue(); });
    await field.press('Enter');
    await page.getByText('Thinking…', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Send message', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();
    await page.getByRole('link', { name: 'Community', exact: true }).click();
    await page.getByRole('heading', { name: 'News and donations', exact: true }).waitFor();
    const underlyingPage = page.url();
    release();
    await launcher.click();
    await page.locator('.chat-message-user').getByText(question, { exact: true }).waitFor();
    await page.locator('.chat-message-assistant').first().waitFor();
    assert.equal(page.url(), underlyingPage, 'Chat responses must not navigate the underlying page');
    assert.equal(await field.inputValue(), '');
    const sessionId = await page.locator('[data-chat-form] input[name="session_id"]').inputValue();
    await page.unroute('**/ui/assistant/chat');

    await page.getByRole('link', { name: 'New chat', exact: true }).click();
    await page.getByRole('heading', { name: 'How can I help you today?', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Conversations', exact: true }).click();
    await page.locator(`.chat-history-item[href*="session_id=${sessionId}"]`).click();
    await page.locator('.chat-message-assistant').first().waitFor();
    assert.equal(page.url(), underlyingPage, 'History selection must remain in the widget');

    const qa = path.join(root, '.runtime', 'qa');
    fs.mkdirSync(qa, { recursive: true });
    for (const [width, height] of [[1440, 900], [800, 600], [390, 844], [320, 568]]) {
      await page.setViewportSize({ width, height });
      const layout = await panel.evaluate(element => {
        const box = element.getBoundingClientRect();
        const composer = element.querySelector('[data-chat-composer]').getBoundingClientRect();
        return { overflow: document.documentElement.scrollWidth > innerWidth,
                 panelInView: box.top >= 0 && box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight,
                 composerInView: composer.bottom <= innerHeight && composer.top >= 0 };
      });
      assert.equal(layout.overflow, false, `Horizontal overflow at ${width}x${height}`);
      assert.equal(layout.panelInView, true, `Panel offscreen at ${width}x${height}`);
      assert.equal(layout.composerInView, true, `Composer offscreen at ${width}x${height}`);
      if (width === 1440 || width === 320) await page.screenshot({ path: path.join(qa, `chat-widget-${width}.png`) });
      await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();
      const launchBox = await launcher.boundingBox();
      assert.ok(launchBox.width >= 44 && Math.abs(launchBox.width - launchBox.height) < 1, 'Launcher is a circular touch target');
      assert.ok(launchBox.x >= 0 && launchBox.y >= 0 && launchBox.x + launchBox.width <= width && launchBox.y + launchBox.height <= height);
      assert.equal(await notifications.isVisible(), true);
      await launcher.click();
    }

    // Network failure leaves the question available for a deliberate retry.
    await page.route('**/ui/assistant/chat', route => route.abort('failed'));
    const retryDraft = 'Keep this question after a network failure';
    await field.fill(retryDraft);
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[data-chat-form] button[type="submit"]').disabled);
    assert.equal(await field.inputValue(), retryDraft);
    await page.unroute('**/ui/assistant/chat');

    // A server error is not inserted as chat HTML, and retry resends the same question.
    await page.route('**/ui/assistant/chat', route => route.fulfill({status:500, contentType:'text/html', body:'Temporary server failure'}));
    const serverDraft = 'Keep this question after a server failure';
    await field.fill(serverDraft);
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.getByRole('button', { name: 'Try again', exact: true }).waitFor();
    assert.equal(await field.inputValue(), serverDraft);
    assert.equal(await panel.getByText('Temporary server failure', {exact:true}).count(), 0);
    const conversations = page.getByRole('button', {name:'Conversations', exact:true});
    if (await conversations.getAttribute('aria-expanded') !== 'true') await conversations.click();
    if (!await page.locator('.chat-guidance').evaluate(element=>element.open)) await page.locator('.chat-guidance summary').click();
    await page.screenshot({path:path.join(qa, 'chat-widget-expanded-error-320.png')});
    const expanded = await field.evaluate(element=>{
      const box=element.getBoundingClientRect();
      const dialog=element.closest('#assistant-widget-panel').getBoundingClientRect();
      const guidance=element.closest('.chat-main').querySelector('.chat-guidance').getBoundingClientRect();
      return{top:box.top,bottom:box.bottom,height:innerHeight,guidanceTop:guidance.top,guidanceBottom:guidance.bottom,guidanceHeight:guidance.height,panelTop:dialog.top,panelBottom:dialog.bottom};
    });
    assert.ok(expanded.top >= 0 && expanded.bottom <= expanded.height, 'Composer must stay in view with conversations, guidance and a retry notice expanded');
    assert.ok(expanded.guidanceTop >= expanded.panelTop && expanded.guidanceBottom <= expanded.panelBottom + 1 && expanded.guidanceHeight >= 45,
              `Expanded guidance must remain readable inside the panel: ${JSON.stringify(expanded)}`);
    await page.unroute('**/ui/assistant/chat');
    await page.getByRole('button', { name: 'Try again', exact: true }).click();
    await page.locator('.chat-message-user').getByText(serverDraft, {exact:true}).waitFor();
    assert.equal(await field.inputValue(), '');
    assert.equal(page.url(), underlyingPage);

    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();
    await page.goto(base + '/assistant?session_id=' + sessionId);
    await page.waitForURL(base + '/dashboard?chat=1&session_id=' + sessionId);
    await page.locator('.chat-message-assistant').first().waitFor();
    assert.equal(await panel.isVisible(), true, 'An old assistant deep link opens the floating widget');
    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.waitForURL(/\/login\?notice=signed-out$/);
    assert.equal(await page.locator('#assistant-widget').count(), 0, 'Signing out removes the private widget');
    assert.deepEqual(errors, []);
    console.log('PASS: header notifications, floating launcher, draft/history persistence, minimize during requests, unchanged workspace URL, network retry, deep links, logout privacy and desktop/mobile layout.');
  } finally {
    if (release) release();
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
