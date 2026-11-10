/* Run with the local app/demo accounts and Playwright available on NODE_PATH. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setup } = require('./features_browser_helpers.cjs');

async function main() {
  const root = path.resolve(__dirname, '..');
  process.env.BASE_URL ||= process.env.RESQ_TEST_URL || 'http://127.0.0.1:8013';
  process.env.RESQ_DEMO_ACCOUNTS ||= path.join(root, '.runtime',
    new URL(process.env.BASE_URL).port === '8014' ? 'docker-demo-accounts.json' : 'demo-accounts.json');
  const app = await setup();
  const { base, errors } = app;
  let release;
  try {
    const page = await app.page(await app.citizen('Synthetic assistant browser test'));
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
    await page.locator('.chat-message-user').getByText(question, { exact: true }).waitFor();
    assert.equal(await field.evaluate(element => element.readOnly), true);
    assert.equal(await page.locator('.chat-message-assistant').count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Send message', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();
    await page.getByRole('link', { name: 'Community', exact: true }).click();
    await page.getByRole('heading', { name: 'News and donations', exact: true }).waitFor();
    const underlyingPage = page.url();
    release();
    await launcher.click();
    await page.locator('.chat-message-user').getByText(question, { exact: true }).waitFor();
    await page.locator('.chat-message-assistant').first().waitFor();
    assert.equal(await page.locator('.chat-message-user').count(), 1);
    assert.equal(await field.evaluate(element => element.readOnly), false);
    assert.equal(page.url(), underlyingPage, 'Chat responses must not navigate the underlying page');
    assert.equal(await field.inputValue(), '');
    const sessionId = await page.locator('[data-chat-form] input[name="session_id"]').inputValue();
    await page.unroute('**/ui/assistant/chat');

    async function send(message, expectedReplies) {
      await field.fill(message);
      await field.press('Enter');
      await page.locator('.chat-message-assistant').nth(expectedReplies - 1).waitFor();
      assert.equal(await page.locator('.chat-message-user').count(), expectedReplies);
      return page.locator('.chat-message-assistant').last();
    }
    const greeting = await send('Hi', 2);
    assert.match(await greeting.locator('.chat-message-content').innerText(), /shelter/i);
    assert.equal(await greeting.locator('.chat-evidence, .chat-message-notice').count(), 0);
    const shelterQuestion = await send('Can you find an available shelter?', 3);
    assert.match(await shelterQuestion.locator('.chat-message-content').innerText(), /district|locality/i);
    const locationReply = await send('Ernakulam', 4);
    await locationReply.locator('summary', { hasText: 'Sources and evidence' }).click();
    assert.match(await locationReply.locator('.chat-evidence').innerText(), /Shelter records/);
    const preparation = await send('How can I prepare for flooding?', 5);
    assert.match(await preparation.locator('.chat-message-content').innerText(), /Pack an emergency kit/i);
    assert.equal(await preparation.locator('.chat-evidence').isVisible(), false);
    const timing = await send('when should I seek emergency shelter?', 6);
    const timingText = await timing.locator('.chat-message-content').innerText();
    assert.match(timingText, /When local officials tell you to evacuate/i);
    assert.doesNotMatch(timingText, /Emergency contacts|Shelter evidence is missing|Excerpt from|https:\/\//i);
    assert.equal(await timing.locator('.chat-evidence').isVisible(), false);
    await timing.locator('summary', { hasText: 'Sources and evidence' }).click();
    assert.match(await timing.innerText(), /KSDMA Flood Evacuation and Relief Camps/);
    assert.match(await timing.locator('.chat-evidence').innerText(), /Safety reference passages/);
    assert.doesNotMatch(await timing.locator('.chat-evidence').innerText(), /Shelter records|Emergency-contact directory/);
    assert.equal(await page.locator('[data-chat-form] input[name="session_id"]').inputValue(), sessionId);
    await page.reload();
    await launcher.click();
    await page.locator('.chat-message-assistant').nth(5).waitFor();
    assert.equal(await page.locator('[data-chat-form] input[name="session_id"]').inputValue(), sessionId);
    assert.equal(page.url(), underlyingPage);

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
      // Chromium can update the viewport before recalculating vw and dvh sizes.
      await page.waitForFunction(({ width, height }) => {
        const box = document.getElementById('assistant-widget-panel')?.getBoundingClientRect();
        return innerWidth === width && innerHeight === height && box?.width > 0
          && box.left >= 0 && box.top >= 0 && box.right <= width && box.bottom <= height;
      }, { width, height }, { timeout: 3000 });
      const layout = await panel.evaluate(element => {
        const box = element.getBoundingClientRect();
        const composer = element.querySelector('[data-chat-composer]').getBoundingClientRect();
        return { panel: box.toJSON(), overflow: document.documentElement.scrollWidth > innerWidth,
                 panelInView: box.top >= 0 && box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight,
                 composerInView: composer.bottom <= innerHeight && composer.top >= 0 };
      });
      assert.equal(layout.overflow, false, `Horizontal overflow at ${width}x${height}`);
      assert.equal(layout.panelInView, true, `Panel offscreen at ${width}x${height}: ${JSON.stringify(layout.panel)}`);
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
    await page.waitForFunction(() => document.querySelector('[data-chat-composer]')?.value === '');
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
    console.log('PASS: immediate messages, contextual follow-ups, concise flood preparation and evacuation guidance, expandable evidence, saved chat resume, retries, privacy and responsive layout.');
  } finally {
    if (release) release();
    await app.close();
  }
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
