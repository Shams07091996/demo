// End-to-end smoke test: loads the real page in jsdom, logs in over HTTP and clicks through the app.
//
//   python manage.py seed_demo --password "some-long-password"
//   python manage.py runserver 8765          (in another terminal)
//   UI_TEST_PASSWORD="some-long-password" node ui_smoke_test.js [alex|admin|viewer]
//
// It creates and removes its own vessels, master-data values and a January-2020 exchange rate.
const path = require('path');
const { buildSync } = require('esbuild');
const { JSDOM } = require('jsdom');

const BASE = process.env.UI_TEST_URL || 'http://localhost:8765';
const PASSWORD = process.env.UI_TEST_PASSWORD;
const ROLE = process.argv[2] || 'alex';
if (!PASSWORD) { console.error('Set UI_TEST_PASSWORD to the password given to seed_demo.'); process.exit(2); }

const bundle = buildSync({
  entryPoints: [path.join(__dirname, '../sheet/static/sheet/js/main.js')],
  bundle: true, write: false, format: 'iife', logLevel: 'error',
}).outputFiles[0].text;

const jar = {};
const remember = (res) => (res.headers.getSetCookie?.() || []).forEach((c) => { const [k, v] = c.split(';')[0].split('='); jar[k] = v; });
const cookies = () => Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; ');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let failures = 0;
const ok = (condition, label) => { console.log(`${condition ? 'PASS' : 'FAIL'} ${label}`); if (!condition) failures += 1; };

async function login() {
  let res = await fetch(`${BASE}/login/`); remember(res);
  res = await fetch(`${BASE}/login/`, {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Cookie: cookies(), Referer: `${BASE}/login/` },
    body: new URLSearchParams({ username: ROLE, password: PASSWORD, csrfmiddlewaretoken: jar.csrftoken }),
  });
  remember(res);
  if (res.status !== 302) throw new Error(`Login failed (HTTP ${res.status}) - wrong UI_TEST_PASSWORD?`);
  res = await fetch(`${BASE}/`, { headers: { Cookie: cookies() } });
  remember(res);
  return res.text();
}

