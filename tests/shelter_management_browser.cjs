/* Run after scripts/start.ps1 with Playwright available on NODE_PATH. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');

(async()=>{
 const root=path.resolve(__dirname,'..');
 const demo=JSON.parse(fs.readFileSync(path.join(root,'.runtime','demo-accounts.json'),'utf8'));
 const base=process.env.RESQ_TEST_URL||'http://127.0.0.1:8013';
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:900}}); context.setDefaultTimeout(15000);
 const errors=[];
 async function page(){const p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('response',r=>{if(r.status()>=500)errors.push(`${r.status()} ${r.url()}`)});return p}
 async function login(p,email,password){await p.goto(base+'/login');await p.getByLabel('Email address').fill(email);await p.getByLabel('Password',{exact:true}).fill(password);await p.getByRole('button',{name:'Sign in',exact:true}).click();await p.waitForURL(base+'/dashboard')}
 async function shelters(p){await p.bringToFront();await p.getByRole('link',{name:'Shelters',exact:true}).click();await p.getByRole('heading',{name:'Shelters',exact:true}).waitFor()}
 async function waitCounts(p,id,capacity,occupied,available){await p.bringToFront();await p.waitForFunction(({id,capacity,occupied,available})=>{const card=document.getElementById('shelter-'+id);return card&&card.querySelector('[data-capacity]')?.textContent.trim()===String(capacity)&&card.querySelector('[data-occupied]')?.textContent.trim()===String(occupied)&&card.querySelector('[data-available]')?.textContent.trim()===String(available)}, {id,capacity,occupied,available},{timeout:10000})}
 const stamp=Date.now();const teamName=`Synthetic shelter live team ${stamp}`;const shelterName=`Synthetic live shelter ${stamp}`;const email=`shelter.live.${stamp}@example.com`;const password=crypto.randomBytes(24).toString('base64url');
 try{
  const admin=await page();await login(admin,demo.accounts.find(a=>a.role==='admin').email,demo.password);
  await admin.getByRole('link',{name:'Administration',exact:true}).click();
  const createTeam=admin.locator('form[action="/ui/management/teams"]');
  await createTeam.getByLabel('Team name',{exact:true}).fill(teamName);await createTeam.getByLabel('Team type',{exact:true}).selectOption('Shelter');await createTeam.getByRole('button',{name:'Create team',exact:true}).click();
  const account=admin.locator('form[action="/ui/management/team-accounts"]');
  await account.getByLabel('Assigned team',{exact:true}).locator('option').filter({hasText:teamName}).waitFor({state:'attached'});
  await account.getByLabel('Team member name',{exact:true}).fill('Synthetic live shelter member');await account.getByLabel('Team member email',{exact:true}).fill(email);await account.getByLabel('Assigned team',{exact:true}).selectOption({label:`${teamName} (Shelter)`});await account.getByLabel('Password',{exact:true}).fill(password);await account.getByLabel('Confirm password',{exact:true}).fill(password);await account.getByRole('button',{name:'Create team account',exact:true}).click();
  await admin.getByText('Team account created. The team member can now sign in with the email and password you set.',{exact:true}).waitFor();
  const member=await page();await login(member,email,password);
  await shelters(admin);const create=admin.locator('form[action="/ui/shelters"]');
  await create.getByLabel('Shelter name',{exact:true}).fill(shelterName);await create.getByLabel('Location',{exact:true}).fill('Synthetic test hall, Kochi');await create.getByLabel('Shelter team',{exact:false}).selectOption({label:teamName});await create.getByLabel('Capacity',{exact:true}).fill('20');await create.getByLabel('Occupied',{exact:true}).fill('2');await create.getByRole('button',{name:'Add shelter',exact:true}).click();
  const adminCard=admin.locator('[data-shelter-id]').filter({has:admin.getByRole('heading',{name:shelterName,exact:true})});await adminCard.waitFor();const id=Number(await adminCard.getAttribute('data-shelter-id'));
  const viewer=await page();await login(viewer,demo.accounts.find(a=>a.role==='citizen').email,demo.password);await viewer.setViewportSize({width:390,height:844});await shelters(viewer);await waitCounts(viewer,id,20,2,18);
  await shelters(member);const memberCard=member.locator('#shelter-'+id);await memberCard.getByRole('button',{name:'Update capacity',exact:true}).click();const edit=member.locator('#shelter-editor form');await edit.getByLabel('Capacity',{exact:true}).fill('25');await edit.getByLabel('Occupied',{exact:true}).fill('9');await edit.getByLabel('Update note',{exact:true}).fill('Synthetic reception count');await edit.getByRole('button',{name:'Save capacity update',exact:true}).click();await member.getByText('Shelter capacity updated. Live availability is refreshing.',{exact:true}).waitFor();await waitCounts(viewer,id,25,9,16);
  // Polling must not overwrite drafts, and stale writes must not overwrite a newer update.
  await member.bringToFront();await edit.getByLabel('Occupied',{exact:true}).fill('8');await edit.getByLabel('Update note',{exact:true}).fill('Synthetic unsaved draft');
  await admin.bringToFront();await adminCard.getByRole('button',{name:'Update capacity',exact:true}).click();const adminEdit=admin.locator('#shelter-editor form');await adminEdit.getByLabel('Capacity',{exact:true}).fill('30');await adminEdit.getByLabel('Occupied',{exact:true}).fill('10');await adminEdit.getByLabel('Update note',{exact:true}).fill('Synthetic admin count');await adminEdit.getByRole('button',{name:'Save capacity update',exact:true}).click();await admin.getByText('Shelter capacity updated. Live availability is refreshing.',{exact:true}).waitFor();await waitCounts(viewer,id,30,10,20);
  await member.bringToFront();await waitCounts(member,id,30,10,20);assert.equal(await edit.getByLabel('Occupied',{exact:true}).inputValue(),'8');assert.equal(await edit.getByLabel('Update note',{exact:true}).inputValue(),'Synthetic unsaved draft');await edit.getByRole('button',{name:'Save capacity update',exact:true}).click();await member.getByRole('button',{name:'Reload latest values',exact:true}).waitFor();await member.getByRole('button',{name:'Reload latest values',exact:true}).click();await member.waitForFunction(()=>document.querySelector('#edit-capacity')?.value==='30');assert.equal(await edit.getByLabel('Occupied',{exact:true}).inputValue(),'10');
  await edit.getByLabel('Status',{exact:true}).selectOption('CLOSED');await edit.getByLabel('Update note',{exact:true}).fill('Synthetic browser check completed');await edit.getByRole('button',{name:'Save capacity update',exact:true}).click();await member.getByText('Shelter capacity updated. Live availability is refreshing.',{exact:true}).waitFor();await viewer.bringToFront();await viewer.locator('#shelter-'+id).getByText('Closed',{exact:true}).waitFor();assert.equal(await viewer.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  // Retire only the synthetic login created in this run.
  const token=await admin.evaluate(()=>sessionStorage.getItem('resq-week1-session'));const headers={Authorization:`Bearer ${token}`};const accounts=await admin.request.get(base+'/api/management/users',{headers});const user=(await accounts.json()).find(a=>a.email===email);assert.ok(user);const retired=await admin.request.patch(base+`/api/management/users/${user.id}`,{headers,data:{role:'response_team',team_id:user.team_id,active:false}});assert.equal(retired.status(),200);
  assert.deepEqual(errors,[]);console.log('PASS: admin created a Shelter team and login, member signed in, admin added shelter, citizen saw live changes without reload, drafts survived refresh and stale edits were rejected.');
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack||e.message);process.exitCode=1});
