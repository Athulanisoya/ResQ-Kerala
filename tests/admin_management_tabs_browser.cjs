/* Run against the local app/demo accounts with Playwright on NODE_PATH. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sections = {
  'create-team': 'Create a team',
  accounts: 'Account management',
  teams: 'Response teams',
  reports: 'Aggregate reports',
};
const display = value => value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());

async function main() {
  const root = path.resolve(__dirname, '..');
  const demo = JSON.parse(fs.readFileSync(path.join(root, '.runtime', 'demo-accounts.json'), 'utf8'));
  const base = process.env.RESQ_TEST_URL || 'http://127.0.0.1:8013';
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 500) errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  try {
    await page.goto(base + '/login');
    await page.getByLabel('Email address').fill(demo.accounts.find(account => account.role === 'admin').email);
    await page.getByLabel('Password', { exact: true }).fill(demo.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(base + '/dashboard');
    await page.locator('[data-nav="updates"]').waitFor({ state: 'visible' });
    await page.locator('.canopy-more summary').click();
    await page.getByRole('link', { name: 'Administration', exact: true }).click();
    await page.locator('[data-management-tab="create-team"]').waitFor();

    const nav = () => page.getByRole('navigation', { name: 'Administration sections', exact: true });
    const timeOrigin = await page.evaluate(() => performance.timeOrigin);
    async function select(section) {
      const request = page.waitForRequest(request => request.method() === 'GET' && request.url() === base + '/management?tab=' + section);
      await nav().getByRole('link', { name: sections[section], exact: true }).click();
      assert.equal((await request).headers()['hx-request'], 'true', 'Section navigation must use HTMX');
      await page.locator(`[data-management-tab="${section}"]`).waitFor();
      await page.waitForURL(base + '/management?tab=' + section);
      assert.equal(await nav().locator('[aria-current="page"]').innerText(), sections[section]);
      assert.equal(await page.evaluate(() => performance.timeOrigin), timeOrigin, 'Section navigation must preserve the document');
    }
    assert.equal(await nav().getByRole('link').count(), 4);
    assert.equal(await page.locator('#management-panel form').count(), 2);

    // A draft in the floating assistant survives all administration section swaps.
    const launcher = page.getByRole('button', { name: 'Open safety assistant', exact: true });
    await launcher.click();
    const composer = page.getByLabel('Message Safety Assistant', { exact: true });
    await composer.fill('Synthetic unsent administration question');
    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();

    const teamName = `Synthetic administration UI team ${Date.now()}`;
    const createForm = () => page.locator('form[action="/ui/management/teams"]');
    await createForm().getByLabel('Team name', { exact: true }).fill(teamName);
    await createForm().getByLabel('Team type', { exact: true }).selectOption('Investigation');
    await createForm().getByRole('button', { name: 'Create team', exact: true }).click();
    await page.getByText('Response team created. You can now add a team member account.', { exact: true }).waitFor();
    await page.waitForURL(base + '/management?tab=create-team');
    await page.getByLabel('Assigned team', { exact: true }).locator('option').filter({ hasText: teamName }).waitFor({ state: 'attached' });
    // Duplicate validation returns to the same section and keeps the non-secret draft.
    await createForm().getByLabel('Team name', { exact: true }).fill(teamName);
    await createForm().getByLabel('Team type', { exact: true }).selectOption('Investigation');
    await createForm().getByRole('button', { name: 'Create team', exact: true }).click();
    await page.getByText('A team with this name already exists', { exact: true }).waitFor();
    assert.equal(await createForm().getByLabel('Team name', { exact: true }).inputValue(), teamName);
    assert.equal(await createForm().getByLabel('Team type', { exact: true }).inputValue(), 'Investigation');

    await select('accounts');
    const firstAccount = page.locator('#management-panel details.management-record').first();
    await firstAccount.locator('summary').click();
    assert.equal(await firstAccount.getByLabel('Role', { exact: true }).isVisible(), true);
    assert.equal(await firstAccount.getByLabel('Account status', { exact: true }).isVisible(), true);
    assert.equal(await page.locator('form[action="/ui/management/team-accounts"]').count(), 0);
    // Existing account forms are inspected only; no live account is submitted or changed.

    await select('teams');
    let synthetic = page.locator('details.management-record').filter({ hasText: teamName });
    await synthetic.locator('summary').click();
    const updatedName = teamName + ' checked';
    await synthetic.getByLabel('Name', { exact: true }).fill(updatedName);
    await synthetic.getByLabel('Availability', { exact: true }).selectOption('OFFLINE');
    await synthetic.getByRole('button', { name: 'Save team', exact: true }).click();
    await page.getByText('Response team updated.', { exact: true }).waitFor();
    await page.waitForURL(base + '/management?tab=teams');
    synthetic = page.locator('details.management-record').filter({ hasText: updatedName });
    await synthetic.locator('summary').click();
    assert.equal(await synthetic.getByLabel('Availability', { exact: true }).inputValue(), 'OFFLINE');

    await select('reports');
    assert.equal(await page.locator('#management-panel form').count(), 0);
    // Compare displayed totals with the same live ledgers used by the administration API.
    const report = await page.evaluate(async () => {
      const response = await fetch('/api/management/reports', {
        headers: { Authorization: 'Bearer ' + sessionStorage.getItem('resq-week1-session') },
      });
      if (!response.ok) throw new Error('Aggregate API could not be read');
      return response.json();
    });
    for (const [field, id] of [['incidents_by_status', 'aggregate-incidents'], ['operations_relief_by_status', 'aggregate-relief'], ['teams_by_status', 'aggregate-teams'], ['campaigns_by_status', 'aggregate-campaigns']]) {
      const card = page.locator(`section[aria-labelledby="${id}"]`);
      for (const [status, count] of Object.entries(report[field])) {
        const row = card.getByRole('row').filter({ has: page.getByRole('rowheader', { name: display(status), exact: true }) });
        assert.equal((await row.getByRole('cell').innerText()).trim(), String(count));
      }
    }
    const donationRows = await page.locator('.management-donation-table tbody tr').evaluateAll(rows => rows.map(row => [...row.children].map(cell => cell.textContent.trim())));
    assert.equal(donationRows.length, report.donations.length);
    for (const donation of report.donations) {
      const row = donationRows.find(cells => cells[0] === display(donation.kind) && cells[1] === display(donation.status) && cells[3] === donation.unit);
      assert.ok(row, 'Each donation kind, status and unit must retain its own row');
      assert.equal(Number(row[2]), Number(donation.quantity));
      assert.equal(Number(row[4]), donation.count);
    }
    const shelter = page.locator('section[aria-labelledby="aggregate-shelters"]');
    assert.deepEqual(await shelter.locator('dd').allTextContents(), [report.shelters.count, report.shelters.occupied, report.shelters.capacity].map(String));
    await launcher.click();
    assert.equal(await composer.inputValue(), 'Synthetic unsent administration question');
    await page.getByRole('button', { name: 'Minimize chat', exact: true }).click();

    const qa = path.join(root, '.runtime', 'qa');
    fs.mkdirSync(qa, { recursive: true });
    for (const width of [1440, 320]) {
      await page.setViewportSize({ width, height: width === 320 ? 740 : 900 });
      for (const section of Object.keys(sections)) {
        await select(section);
        if (section === 'accounts') await page.locator('#management-panel details.management-record').first().locator('summary').click();
        if (section === 'teams') await page.locator('details.management-record').filter({ hasText: updatedName }).locator('summary').click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${sections[section]} overflows at ${width}px`);
        const buttons = await nav().getByRole('link').evaluateAll(links => links.map(link => {
          const rect = link.getBoundingClientRect();
          return rect.width >= 44 && rect.height >= 44 && rect.left >= 0 && rect.right <= innerWidth;
        }));
        assert.ok(buttons.every(Boolean), `Section links must remain usable at ${width}px`);
        await page.screenshot({ path: path.join(qa, `administration-${section}-${width}.png`), fullPage: true });
      }
    }
    // A direct URL can be reloaded and restore the selected section after bootstrap.
    await page.goto(base + '/management?tab=accounts');
    await page.locator('[data-management-tab="accounts"]').waitFor();
    assert.equal(await nav().locator('[aria-current="page"]').innerText(), 'Account management');
    assert.deepEqual(errors, []);
    console.log('PASS: four HTMX administration sections, synthetic team create/edit and retained validation, read-only account inspection, live report totals and separate units, assistant draft persistence, direct links and 1440/320px layouts.');
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
