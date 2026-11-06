const { setup } = require('./features_browser_helpers.cjs');
async function main() {
  const h = await setup(), a = h.assert; let shelter;
  const citizen = await h.citizen('Synthetic facilities visitor');
  const admin = await h.page(h.admin), p = await h.page(citizen);
  try {
    shelter = await h.api(h.admin.access_token, '/api/shelters', 'POST', {
      name: 'Synthetic accessible shelter ' + Date.now(), location: 'Synthetic Aluva fixture, not real accommodation',
      capacity: 10, occupied: 0, contact: 'Synthetic reception only' });
    await h.open(admin, '/shelters', 'Shelters');
    await admin.locator(`[data-shelter-id="${shelter.id}"]`).getByRole('button', { name: 'Update facility details', exact: true }).click();
    const form = admin.locator(`form[action="/ui/shelters/${shelter.id}/facilities"]`); await form.waitFor();
    await form.getByLabel('Wheelchair access', { exact: true }).selectOption('YES');
    await form.getByLabel('Charging facilities', { exact: true }).selectOption('YES');
    await form.getByLabel('Pets allowed', { exact: true }).selectOption('NO');
    await form.getByLabel('Facility confirmation note').fill('Synthetic staff inspection for browser testing');
    await form.locator('[name=confirmed]').check(); await h.submit(admin, form);
    const saved = await h.api(citizen.access_token, '/api/shelters/' + shelter.id);
    a.equal(saved.facility_details.wheelchair_access, 'YES'); a.equal(saved.facility_freshness, 'current');
    a.equal(saved.capacity_confirmed_at, shelter.capacity_confirmed_at);
    await h.open(p, '/shelters?facility=wheelchair_access&facility=charging', 'Shelters');
    a.equal(await p.locator('[data-shelter-id]').count(), 1);
    a.equal(await p.locator('[data-shelter-id]').getAttribute('data-shelter-id'), String(shelter.id));
    const poll = p.waitForResponse(r => new URL(r.url()).pathname === '/ui/shelters/live' && r.url().includes('facility=charging'));
    await poll; a.equal(await p.locator('[data-shelter-id]').count(), 1);
    await p.locator('input[name=facility][value=accessible_toilets]').check();
    await p.locator('.shelter-search-form').getByRole('button', { name: 'Search', exact: true }).click();
    await p.getByRole('heading', { name: 'No matching shelter records', exact: true }).waitFor();
    for (const width of [1440, 320]) {
      await p.setViewportSize({ width, height: 1000 });
      await h.open(p, '/shelters?facility=wheelchair_access&facility=charging', 'Shelters');
      await h.screenshot(p, 'shelter-facilities-' + width);
    }
    a.deepEqual(h.errors, []);
    console.log('Passed: staff facility confirmation, independent capacity timestamp, AND filters, unknown exclusion, polling retention and 320/1440 layouts.');
  } finally {
    if (shelter) { const row = await h.api(h.admin.access_token, '/api/shelters/' + shelter.id);
      await h.api(h.admin.access_token, '/api/shelters/' + shelter.id, 'PATCH', { capacity: row.capacity, occupied: 0, expected_version: row.version, status: 'CLOSED', note: 'Synthetic facility browser cleanup' }); }
    await h.close();
  }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
