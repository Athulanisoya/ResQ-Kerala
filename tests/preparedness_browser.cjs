const { setup } = require('./features_browser_helpers.cjs');
async function main() {
  const h = await setup(), a = h.assert;
  const citizen = await h.citizen('Synthetic preparedness household');
  const p = await h.page(citizen), admin = await h.page(h.admin);
  try {
    await h.open(p, '/preparedness', 'Household preparedness');
    const form = p.locator('form.preparedness-form');
    await form.locator('input[name="done:meeting_points"]').check();
    await form.locator('input[name="done:supplies"]').check();
    await form.getByLabel('Nearby meeting point', { exact: true }).fill('Synthetic private nearby point');
    await form.getByLabel('Meeting point outside your area', { exact: true }).fill('Synthetic private outside point');
    await form.getByLabel('Contact 1 name', { exact: true }).fill('Synthetic household contact');
    await form.getByLabel('Contact 1 phone', { exact: true }).fill('0000000000');
    await form.getByLabel('Contact 1 relationship', { exact: true }).fill('Synthetic relative');
    await form.getByLabel('Evacuation assistance plan', { exact: true }).fill('Synthetic private assistance details');
    await form.getByLabel('Next household review date', { exact: true }).fill('2026-11-01');
    await form.locator('[name=reviewed]').check(); await h.submit(p, form);
    const saved = await h.api(citizen.access_token, '/api/preparedness/me');
    a.equal(saved.version, 1); a.equal(saved.completed.length, 2); a.ok(saved.reviewed_at); a.ok(saved.review_due);
    await p.getByRole('button', { name: 'Print saved plan', exact: true }).waitFor();
    await h.open(p, '/preparedness?lang=ml', 'Household preparedness');
    await p.getByRole('heading', { name: 'വീട്ടിലെ തയ്യാറെടുപ്പ് പട്ടിക', exact: true }).waitFor();
    a.equal(await p.locator('input[name="done:meeting_points"]').isChecked(), true);
    a.equal(await form.getByLabel('Nearby meeting point', { exact: true }).inputValue(), saved.nearby_meeting);
    for (const width of [1440, 320]) { await p.setViewportSize({ width, height: 1000 }); await h.screenshot(p, 'preparedness-ml-' + width); }
    await p.setViewportSize({ width: 1440, height: 1000 });
    await p.screenshot({ path: '.runtime/qa/preparedness-preview.png', fullPage: false });
    await p.setViewportSize({ width: 1000, height: 1300 });
    await p.locator('#nearby-meeting').fill('UNSAVED value must not print');
    const styleBeforePrint = await p.evaluate(() => ({ css: document.body.style.cssText, background: getComputedStyle(document.body).backgroundColor }));
    await p.evaluate(() => { window.__printCalls = 0; window.print = () => { window.__printCalls++; }; });
    await p.getByRole('button', { name: 'Print saved plan', exact: true }).click(); a.equal(await p.evaluate(() => window.__printCalls), 1);
    await p.emulateMedia({ media: 'print' });
    a.equal(await p.locator('.preparedness-workspace').isVisible(), false);
    a.equal(await p.locator('.preparedness-print-only').isVisible(), true);
    await p.waitForFunction(() => getComputedStyle(document.documentElement).backgroundColor === 'rgb(255, 255, 255)' && getComputedStyle(document.body).backgroundColor === 'rgb(255, 255, 255)');
    const printed = await p.locator('.preparedness-print-only').innerText();
    a.ok(printed.includes(saved.nearby_meeting)); a.ok(!printed.includes('UNSAVED value')); a.ok(printed.includes('0000000000'));
    await h.screenshot(p, 'preparedness-print');
    await p.evaluate(() => window.dispatchEvent(new Event('afterprint')));
    await p.emulateMedia({ media: 'screen' });
    await p.waitForFunction(expected => document.body.style.cssText === expected.css && getComputedStyle(document.body).backgroundColor === expected.background, styleBeforePrint);
    a.equal(await p.locator('.preparedness-workspace').isVisible(), true);
    await h.open(admin, '/preparedness', 'Household preparedness');
    a.equal((await admin.locator('#main-content').innerText()).includes(saved.nearby_meeting), false);
    a.equal((await h.api(h.admin.access_token, '/api/preparedness/me')).version, 0);
    a.deepEqual(h.errors, []);
    console.log('Passed: private saved checklist and contacts, English/Malayalam switch, review state, saved-only print layout, administrator isolation and 320/1440 layouts.');
  } finally { await h.close(); }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
