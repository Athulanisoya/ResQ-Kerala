const { setup } = require('./features_browser_helpers.cjs');
async function main() {
  const h = await setup(), a = h.assert; let circle;
  const owner = await h.citizen('Synthetic family owner'), member = await h.citizen('Synthetic family member');
  const p = await h.page(owner), q = await h.page(member);
  const form = (page, operation) => page.locator(`form:has(input[name=operation][value="${operation}"])`);
  try {
    await h.open(p, '/family-safety', 'Family safety');
    await form(p, 'create').getByLabel('New circle name').fill('Synthetic private household'); await h.submit(p, form(p, 'create'));
    circle = (await h.api(owner.access_token, '/api/family-safety/circles')).circles[0];
    await p.waitForURL(h.base + '/family-safety?circle_id=' + circle.id);
    await form(p, 'invite').getByLabel('Invite an existing account by email').fill(member.user.email); await h.submit(p, form(p, 'invite'));
    a.equal((await h.request(h.admin.access_token, '/api/family-safety/circles/' + circle.id)).status, 404);
    a.equal((await h.request(member.access_token, '/api/family-safety/circles/' + circle.id)).status, 404);
    await h.open(q, '/family-safety', 'Family safety'); await h.submit(q, form(q, 'accept'));
    await h.open(p, '/family-safety?circle_id=' + circle.id, 'Family safety');
    await form(p, 'checkin').getByLabel('My status', { exact: true }).selectOption('SAFE');
    await form(p, 'checkin').getByLabel('Location to share (optional)', { exact: true }).fill('Synthetic private meeting point');
    await form(p, 'checkin').locator('[name=consent]').check(); await h.submit(p, form(p, 'checkin'));
    await h.open(q, '/family-safety?circle_id=' + circle.id, 'Family safety');
    await q.getByText('Shared location: Synthetic private meeting point', { exact: true }).waitFor();
    for (const width of [1440, 320]) { await q.setViewportSize({ width, height: 1000 }); await h.screenshot(q, 'family-safety-' + width); }
    await h.submit(p, form(p, 'withdraw'));
    await h.open(q, '/family-safety?circle_id=' + circle.id, 'Family safety');
    a.equal((await q.locator('#main-content').innerText()).includes('Synthetic private meeting point'), false);
    await h.submit(q, form(q, 'leave'));
    a.equal((await h.request(member.access_token, '/api/family-safety/circles/' + circle.id)).status, 404);
    a.deepEqual(h.errors, []);
    console.log('Passed: private family circle creation, invitation acceptance, self check-in, withdrawal, leaving, administrator exclusion and 320/1440 layouts.');
  } finally {
    if (circle) await h.api(owner.access_token, '/api/family-safety/circles/' + circle.id + '/close', 'POST', { expected_version: 1 });
    await h.close();
  }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