(async () => {
  const html = (await login()).replace(/<script type="module"[^>]*><\/script>/, '');
  const dom = new JSDOM(html, { url: `${BASE}/`, runScripts: 'dangerously', pretendToBeVisual: true });
  const w = dom.window;
  let listCalls = 0;          // how many vessel-list requests the page made
  let slowAlertsFor = null;   // a query fragment whose alerts response is held back (to test late answers)
  let holdBulkCheck = null;   // a promise the bulk duplicate check waits for (to deliver its answer late)
  let failBulkCheck = false;  // make the bulk duplicate check fail
  let bulkCreates = 0;        // how many bulk-create requests the page sent
  let stayPosts = 0;          // how many "create hotel stay" requests the page sent
  let holdStay = null;        // {id, until}: hold back the answer for opening that stay
  w.fetch = async (url, opts = {}) => {
    if (url.startsWith('/api/vessels/?')) listCalls += 1;
    if (url === '/api/vessels/bulk/') bulkCreates += 1;
    if (url === '/api/hotels/' && opts.method === 'POST') stayPosts += 1;
    if (holdStay && url === `/api/hotels/${holdStay.id}/` && (opts.method || 'GET') === 'GET') await holdStay.until;
    if (slowAlertsFor && url.startsWith('/api/vessels/alerts/') && url.includes(slowAlertsFor)) await sleep(600);
    if (url === '/api/vessels/bulk/check/') {
      if (failBulkCheck) return new Response(JSON.stringify({ error: 'Server unavailable.' }), { status: 503 });
      if (holdBulkCheck) await holdBulkCheck;
    }
    return fetch(BASE + url, { ...opts, headers: { ...(opts.headers || {}), Cookie: cookies() } });
  };
  w.confirm = () => true;
  w.alert = (m) => console.log('  (alert) ' + m);
  w.HTMLElement.prototype.scrollIntoView = () => {};
  const jsErrors = [];
  w.addEventListener('error', (e) => jsErrors.push(e.message));

  const $ = (s) => w.document.querySelector(s);
  const $$ = (s) => [...w.document.querySelectorAll(s)];
  const click = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  const type = (el, value) => { el.value = value; el.dispatchEvent(new w.Event('input', { bubbles: true })); el.dispatchEvent(new w.Event('change', { bubbles: true })); };
  const waitFor = async (cond, ms = 4000) => { const end = Date.now() + ms; while (Date.now() < end) { if (cond()) return true; await sleep(40); } return false; };
  const modalText = () => $('#modal').textContent;
  const rowFor = (name) => $$('#tbody tr').find((t) => t.textContent.includes(name));
  const go = async (page) => { w.location.hash = page; return waitFor(() => !$(`#page-${page}`).hidden && $('#pageTitle').textContent.length > 0); };
  const openRow = async (name) => { click(rowFor(name).querySelector('td')); await waitFor(() => $('#modal h2')?.textContent.includes(name)); };
  const closeModal = () => click($('#modal [data-act="close"]'));
  const localNow = () => { const d = new w.Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const meta = () => $('meta[name="csrf-token"]').content;
  const clearTestRate = async () => {
    const { rates } = await (await w.fetch('/api/rates/')).json();
    for (const r of rates.filter((x) => x.month === '2020-01')) await w.fetch(`/api/rates/${r.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
  };
  if (ROLE === 'admin') await clearTestRate();

  // A vessel whose texts look like markup: every screen must show them literally (editors only; viewers can't add).
  const HOSTILE = 'SMOKE <i>X</i> & "Q"';
  const HOSTILE_AGENT = '<b>A</b> &amp;';
  // The page's own <b> labels are fine; an <i>/<b> holding the hostile inner texts (or any <img>) is not.
  const noMarkup = (root) => !!root && !root.querySelector('img')
    && ![...root.querySelectorAll('i, b')].some((e) => ['X', 'A', 'O', 'R', 'G', 'M', 'B'].includes(e.textContent.trim()));
  let hostileId = null;
  if (ROLE === 'alex' || ROLE === 'admin') {
    const res = await w.fetch('/api/vessels/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
      body: JSON.stringify({ name: HOSTILE, agent: HOSTILE_AGENT, opr: '<i>O</i>', port: 'alexandria', date: localNow() }),
    });
    hostileId = (await res.json()).id;
    ok(res.status === 201 || res.status === 200, `hostile-text vessel created (HTTP ${res.status})`);
  }

  // Run the app the way a page does: as a <script> element (no eval).
  const appScript = w.document.createElement('script');
  appScript.textContent = bundle;
  w.document.body.appendChild(appScript);
  await waitFor(() => $$('#tbody tr').length > 0);
  console.log(`role: ${ROLE} | vessels: ${$$('#tbody tr').map((t) => t.querySelector('.vessel-name').textContent).join(', ')}`);
  if (hostileId) {
    const row = () => $(`#tbody tr[data-id="${hostileId}"]`);
    ok(await waitFor(() => row()), 'hostile vessel is listed');
    ok(row().querySelector('.vessel-name').textContent === HOSTILE && noMarkup(row()), 'vessels list: markup-like name shows literally');
    ok(row().textContent.includes(HOSTILE_AGENT) && row().textContent.includes('<i>O</i>'), 'vessels list: agent and OPR show literally (no double escaping)');
    ok(await waitFor(() => $('#notifPanel').textContent.includes(HOSTILE)) && noMarkup($('#notifPanel')) && $('#notifBanner').textContent.includes(HOSTILE) && noMarkup($('#notifBanner')), 'alerts: markup-like name shows literally');
  }

  // A port user outside Alexandria (run: node ui_smoke_test.js suez): their own Master-data values are offered in the
  // Add vessel form. A short, separate run: the rest of this script is written for alex / admin / viewer.
  if (ROLE === 'suez') {
    await go('master');
    type($('[data-new="agent"]'), 'SMOKE SUEZ OWN AGENT');
    click($('[data-act="add-option"][data-kind="agent"]'));
    const ownRow = () => $$('.opt-row').find((r) => r.textContent.includes('SMOKE SUEZ OWN AGENT'));
    ok(await waitFor(() => ownRow()?.textContent.includes('Suez')), 'suez user: a value they add belongs to Suez');
    const own = { id: ownRow().querySelector('[data-act="del-option"]').dataset.id };
    await go('vessels');
    click($('#addVesselBtn'));
    ok(await waitFor(() => $('#vessel-form [name=agent]')) && [...$('#vessel-form [name=agent]').options].some((o) => o.textContent === 'SMOKE SUEZ OWN AGENT'), 'suez user: the Add vessel form offers their own agent');
    closeModal();
    ok([...$('#qa-agent').options].some((o) => o.textContent === 'SMOKE SUEZ OWN AGENT'), 'suez user: quick add offers their own agent');
    await w.fetch(`/api/options/${own.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
    return finish();
  }

  /* ======== layout: sidebar and pages ======== */
  const navItems = $$('#nav .nav-item').filter((a) => a.style.display !== 'none');
  ok($('#sidebar') && navItems.length === (ROLE === 'viewer' ? 7 : 8), 'sidebar lists the pages (read-only users have no Bulk add)');
  ok($$('#nav .nav-item').map((a) => a.dataset.page).join() === 'vessels,bulk,hotels,transport,calculations,dashboard,master,rates', 'Calculations sits after Transport');
  ok(!$('.tabs') && $('.sidebar'), 'navigation is a sidebar, not a tab bar');
  ok(!$('#page-vessels').hidden && $('#pageTitle').textContent === 'Vessels', 'starts on the Vessels page');
  for (const [page, title] of [['hotels', 'Hotels'], ['transport', 'Transport'], ['calculations', 'Calculations'], ['dashboard', 'Dashboard'], ['master', 'Master data'], ['rates', 'Exchange rates'], ['vessels', 'Vessels']]) {
    await go(page);
    ok($$('.page').filter((p) => !p.hidden).length === 1 && $('#pageTitle').textContent === title && $(`#nav [data-page="${page}"]`).classList.contains('active'), `sidebar opens "${title}"`);
  }

  /* ---- calculations page (every role sees it, money included) ---- */
  await go('calculations');
  ok(await waitFor(() => /Revenue LE .+ · Cost LE .+ · Profit LE .+ · \d+ lines?/.test($('#c-totals').textContent)), 'calculations: one totals line');
  const waterRow = () => $$('#c-tbody tr').find((t) => t.textContent.includes('MSC AURORA') && t.textContent.includes('Fresh Water'));
  ok(await waitFor(() => waterRow()) && waterRow().textContent.includes('USD 900.00 × 50.00 = 45,000.00'), 'calculations: a USD line shows its working');
  ok(waterRow().textContent.includes('EGP 30,000.00') && waterRow().textContent.includes('15,000.00'), 'calculations: cost and profit in EGP');
  ok([...$('#c-pager #c-page-size').options].map((o) => o.value).join() === '10,25,50,100', 'calculations: rows per page 10/25/50/100');
  ok([...$('#c-opr').options].map((o) => o.textContent).includes('MSK'), 'calculations: the OPR choices come from the range');
  type($('#c-opr'), 'MSK');
  ok(await waitFor(() => $$('#c-tbody tr').length > 0 && $$('#c-tbody tr').every((t) => t.textContent.includes('MSK'))), 'calculations: the OPR filter narrows the lines');
  type($('#c-opr'), '');
  await waitFor(() => $('#c-totals').textContent.includes('lines'));
  if (ROLE !== 'viewer') {
    // An edit made from the page (vessel name → summary → details → add a service) shows up on the page at once.
    click(waterRow().querySelector('[data-act="summary"]'));
    await waitFor(() => $('#modal [data-act="open-vessel"]'));
    click($('#modal [data-act="open-vessel"]'));
    await waitFor(() => $('[data-act="add-service"]'));
    click($('[data-act="add-service"]'));
    click($('[data-type="Others / Remarks"]'));
    type($('#svc-form [name=note]'), 'calc smoke'); type($('#svc-form [name=cost]'), '7');
    click($('[data-act="save-service"]'));
    await waitFor(() => modalText().includes('calc smoke'));
    closeModal();
    const othersRow = () => $$('#c-tbody tr').find((t) => t.textContent.includes('MSC AURORA') && t.textContent.includes('Others / Remarks'));
    ok(await waitFor(() => othersRow() && othersRow().textContent.includes('EGP 7.00')), 'calculations: an edit made from the page shows up without reloading');
    click(othersRow().querySelector('[data-act="summary"]')); // remove the test service again
    await waitFor(() => $('#modal [data-act="open-vessel"]'));
    click($('#modal [data-act="open-vessel"]'));
    await waitFor(() => $$('.svc-card').some((c) => c.textContent.includes('Others / Remarks')));
    click($$('.svc-card').find((c) => c.textContent.includes('Others / Remarks')).querySelector('[data-act="del-service"]'));
    await waitFor(() => !$$('.svc-card').some((c) => c.textContent.includes('Others / Remarks')));
    closeModal();
    await waitFor(() => !othersRow());
  }
  if (ROLE === 'admin') {
    // Rates are stored with 4 decimals; the working shows them in full so the multiplication adds up.
    await go('rates');
    type($('#rate-form [name=month]'), localNow().slice(0, 7)); type($('#rate-form [name=rate]'), '48.2525');
    click($('[data-act="save-rate"]'));
    await waitFor(() => $('#rates-panel').textContent.includes('48.2525'));
    await go('calculations');
    ok(await waitFor(() => waterRow()?.textContent.includes('USD 900.00 × 48.2525 = 43,427.25')), 'calculations: a 4-decimal rate is shown in full');
    await go('rates');
    type($('#rate-form [name=month]'), localNow().slice(0, 7)); type($('#rate-form [name=rate]'), '50');
    click($('[data-act="save-rate"]'));
    await waitFor(() => /\b50\b/.test($('#rates-panel').textContent));
  }
  await go('vessels');
  ok($$('#tbody tr').length > 0, 'vessel table renders');
  ok(!$('#stats') && !$('#exportBtn'), 'no stat cards and no CSV button on the Vessels page');
  ok($$('#tbody tr')[0].children.length === 9 && !$('th[data-sort="total_cost_egp"]') && !/Total Cost/.test($('thead').textContent), 'table has an Agent column and no Total Cost column');

  // The ☰ button: on a wide screen it hides / shows the sidebar (remembered); jsdom counts as wide.
  click($('#menuBtn'));
  ok(w.document.body.classList.contains('nav-collapsed') && w.localStorage.getItem('sheet.navCollapsed') === '1', '☰ hides the sidebar on a wide screen');
  click($('#menuBtn'));
  ok(!w.document.body.classList.contains('nav-collapsed') && w.localStorage.getItem('sheet.navCollapsed') === '0', '☰ shows it again');

  // Bulk add: no help paragraph and no placeholders.
  ok(!$('#page-bulk .help') && !$$('#page-bulk [placeholder]').length, 'bulk add has no help text and no placeholders');
  ok(!$('#tbody [data-act="open-vessel"]') && $('#tbody [data-act="summary"]'), 'rows have Summary but no separate Edit button');
  ok(ROLE === 'viewer' ? !$('#tbody [data-act="del-vessel-row"]') : !!$('#tbody [data-act="del-vessel-row"]'), 'rows have a Delete button only for users who can edit');

  /* ---- date range, server-side search and paging ---- */
  const monthStart = localNow().slice(0, 8) + '01';
  ok($('#f-from').value === monthStart && $('#f-to').value.slice(0, 7) === monthStart.slice(0, 7), 'date range defaults to this month');
  ok($('#page-size') && [...$('#page-size').options].map((o) => o.value).join() === '10,25,50,100' && $('#page-size').value === '50', 'rows per page: 10 / 25 / 50 / 100, default 50');
  ok($('#pager').textContent.includes('Showing'), 'pager shows "Showing x–y of n"');
  type($('#search'), 'zzzz-no-match');
  ok($$('#tbody tr').length > 0, 'search waits for a pause before asking the server');
  ok(await waitFor(() => $$('#tbody tr').length === 0 && $('#empty').style.display === 'block'), 'search with no match shows the empty state (from the server)');
  type($('#search'), '');
  ok(await waitFor(() => $$('#tbody tr').length > 0), 'clearing the search brings the rows back');
  type($('#page-size'), '10');
  ok(await waitFor(() => $('#page-size').value === '10'), 'rows per page can be changed');
  ok(w.localStorage.getItem('sheet.pageSize') === '10', 'rows-per-page choice is remembered');
  type($('#page-size'), '50');
  await waitFor(() => $('#page-size').value === '50');

  // Typing a date by keyboard: the browser reports every keystroke (year 0002, 0020, 0202, 2027).
  const monthEnd = $('#f-to').value;
  await sleep(500);
  let callsBefore = listCalls;
  type($('#f-to'), '0002-11-30'); // half-typed year, earlier than From
  ok($('#f-to').value === '0002-11-30', 'a half-typed year in To is not reset while typing');
  for (const partial of ['0020-11-30', '0202-11-30', '2027-11-30']) type($('#f-to'), partial);
  await sleep(900);
  ok($('#f-to').value === '2027-11-30' && listCalls - callsBefore === 1, `typing a year into To ends on it and asks the server once (asked ${listCalls - callsBefore} times)`);
  callsBefore = listCalls;
  for (const partial of ['0002-11-01', '0020-11-01', '0202-11-01', '2025-11-01']) type($('#f-from'), partial);
  await sleep(900);
  ok(listCalls - callsBefore === 1, `typing a year into From asks the server once, after a pause (asked ${listCalls - callsBefore} times)`);
  callsBefore = listCalls;
  type($('#f-from'), '2030-01-01');
  await sleep(900);
  ok(listCalls === callsBefore && /From must be on or before To/.test($('#status-text').textContent), 'From after To is not sent and says why');
  type($('#f-from'), monthStart); type($('#f-to'), monthEnd);
  ok(await waitFor(() => $('#f-to').value === monthEnd && $('#status-text').textContent === 'Synced'), 'range restored');

  // Switching ports quickly: a late answer for the first port must not overwrite the alerts of the second.
  if (ROLE !== 'alex') {
    slowAlertsFor = 'port=alexandria';
    type($('#portSelect'), 'alexandria');
    type($('#portSelect'), 'portsaid');
    await sleep(1200);
    slowAlertsFor = null;
    const banner = $('#notifBanner').textContent;
    ok(banner.includes('ARKAS STAR') && !banner.includes('MSC AURORA'), 'alerts follow the last port chosen, even if an earlier answer arrives late');
    type($('#portSelect'), 'ALL');
    await waitFor(() => $('#notifBanner').textContent.includes('MSC AURORA'));
  }
  click($$('#tbody tr')[0]);
  ok(await waitFor(() => $('#overlay').classList.contains('open')) && $('#overlay').classList.contains('open') && /Summary of services/.test(modalText()), 'vessel dialog opens and has a "Summary of services" button');
  closeModal();

  /* ======== read-only user ======== */
  if (ROLE === 'viewer') {
    ok($('#addVesselBtn').style.display === 'none' && $('#quickAdd').style.display === 'none', 'read-only: add controls hidden');
    ok($('#portSelect').style.display !== 'none', 'read-only: sees the port selector');
    await go('bulk');
    ok($('#page-bulk').hidden && !$('#page-vessels').hidden, 'read-only: opening #bulk lands back on Vessels');
    click($$('#tbody tr')[0]);
    await waitFor(() => $('#modal [data-act="summary"]')); // the dialog opens once the vessel is at hand
    ok(!$('[data-act="add-service"]') && !$('[data-act="del-vessel"]') && !$('[data-act="edit-vessel"]'), 'read-only: no edit buttons in the dialog');
    click($('#modal [data-act="summary"]'));
    ok(await waitFor(() => modalText().includes('Port call') && modalText().includes('Services on this vessel')), 'read-only: summary of services opens');
    closeModal();
    await go('master');
    ok($$('#master-grid .panel').length === 6 && !$('[data-act="add-option"]') && !$('[data-act="del-option"]'), 'read-only: master data is view-only');
    await go('rates');
    ok(!$('#rate-form'), 'read-only: cannot edit exchange rates');
    for (const [page, p] of [['hotels', 'h'], ['transport', 't']]) {
      await go(page);
      ok(await waitFor(() => $(`#${p}-head`).textContent.includes('Vessel')), `read-only: ${page} list renders`);
      ok($(`#${p}-add`).style.display === 'none' && /Cost/.test($(`#${p}-head`).textContent) && /Revenue/.test($(`#${p}-head`).textContent), `read-only: ${page} has no Add button but sees cost and revenue`);
      ok($(`#${p}-port`).style.display !== 'none', `read-only: ${page} has the port selector`);
    }
    return finish();
  }

  if (ROLE === 'alex') ok($('#portBanner').textContent.includes('Alexandria'), 'port user sees the port banner');
  if (ROLE === 'admin') ok($('#qa-port').style.display !== 'none' && $('#portSelect').style.display !== 'none', 'admin sees the port selectors');
  if (ROLE === 'admin') {
    const keepPort = $('#qa-port').value;
    const pick = [...$('#qa-opr').options].find((o) => o.value)?.value; // the demo data's OPRs are All-ports values
    type($('#qa-opr'), pick);
    type($('#qa-port'), 'suez');
    ok(pick && $('#qa-opr').value === pick, 'quick add: changing the port keeps the chosen OPR');
    type($('#qa-port'), keepPort);
    type($('#qa-opr'), '');
  }

  /* ======== master data page ======== */
  await go('master');
  ok($$('#master-grid .panel h3').map((h) => h.textContent).join() === 'OPR,POC,Agent,Hotel,Airport,Port', 'master data has OPR, POC, Agent, Hotel, Airport and Port lists');
  type($('[data-new="agent"]'), 'SMOKE AGENT');
  click($('[data-act="add-option"][data-kind="agent"]'));
  ok(await waitFor(() => $('#master-grid').textContent.includes('SMOKE AGENT')), 'master data: agent added');
  type($('[data-new="opr"]'), 'SMOKE-OPR');
  click($('[data-act="add-option"][data-kind="opr"]'));
  ok(await waitFor(() => $('#master-grid').textContent.includes('SMOKE-OPR')), 'master data: OPR added');
  type($('[data-new="hotel"]'), 'SMOKE HOTEL');
  click($('[data-act="add-option"][data-kind="hotel"]'));
  ok(await waitFor(() => $('#master-grid').textContent.includes('SMOKE HOTEL')), 'master data: hotel added');
  for (const [kind, value] of [['airport', 'SMOKE ALEXANDRIA AIRPORT'], ['port', 'SMOKE ALEXANDRIA PORT']]) {
    type($(`[data-new="${kind}"]`), value);
    click($(`[data-act="add-option"][data-kind="${kind}"]`));
    ok(await waitFor(() => $('#master-grid').textContent.includes(value)), `master data: ${kind} added`);
  }

  /* ---- master data per port ---- */
  if (ROLE === 'alex') {
    ok(!$('select[data-new-port]') && !$('select[data-option-port]'), 'port user: no port choices on Master data (values go to their port)');
  }
  if (ROLE === 'admin') {
    const portChoices = (sel) => [...sel.options].map((o) => o.value).join();
    ok($$('select[data-new-port]').length === 6 && portChoices($('select[data-new-port="agent"]')) === ',alexandria,portsaid,damietta,suez', 'admin: every list has a port choice (All ports + each port)');
    for (const [kind, value] of [['agent', 'SMOKE SUEZ AGENT'], ['hotel', 'SMOKE SUEZ HOTEL']]) {
      type($(`[data-new="${kind}"]`), value);
      type($(`select[data-new-port="${kind}"]`), 'suez');
      click($(`[data-act="add-option"][data-kind="${kind}"]`));
      await waitFor(() => $('#master-grid').textContent.includes(value));
    }
    const optionRow = (value) => $$('.opt-row').find((r) => r.textContent.includes(value));
    ok(optionRow('SMOKE SUEZ AGENT')?.querySelector('select[data-option-port]')?.value === 'suez', 'admin: the new agent belongs to Suez');
    ok($('select[data-new-port="agent"]').value === 'suez', 'admin: the port chosen for a list is remembered for the next value');
    await go('bulk'); // first visit: the default lists follow the bulk port (Alexandria)
    ok(![...$('#bk-agent').options].some((o) => o.textContent === 'SMOKE SUEZ AGENT'), 'bulk add: default lists follow the target port on the first visit');
    await go('vessels');
    type($('#portSelect'), 'suez');
    ok(await waitFor(() => $('#qa-port').value === 'suez' && [...$('#qa-agent').options].some((o) => o.textContent === 'SMOKE SUEZ AGENT')), 'quick add follows the header port selector');
    type($('#portSelect'), 'ALL');
    await waitFor(() => $('#portSelect').value === 'ALL');
    await go('master');
    const agentChoices = () => [...$('#vessel-form [name=agent]').options].map((o) => o.textContent);
    await go('vessels');
    click($('#addVesselBtn'));
    type($('#vessel-form [name=port]'), 'alexandria');
    ok(await waitFor(() => !agentChoices().includes('SMOKE SUEZ AGENT')), 'a Suez agent is not offered for an Alexandria vessel');
    type($('#vessel-form [name=port]'), 'suez');
    ok(await waitFor(() => agentChoices().includes('SMOKE SUEZ AGENT')), 'switching the vessel to Suez offers the Suez agent');
    closeModal();
    await go('master');
    type(optionRow('SMOKE SUEZ AGENT').querySelector('select[data-option-port]'), '');
    ok(await waitFor(() => optionRow('SMOKE SUEZ AGENT')?.querySelector('select[data-option-port]')?.value === ''), 'admin: moving a value to All ports saves');
    await go('vessels');
    click($('#addVesselBtn'));
    type($('#vessel-form [name=port]'), 'alexandria');
    ok(await waitFor(() => agentChoices().includes('SMOKE SUEZ AGENT')), 'an All-ports agent is offered everywhere');
    closeModal();
    await go('master');
  }
  const agentRow = $$('.opt-row').find((r) => r.textContent.includes('SMOKE AGENT'));
  ok(agentRow.textContent.includes('0 vessels'), 'master data: shows how many vessels use a value');
  ok($$('#qa-agent option').some((o) => o.textContent === 'SMOKE AGENT') && $$('#qa-opr option').some((o) => o.textContent === 'SMOKE-OPR'), 'master data: dropdowns elsewhere are updated');

  /* ======== quick add (with agent) ======== */
  await go('vessels');
  const NAME = 'UI SMOKE SHIP';
  type($('#qa-name'), 'ui smoke ship');
  ok($('#qa-name').value === NAME, 'quick-add upper-cases the name');
  type($('#qa-date'), '2020-01-15');
  type($('#qa-agent'), 'SMOKE AGENT');
  click($('#qa-add'));
  ok(await waitFor(() => $('#rangeNotice').textContent.includes('15.01.2020 is outside the current date range')), 'notice for a vessel saved outside the range');
  ok(!rowFor(NAME), 'the range is not changed by itself');
  click($('[data-act="show-outside"]'));
  ok(await waitFor(() => rowFor(NAME)) && $('#f-from').value === '2020-01-15' && $('#rangeNotice').hidden, 'Show it widens the range and shows the row');
  ok(rowFor(NAME).textContent.includes('SMOKE AGENT'), 'the agent shows in the table');
  await go('master');
  ok(await waitFor(() => $$('.opt-row').find((r) => r.textContent.includes('SMOKE AGENT'))?.textContent.includes('1 vessel')), 'master data: usage count goes up');
  await go('vessels');

  /* ======== add-vessel form (+ XSS) ======== */
  click($('#addVesselBtn'));
  ok($('#vessel-form select[name=opr]') && $('#vessel-form select[name=poc]') && $('#vessel-form select[name=agent]'), 'vessel form uses master-data dropdowns');
  ok($$('#vessel-form [type=datetime-local]').length === 5, 'vessel form has the five port-call time fields');
  type($('#vessel-form [name=name]'), '<img src=x onerror=window.__xss=1>');
  type($('#vessel-form [name=opr]'), 'MSK');
  type($('#vessel-form [name=date]'), '2020-01-20');
  type($('[data-sum="Vendor Name"]'), 'ACME & SONS');
  click($('[data-act="save-vessel"]'));
  await waitFor(() => $('#modal h2')?.textContent.includes('<img'));
  ok($('#modal h2').textContent.includes('<img') && !w.__xss && !$('#modal h2 img'), 'XSS payload in a vessel name does not execute');
  closeModal();
  ok(!$$('#tbody img').length, 'XSS payload is escaped in the table too');

  /* ======== saving into another port than the one shown (admin) ======== */
  if (ROLE === 'admin') {
    type($('#portSelect'), 'suez');
    await waitFor(() => $('#portBanner').textContent.includes('Suez'));
    click($('#addVesselBtn'));
    type($('#vessel-form [name=name]'), 'PORT MOVE');
    type($('#vessel-form [name=date]'), localNow());
    type($('#vessel-form [name=port]'), 'alexandria');
    click($('[data-act="save-vessel"]'));
    await waitFor(() => $('#modal h2')?.textContent.includes('PORT MOVE'));
    closeModal();
    ok(await waitFor(() => $('#portSelect').value === 'ALL' && rowFor('PORT MOVE')), 'a vessel saved into another port stays visible (port selector goes to All)');
  }

  /* ======== port-call times and agent ======== */
  await openRow(NAME);
  click($('#modal [data-act="edit-vessel"]'));
  ok($('#vessel-form [name=agent]').value === 'SMOKE AGENT', 'edit form shows the saved agent');
  click($('[data-act="time-now"][data-target="arrival_at"]'));
  ok(/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test($('[name=arrival_at]').value), '"Now" fills a time');
  const times = { arrival_at: '2020-01-15T06:00', berthing_at: '2020-01-15T08:30', ops_start_at: '2020-01-15T09:00', ops_end_at: '2020-01-15T15:00', sailing_at: '2020-01-15T05:00' };
  Object.entries(times).forEach(([name, value]) => type($(`[name=${name}]`), value));
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /cannot be before/.test($('#modal .error')?.textContent || '')), 'impossible times are rejected with a clear message');
  type($('[name=sailing_at]'), '2020-01-15T18:00');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => modalText().includes('15.01.2020 08:30') && modalText().includes('SMOKE AGENT')), 'times and agent saved and shown in the Port call block');
  ok(modalText().includes('9h 30m') && modalText().includes('6h') && modalText().includes('12h'), 'durations: 9h 30m at berth, 6h operations, 12h in port');
  ok($('#modal .status-chip')?.textContent === 'Sailed', 'status chip shows "Sailed"');
  closeModal();
  ok(rowFor(NAME).querySelector('.status-chip')?.textContent === 'Sailed', 'status chip is also in the table');

  /* ======== Fresh Water + live preview ======== */
  await openRow(NAME);
  click($('[data-act="add-service"]'));
  click($('[data-type="Fresh Water"]'));
  type($('[name=quantity]'), '40'); type($('[name=revenue]'), '100'); type($('[name=revenueCurrency]'), 'USD'); type($('[name=cost]'), '2000');
  ok($('#preview').textContent.includes('No exchange rate'), 'preview warns when the month has no rate');
  type($('[name=exchangeRate]'), '50');
  ok($('#preview').textContent.includes('5,000.00') && $('#preview').textContent.includes('3,000.00'), 'preview: 100 USD at 50 = 5,000 revenue, 3,000 profit');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('Quantity (tons): 40')), 'Fresh Water saved');

  /* ======== Cash to Master ======== */
  click($('[data-act="add-service"]'));
  click($('[data-type="Cash to Master"]'));
  type($('[name=amount]'), '1000'); type($('[name=amountCurrency]'), 'USD'); type($('[name=percentage]'), '5'); type($('[name=exchangeRate]'), '50');
  const preview = () => $('#preview').textContent;
  ok(preview().includes('2,500.00') && preview().includes('47,500.00'), 'cash: 5% of 1000 USD = 2,500 ours, 47,500 to the master');
  type($('[name=percentage]'), '10');
  ok(preview().includes('5,000.00') && preview().includes('45,000.00'), 'cash: revenue updates live');
  type($('[name=shareMode]'), 'fixed'); type($('[name=fixedRevenue]'), '100');
  ok(preview().includes('5,000.00'), 'cash: fixed 100 USD gives 5,000 revenue');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => $('[data-act="add-service"]') && modalText().includes('our share fixed USD 100.00')), 'Cash to Master saved');

  /* ======== multi-entry ======== */
  click($('[data-act="add-service"]'));
  click($('[data-type="Delivery Parcels"]'));
  click($('[data-act="add-entry"]')); click($('[data-act="add-entry"]'));
  const [first, second] = $$('.entry');
  type(first.querySelector('[data-f=awb]'), 'AWB-1'); type(first.querySelector('[data-f=weight]'), '3');
  type(first.querySelector('[data-f=cost]'), '250'); type(first.querySelector('[data-f=revenue]'), '10');
  click(second.querySelector('[data-act="rm-entry"]'));
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('AWB-1') && modalText().includes('3 kg')), 'Delivery Parcels saved');

  /* ======== crew change ======== */
  click($('[data-act="add-service"]'));
  click($('[data-type="Crew Change"]'));
  click($('[data-act="add-crew"][data-group="onSigners"]'));
  type($('.crew-card [data-crew=personalData]'), 'Surname: Test\nGiven name: Ahmed\nRank: 2/E\nNationality: Egyptian');
  ok($('.crew-card [data-crew=name]').value === 'Ahmed Test', 'crew: name filled from personal data');
  click($('[data-act="add-crew"][data-group="offSigners"]'));
  const offCard = $('.crew-card[data-group="offSigners"]');
  type(offCard.querySelector('[data-crew=name]'), 'Mona Off');
  type(offCard.querySelector('[data-crew=flightData]'), 'FLIGHT TK 689 - Turkish Airlines\nDEPARTURE: Alexandria, Egypt  05 APR 08:55\nARRIVAL: Istanbul, Turkey  05 APR 12:30');
  ok($('#svc-form [name=cost]') && $('#svc-form [name=revenue]'), 'crew change: has cost and revenue like every service');
  type($('#svc-form [name=cost]'), '100');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('On-signers (1): Ahmed Test')), 'Crew Change saved');
  ok($$('.svc-card').some((c) => c.textContent.includes('Crew Change') && c.textContent.includes('LE 100.00')), 'crew change: its cost shows on the vessel');

  /* ======== summary of services ======== */
  click($('#modal [data-act="summary"]'));
  ok(await waitFor(() => modalText().includes('TOTAL PROFIT')), 'summary opens from the vessel dialog');
  ok(modalText().includes('Port call') && modalText().includes('SMOKE AGENT') && modalText().includes('15.01.2020 06:00'), 'summary: port call times and agent');
  ok(modalText().includes('Services on this vessel') && modalText().includes('Fresh Water ×1') && modalText().includes('Crew Change ×1'), 'summary: services listed with counts');
  ok(modalText().includes('2/E') && modalText().includes('Egyptian') && modalText().includes('Alexandria · 05 APR 08:55'), 'summary: crew table');
  ok(!!$('#modal [data-act="print"]'), 'summary: has a Print button');
  closeModal();
  click(rowFor(NAME).querySelector('[data-act="summary"]'));
  ok(await waitFor(() => $('#modal h2')?.textContent === NAME && modalText().includes('Port call')), 'summary also opens from the table button');
  closeModal();

  /* ======== edit + delete a service ======== */
  await openRow(NAME);
  click($$('[data-act="edit-service"]')[0]);
  type($('[name=quantity]'), '55');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('Quantity (tons): 55')), 'service edit saved');
  const before = $$('.svc-card').length;
  click($$('[data-act="del-service"]').pop());
  ok(await waitFor(() => $$('.svc-card').length === before - 1), 'service deleted');
  closeModal();

  /* ======== bulk add ======== */
  await go('bulk');
  ok($('#bk-opr') && $$('#bk-agent option').some((o) => o.textContent === 'SMOKE AGENT'), 'bulk page: dropdowns come from master data');
  if (ROLE === 'admin') ok($('#bk-port-wrap').style.display !== 'none', 'bulk page: admin can choose the port');
  type($('#bk-date'), '2026-11-20');
  type($('#bk-agent'), 'SMOKE AGENT');
  type($('#bk-text'), ['Vessel\tDate\tOPR\tPOC\tAgent', 'BULK A\t13.11.2026\tSMOKE-OPR\tALY\tSMOKE AGENT', 'bulk b\t14/11/2026', 'BULK C\tnot-a-date', 'BULK A\t13.11.2026'].join('\n'));
  click($('[data-act="bulk-preview"]'));
  ok(await waitFor(() => $('#bk-preview .bulk-table')) && $('#bk-preview .bulk-table tbody').children.length === 4, 'bulk: four lines previewed (header ignored)');
  ok($('#bk-preview').textContent.includes('1 with errors') && $('[data-act="bulk-create"]').disabled, 'bulk: a bad row blocks creation');
  ok($('#bk-preview').textContent.includes('1 duplicate'), 'bulk: duplicate line is flagged and skipped');
  // Editable preview: fix things in the table instead of the pasted text.
  type($('#bk-text'), ['BULK A\t13.11.2026\tSMOKE-OPR\tALY\tSMOKE AGENT', 'bulk b\t31.02.2026', 'BULK C\t14.11.2026'].join('\n'));
  click($('[data-act="bulk-preview"]'));
  ok(await waitFor(() => $('#bk-preview tr[data-i="1"] [data-f=date]')), 'bulk: preview rows are editable');
  const cell = (i, f) => $(`#bk-preview tr[data-i="${i}"] [data-f=${f}]`);
  ok($('[data-act="bulk-create"]').disabled && /not a valid date/.test($('#bk-preview tr[data-i="1"] .bk-check').textContent), 'bulk: a bad pasted date shows ✗');
  const nameInput = cell(2, 'name'); nameInput.focus(); type(nameInput, 'BULK C2');
  ok(w.document.activeElement === nameInput && nameInput.value === 'BULK C2', 'bulk: typing in a cell keeps focus');
  type(cell(1, 'date'), '2026-11-14');
  ok(await waitFor(() => !$('[data-act="bulk-create"]').disabled && $('[data-act="bulk-create"]').textContent.includes('Create 3')), 'bulk: fixing the date enables Create 3');
  type(cell(2, 'date'), '');
  ok($('[data-act="bulk-create"]').disabled && /Date is missing/.test($('#bk-preview tr[data-i="2"] .bk-check').textContent), 'bulk: clearing a date blocks Create');
  click($('#bk-preview tr[data-i="2"] [data-act="bulk-del-row"]'));
  ok(await waitFor(() => $('[data-act="bulk-create"]').textContent.includes('Create 2') && !$('[data-act="bulk-create"]').disabled), 'bulk: removing the bad row enables Create 2');
  type($('#bk-all-agent'), 'SMOKE AGENT'); click($('[data-act="bulk-apply-all"]'));
  ok(cell(1, 'agent').value === 'SMOKE AGENT' && cell(0, 'agent').value === 'SMOKE AGENT', '"Set on all rows" fills the agent');
  click($('[data-act="bulk-add-row"]'));
  ok($$('#bk-preview tbody tr').length === 3 && /name is missing/.test($('#bk-preview tr[data-i="2"] .bk-check').textContent), 'bulk: + Add row adds a blank row');
  click($('#bk-preview tr[data-i="2"] [data-act="bulk-del-row"]'));
  w.confirm = () => false;
  click($('[data-act="bulk-preview"]'));
  ok($$('#bk-preview tbody tr').length === 2 && cell(1, 'agent').value === 'SMOKE AGENT', 'bulk: re-Preview asks before replacing edited rows');
  w.confirm = () => true;
  const createBtn = () => $('[data-act="bulk-create"]');
  await waitFor(() => createBtn()?.disabled === false);

  // Leaving a cell (the browser fires "change" on blur) must not disable Create when nothing changed.
  cell(0, 'name').dispatchEvent(new w.Event('change', { bubbles: true }));
  ok(createBtn() && !createBtn().disabled, 'bulk: leaving a cell without changing it keeps Create enabled');

  // A late answer to an older duplicate check must not enable Create while a newer check is still due.
  let release;
  holdBulkCheck = new Promise((r) => { release = r; });
  type(cell(0, 'name'), 'BULK A TEMP');
  await sleep(400);                      // that check is now waiting at the server
  type(cell(0, 'name'), 'BULK A');       // a newer edit: its check fires 300 ms later
  release(); holdBulkCheck = null;
  await sleep(80);                       // the old answer has arrived
  ok(createBtn().disabled, 'bulk: a late answer to an older check does not enable Create');
  await waitFor(() => createBtn()?.disabled === false);

  // If the duplicate check fails, Create stays off until a check succeeds.
  failBulkCheck = true;
  type(cell(0, 'name'), 'BULK A TEMP');
  await sleep(600);
  ok(createBtn().disabled && /couldn't check for duplicates/i.test($('#bk-preview').textContent), 'bulk: a failed duplicate check keeps Create off and says so');
  failBulkCheck = false;
  type(cell(0, 'name'), 'BULK A');
  ok(await waitFor(() => createBtn()?.disabled === false), 'bulk: the next successful check enables Create again');

  ok(createBtn() && !createBtn().disabled && createBtn().textContent.includes('Create 2'), 'bulk: "Create 2 vessels" is ready');
  const createsBefore = bulkCreates;
  click(createBtn()); click(createBtn()); // a double click
  ok(await waitFor(() => $('#bk-preview').textContent.includes('Added 2 vessels')), 'bulk: vessels created');
  ok(bulkCreates - createsBefore === 1, `bulk: a double click creates the vessels once (sent ${bulkCreates - createsBefore} times)`);
  click($('[data-act="bulk-view"]'));
  ok(await waitFor(() => !$('#page-vessels').hidden), 'bulk: "View them" opens the Vessels page');
  await go('bulk');
  type($('#bk-text'), 'BULK A\t13.11.2026');
  click($('[data-act="bulk-preview"]'));
  ok(await waitFor(() => $('#bk-preview').textContent.includes('1 duplicate')), 'bulk: a vessel already saved is flagged by the server');
  type(cell(0, 'name'), 'BULK A NEW');
  ok(await waitFor(() => !$('#bk-preview').textContent.includes('1 duplicate')), 'bulk: the duplicate check re-runs after an edit');
  type(cell(0, 'name'), 'BULK A');
  await waitFor(() => $('#bk-preview').textContent.includes('1 duplicate'));
  if (ROLE === 'admin') {
    const createdIn = $('#bk-port').value;
    type($('#bk-port'), createdIn === 'suez' ? 'damietta' : 'suez');
    ok(await waitFor(() => !$('#bk-preview').textContent.includes('1 duplicate')), 'bulk: changing the port re-checks duplicates');
    type($('#bk-port'), createdIn);
  }
  click($('[data-act="bulk-clear"]'));
  type($('#bk-text'), Array.from({ length: 200 }, (_, i) => `LIMIT ${i + 1}\t13.11.2026`).join('\n'));
  click($('[data-act="bulk-preview"]'));
  await waitFor(() => $$('#bk-preview tbody tr').length === 200);
  click($('[data-act="bulk-add-row"]'));
  ok($$('#bk-preview tbody tr').length === 200 && /limit is 200/.test($('#bk-error').textContent), 'bulk: + Add row stops at 200 rows');
  click($('[data-act="bulk-clear"]'));
  await go('vessels');
  ok(await waitFor(() => rowFor('BULK A') && rowFor('BULK B')), 'bulk: new vessels appear in the table');
  ok(rowFor('BULK A').textContent.includes('SMOKE AGENT') && rowFor('BULK B').textContent.includes('SMOKE AGENT'), 'bulk: default agent applied to rows that left it out');

  /* ======== exchange rates page ======== */
  await go('rates');
  if (ROLE === 'admin') {
    type($('#rate-form [name=month]'), '2020-01'); type($('#rate-form [name=rate]'), '51.5');
    click($('[data-act="save-rate"]'));
    ok(await waitFor(() => $('#rates-panel').textContent.includes('51.5')), 'exchange rates page: rate saved');
  } else {
    ok(!$('#rate-form') && !$('[data-act="del-rate"]'), 'port user: exchange rates are admin-only');
  }

  /* ======== notifications (quick add uses today's date) ======== */
  await go('vessels');
  type($('#qa-name'), 'smoke today');
  type($('#qa-date'), localNow());
  click($('#qa-add'));
  ok(await waitFor(() => rowFor('SMOKE TODAY')), 'vessel dated today created');
  ok(await waitFor(() => $('#bellBadge').style.display !== 'none' && $('#notifBanner').textContent.includes('SMOKE TODAY')), 'bell badge and banner show vessels due today (alerts load alongside the table)');
  // The banner can shrink to one line (and back); the choice is remembered.
  click($('#notifBanner [data-act="toggle-alerts"]'));
  ok($('#notifBanner').classList.contains('collapsed') && !$('#notifBanner .notif-row') && /\d+ today/.test($('#notifBanner').textContent) && w.localStorage.getItem('sheet.alertsCollapsed') === '1', 'alerts banner shrinks to one line');
  click($('#notifBanner [data-act="toggle-alerts"]'));
  ok(!$('#notifBanner').classList.contains('collapsed') && $('#notifBanner').textContent.includes('SMOKE TODAY'), 'alerts banner expands again');
  click($('#bell'));
  ok($('#notifPanel').classList.contains('open') && $('#notifPanel').textContent.includes('SMOKE TODAY'), 'bell panel lists the vessel');
  click($('#notifPanel [data-act="summary"]'));
  ok(await waitFor(() => $('#modal h2')?.textContent.includes('SMOKE TODAY')), 'clicking a notification opens its summary');
  closeModal();

  /* ======== hotels and transport ======== */
  const dmyOf = (iso) => iso.split('-').reverse().join('.');
  const todayIso = localNow();
  const plusDays = (iso, n) => { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const pickVessel = async (name) => {
    type($('#bkd-vessel-q'), name);
    ok(await waitFor(() => $$('#bkd-vessel-results [data-act="booking-pick-vessel"]').some((b) => b.textContent.includes(name))), `dialog: vessel search finds ${name}`);
    click($$('#bkd-vessel-results [data-act="booking-pick-vessel"]').find((b) => b.textContent.includes(name)));
    return waitFor(() => $$('#bkd-crew input[data-crew-i]').length >= 2);
  };
  await go('hotels');
  ok(await waitFor(() => /Cost\/night/.test($('#h-head').textContent) && /Revenue\/night/.test($('#h-head').textContent)), 'hotels: cost and revenue per night columns');
  ok($('#h-from').value === todayIso.slice(0, 8) + '01' && [...$('#h-pager #h-page-size').options].map((o) => o.value).join() === '10,25,50,100', 'hotels: this month by default, rows per page 10/25/50/100');
  click($('#h-add'));
  ok(await waitFor(() => $('#bkd-vessel-q')), 'hotels: "+ Add hotel stay" opens the dialog');
  ok(await pickVessel('MSC AURORA'), 'dialog: picking the vessel lists its crew');
  if (ROLE === 'admin') {
    const hotelChoices = [...$('[data-bf="hotel"]').options].map((o) => o.textContent);
    ok(hotelChoices.includes('SMOKE HOTEL') && !hotelChoices.includes('SMOKE SUEZ HOTEL'), 'dialog: an Alexandria vessel is offered only Alexandria and All-ports hotels');
  }
  click($$('#bkd-crew input[data-crew-i]')[0]);
  await waitFor(() => $$('#bkd-guests [data-g-f="name"]').length === 1);
  click($$('#bkd-crew input[data-crew-i]')[1]); // the dialog redraws after each tick: look the box up again
  await waitFor(() => $$('#bkd-guests [data-g-f="name"]').length === 2);
  ok($$('#bkd-guests [data-g-f="name"]').map((i) => i.value).join() === 'Ahmed Test,Ali Sayed', 'dialog: ticked crew become guest lines');
  ok($('[data-bf="check_in"]').value === todayIso, 'dialog: check-in pre-filled from the flight arrival');
  type($('[data-bf="hotel"]'), 'SMOKE HOTEL'); type($('[data-bf="nights"]'), '2');
  ok($('[data-bf="cost"]') && $('[data-bf="revenue"]') && $('[data-bf="revenue_currency"]') && !$('[data-bf="price"]'), 'dialog: cost and revenue, each with a currency');
  type($('[data-bf="cost"]'), '80'); type($('[data-bf="revenue"]'), '4500');
  const currencySelect = $('[data-bf="cost_currency"]');
  currencySelect.focus();
  type(currencySelect, 'USD');
  ok(await waitFor(() => $('[data-bf="exchange_rate"]')), 'dialog: the exchange rate shows when either side is USD');
  ok(w.document.activeElement?.dataset?.bf === 'cost_currency', 'dialog: the field you were in keeps focus when the dialog redraws');
  const postsBefore = stayPosts;
  click($('[data-act="booking-save"]')); click($('[data-act="booking-save"]')); // a double click
  ok(await waitFor(() => !$('#overlay').classList.contains('open') && $('#h-tbody').textContent.includes('AHMED TEST') && $('#h-tbody').textContent.includes('ALI SAYED')), 'hotels: the shared room is listed with both guests');
  ok(stayPosts - postsBefore === 1, `hotels: a double click on Save creates the stay once (sent ${stayPosts - postsBefore} times)`);
  const stayRow = () => $$('#h-tbody tr').find((t) => t.textContent.includes('AHMED TEST'));
  ok(stayRow().textContent.includes('USD 80.00') && stayRow().textContent.includes('EGP 4,500.00') && stayRow().textContent.includes('MSC AURORA') && stayRow().textContent.includes(dmyOf(plusDays(todayIso, 2))), 'hotels: cost, revenue, vessel and check-out shown');
  click(stayRow());
  ok(await waitFor(() => $('[data-bf="nights"]')?.value === '2'), 'hotels: a row opens its booking');
  type($('[data-bf="nights"]'), '3');
  click($('[data-act="booking-save"]'));
  ok(await waitFor(() => stayRow()?.textContent.includes(dmyOf(plusDays(todayIso, 3)))), 'hotels: editing nights moves the check-out');

  // More stays straight through the API: one to open quickly after another, and enough to fill two pages.
  const post = (url, body) => w.fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() }, body: JSON.stringify(body) });
  const vesselId = (await (await w.fetch(`/api/vessels/?q=${encodeURIComponent('MSC AURORA')}`)).json()).vessels[0].id;
  const extraStay = (name, nights) => post('/api/hotels/', { vessel: vesselId, hotel: 'SMOKE HOTEL', check_in: todayIso, nights, guests: [{ name }] });
  await extraStay('LATE TEST', 5);
  for (let i = 1; i <= 10; i += 1) await extraStay(`STEP ${i}`, 1);
  await go('vessels'); await go('hotels');
  await waitFor(() => $$('#h-tbody tr').some((t) => t.textContent.includes('LATE TEST')));

  // Opening one stay and then another before the first answers must show the second one only.
  let releaseStay;
  holdStay = { id: stayRow().dataset.id, until: new Promise((r) => { releaseStay = r; }) };
  click(stayRow());
  click($$('#h-tbody tr').find((t) => t.textContent.includes('LATE TEST')));
  await waitFor(() => $('[data-bf="nights"]')?.value === '5');
  releaseStay(); holdStay = null;
  await sleep(150);
  ok($('[data-bf="nights"]').value === '5' && $('#bkd-guests [data-g-f="name"]').value === 'LATE TEST', 'hotels: a late answer for another stay does not overwrite the open dialog');
  closeModal();

  // Deleting the last row of the last page steps back a page.
  type($('#h-page-size'), '10');
  await waitFor(() => $$('#h-tbody tr').length === 10);
  click($('[data-act="booking-page"][data-step="1"]'));
  await waitFor(() => $('#h-pager').textContent.includes('Page 2'));
  for (const row of $$('#h-tbody tr')) {
    click($$('#h-tbody tr')[0]);
    await waitFor(() => $('[data-act="booking-delete"]'));
    click($('[data-act="booking-delete"]'));
    await waitFor(() => !$('#overlay').classList.contains('open'));
    await sleep(100);
    void row;
  }
  ok(await waitFor(() => $$('#h-tbody tr').length === 10 && !$('#h-pager').textContent.includes('Page 2')), 'hotels: deleting the last row of the last page steps back a page');
  type($('#h-page-size'), '50');
  await waitFor(() => $$('#h-tbody tr').length > 10 || $('#h-pager').textContent.includes('of'));

  await go('transport');
  click($('#t-add'));
  await waitFor(() => $('#bkd-vessel-q'));
  await pickVessel('MSC AURORA');
  click($('[data-act="booking-save"]'));
  ok(await waitFor(() => /Add at least one guest\./.test($('#modal .error')?.textContent || '')), 'transport: saving with no guest says why');
  click($$('#bkd-crew input[data-crew-i]')[0]);
  type($('[data-bf="from_place"]'), 'airport'); type($('[data-bf="to_place"]'), 'port');
  ok(await waitFor(() => $('[data-bf="port_name"]')?.value === 'SMOKE ALEXANDRIA PORT'), 'transport: the port is pre-filled from the vessel\'s port');
  ok(await waitFor(() => $('[data-bf="airport"]')?.value === 'SMOKE ALEXANDRIA AIRPORT'), 'transport: the airport is pre-filled from the flight\'s city');
  type($('[data-bf="to_place"]'), 'hotel');
  ok(await waitFor(() => $('[data-bf="hotel"]')?.value === 'SMOKE HOTEL'), 'transport: the hotel is pre-filled from the guest\'s stay');
  ok(!$('[data-bf="port_name"]') && $('[data-bf="airport"]').value === 'SMOKE ALEXANDRIA AIRPORT', 'transport: only the ends in use ask which airport / port / hotel');
  ok($('[data-bf="at"]').value === `${todayIso}T10:00`, 'transport: the time is pre-filled from the flight arrival');
  click($('[data-act="booking-save"]'));
  ok(await waitFor(() => $('#t-tbody').textContent.includes('Airport (SMOKE ALEXANDRIA AIRPORT) → Hotel (SMOKE HOTEL)') && $('#t-tbody').textContent.includes('AHMED TEST')), 'transport: the transfer is listed with its airport and hotel');
  await go('master');
  const hotelOption = () => $$('.opt-row').find((r) => r.textContent.includes('SMOKE HOTEL'));
  ok(await waitFor(() => /\d+ bookings?/.test(hotelOption()?.textContent || '') && !/vessel/.test(hotelOption().textContent)), 'master data: hotels count bookings, not vessels');
  for (const [page, p] of [['transport', 't'], ['hotels', 'h']]) {
    await go(page);
    await waitFor(() => $(`#${p}-tbody tr`));
    const testRow = () => $$(`#${p}-tbody tr`).find((t) => /AHMED TEST|LATE TEST|STEP \d/.test(t.textContent));
    for (let guard = 0; testRow() && guard < 20; guard += 1) { // the list redraws after each delete: look again
      click(testRow());
      if (!(await waitFor(() => $('[data-act="booking-delete"]')))) break;
      click($('[data-act="booking-delete"]'));
      await waitFor(() => !$('#overlay').classList.contains('open'));
      await sleep(150);
    }
    ok(await waitFor(() => !/AHMED TEST|LATE TEST|STEP \d/.test($(`#${p}-tbody`).textContent)), `${page}: test bookings deleted`);
  }

  /* ======== dashboard ======== */
  await go('dashboard');
  ok($('#d-from') && !$('#dash-year') && $('#d-from').value === $('#f-from').value, 'dashboard uses the same date range');
  ok(await waitFor(() => $$('#opr-cards .opr-card').length > 0) && $$('#chart-vessels .bar').length > 0, 'dashboard: charts and OPR cards render');
  click($('#opr-cards .opr-card'));
  ok(await waitFor(() => modalText().includes('Services summary')), 'dashboard: OPR card opens the combined summary');
  closeModal();
  const keepFrom = $('#d-from').value;
  const keepTo = $('#d-to').value;
  type($('#d-from'), '2001-01-01'); type($('#d-to'), '2001-01-31');
  ok(await waitFor(() => $('#dash-count').textContent === '0' && $('#opr-cards').textContent.includes('No data')), 'dashboard: changing the range reloads its figures');
  ok($('#f-from').value === '2001-01-01', 'dashboard and vessels share one range');
  click($('#d-clear'));
  ok(await waitFor(() => $('#d-from').value === '' && $('#dash-count').textContent !== '0'), '"All dates" clears the range');
  type($('#d-from'), keepFrom); type($('#d-to'), keepTo);
  await waitFor(() => $('#f-from').value === keepFrom);

  /* ======== clean up ======== */
  await go('vessels');
  for (const name of [NAME, '<img', 'SMOKE TODAY', 'BULK A', 'BULK B', 'PORT MOVE']) {
    const row = $$('#tbody tr').find((t) => t.textContent.includes(name));
    if (!row) continue;
    click(row.querySelector('[data-act="del-vessel-row"]')); // the Delete button in the table row
    await waitFor(() => !$$('#tbody tr').some((t) => t.dataset.id === row.dataset.id));
  }
  ok(await waitFor(() => !$$('#tbody tr').some((t) => /UI SMOKE|SMOKE TODAY|<img|BULK|PORT MOVE/.test(t.textContent))), 'test vessels deleted (the list reloads after the dialog closes)');
  await go('master');
  for (const value of ['SMOKE AGENT', 'SMOKE-OPR', 'SMOKE HOTEL', 'SMOKE ALEXANDRIA AIRPORT', 'SMOKE ALEXANDRIA PORT', 'SMOKE SUEZ AGENT', 'SMOKE SUEZ HOTEL']) {
    const row = $$('.opt-row').find((r) => r.textContent.includes(value));
    if (row) { click(row.querySelector('[data-act="del-option"]')); await waitFor(() => !$('#master-grid').textContent.includes(value)); }
  }
  ok(!$('#master-grid').textContent.includes('SMOKE'), 'master data values removed');
  if (ROLE === 'admin') await clearTestRate();
  if (hostileId) {
    const res = await w.fetch(`/api/vessels/${hostileId}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
    ok(res.ok, 'hostile-text vessel deleted');
  }
  finish();

  function finish() {
    ok(jsErrors.length === 0, `no JavaScript errors${jsErrors.length ? ': ' + jsErrors.join('; ') : ''}`);
    console.log(failures ? `\n${failures} FAILED` : '\nALL PASSED');
    process.exit(failures ? 1 : 0);
  }
})().catch((e) => { console.error(e); process.exit(1); });
