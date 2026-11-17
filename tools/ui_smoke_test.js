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
  let stayPosts = 0;          // how many "create hotel stay" requests the page sent
  let holdStay = null;        // {id, until}: hold back the answer for opening that stay
  w.fetch = async (url, opts = {}) => {
    if (url.startsWith('/api/vessels/?')) listCalls += 1;
    if (url === '/api/hotels/' && opts.method === 'POST') stayPosts += 1;
    if (holdStay && url === `/api/hotels/${holdStay.id}/` && (opts.method || 'GET') === 'GET') await holdStay.until;
    if (slowAlertsFor && url.startsWith('/api/vessels/alerts/') && url.includes(slowAlertsFor)) await sleep(600);
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
  const shown = (el) => !!el && !el.hidden && el.style.display !== 'none'; // hidden attribute or a style set by the app
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
      body: JSON.stringify({ name: HOSTILE, arrival_agent: HOSTILE_AGENT, opr: '<i>O</i>', port: 'alexandria', date: localNow() }),
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
    click(row().querySelector('[data-act="summary"]'));
    ok(await waitFor(() => $('#modal h2')?.textContent === HOSTILE), 'summary: title shows the name literally');
    ok(modalText().includes(HOSTILE_AGENT) && modalText().includes('<i>O</i>') && noMarkup($('#modal')), 'summary: agent and OPR literal, no markup');
    closeModal();
    click(row().querySelector('td'));
    ok(await waitFor(() => $('#modal h2')?.textContent === HOSTILE) && modalText().includes(HOSTILE_AGENT) && noMarkup($('#modal')), 'vessel details: texts literal, no markup');
    click($('#modal [data-act="edit-vessel"]'));
    ok(await waitFor(() => $('#vessel-form [name=name]')?.value === HOSTILE), 'vessel form: name input holds the exact text');
    ok($('#vessel-form [name=arrival_agent]').value === HOSTILE_AGENT && $('#vessel-form [name=opr]').value === '<i>O</i>', 'vessel form: agent / OPR kept as exact values');
    if (ROLE === 'admin') {
      type($('#vessel-form [name=port]'), 'suez');
      ok($('#vessel-form [name=arrival_agent]').value === HOSTILE_AGENT && $('#vessel-form [name=opr]').value === '<i>O</i>', 'vessel form: changing the port keeps the chosen values');
    }
    closeModal();

    // Services with markup-like texts: a remark and a crew member.
    const addHostileService = async (type, fill) => {
      click(row().querySelector('td'));
      await waitFor(() => $('#modal [data-act="add-service"]'));
      click($('#modal [data-act="add-service"]'));
      await waitFor(() => $(`#modal [data-act="pick-type"][data-type="${type}"]`));
      click($(`#modal [data-act="pick-type"][data-type="${type}"]`));
      await waitFor(() => $('#svc-form'));
      await fill();
      click($('[data-act="save-service"]'));
      return waitFor(() => $('#modal .svc-card') && !$('#svc-form'));
    };
    ok(await addHostileService('Others / Remarks', () => { type($('#svc-form [name=note]'), '<b>R</b>'); type($('#svc-form [name=cost]'), '10'); }), 'remark with markup-like text saved');
    ok(modalText().includes('<b>R</b>') && noMarkup($('#modal')), 'vessel details: remark shows literally');
    click($('#modal [data-act="edit-service"]'));
    ok(await waitFor(() => $('#svc-form [name=note]')?.value === '<b>R</b>'), 'service form: remark textarea holds the exact text');
    closeModal();
    ok(await addHostileService('Crew Change', async () => {
      click($('#crew-editor [data-act="add-crew"][data-group="onSigners"]'));
      await waitFor(() => $('#crew-editor [data-crew="name"]'));
      type($('#crew-editor [data-crew="name"]'), '<b>R</b> crew');
      ok($('#crew-editor .crew-name').textContent === '<b>R</b> crew' && noMarkup($('#crew-editor')), 'crew editor: typed name shows literally');
    }), 'crew change with markup-like name saved');
    ok(modalText().includes('<b>R</b> crew') && noMarkup($('#modal')), 'vessel details: crew name shows literally');
    closeModal();
    click(row().querySelector('[data-act="summary"]'));
    ok(await waitFor(() => modalText().includes('<b>R</b> crew')) && modalText().includes('<b>R</b>') && noMarkup($('#modal')), 'summary: remark and crew name literal');
    closeModal();

    await go('calculations');
    const calcRows = () => $$('#c-tbody tr').filter((t) => t.textContent.includes(HOSTILE));
    ok(await waitFor(() => calcRows().length > 0), 'calculations: lines of the markup-like vessel are listed');
    ok(calcRows()[0].textContent.includes('<i>O</i>') && noMarkup($('#c-tbody')), 'calculations: vessel name and OPR show literally');
    ok([...$('#c-opr').options].some((o) => o.textContent === '<i>O</i>'), 'calculations: OPR filter lists the markup-like OPR as text');

    await go('master');
    type($('[data-new="agent"]'), 'SMOKE <i>M</i>');
    click($('[data-act="add-option"][data-kind="agent"]'));
    const optRow = () => $$('.opt-row').find((r) => r.querySelector('.val')?.textContent === 'SMOKE <i>M</i>');
    ok(await waitFor(() => optRow()), 'master data: markup-like value is listed literally');
    ok(noMarkup($('#master-grid')) && optRow().querySelector('[data-act="del-option"]').dataset.value === 'SMOKE <i>M</i>', 'master data: no markup, exact value on the Remove button');
    await w.fetch(`/api/options/${optRow().querySelector('[data-act="del-option"]').dataset.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
    await go('vessels');
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
    ok(await waitFor(() => $('#vessel-form [name=arrival_agent]')) && [...$('#vessel-form [name=sailing_agent]').options].some((o) => o.textContent === 'SMOKE SUEZ OWN AGENT'), 'suez user: the Add vessel form offers their own agent');
    closeModal();
    ok([...$('#qa-agent').options].some((o) => o.textContent === 'SMOKE SUEZ OWN AGENT'), 'suez user: quick add offers their own agent');
    await w.fetch(`/api/options/${own.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
    await checkHistory();
    return finish();
  }

  /* ======== layout: sidebar and pages ======== */
  const navItems = $$('#nav .nav-item').filter((a) => a.style.display !== 'none');
  ok($('#sidebar') && navItems.length === (ROLE === 'admin' ? 8 : 7), 'sidebar lists the pages (admins also have History; no Bulk add)');
  const pageOrder = 'vessels,hotels,transport,calculations,dashboard,master,rates' + (ROLE === 'admin' ? ',history' : '');
  ok($$('#nav .nav-item').map((a) => a.dataset.page).join() === pageOrder, 'Calculations sits after Transport; History (admins) last');
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
  ok($$('#tbody tr')[0].children.length === 10 && !$('th[data-sort="total_cost_egp"]') && !/Total Cost/.test($('thead').textContent), 'table has arrival / sailing agent columns and no Total Cost column');
  ok($('th[data-sort="arrival_agent"]')?.textContent.includes('Arrival agent') && $('th[data-sort="sailing_agent"]')?.textContent.includes('Sailing agent'), 'the two agent columns are sortable');

  // The ☰ button: on a wide screen it hides / shows the sidebar (remembered); jsdom counts as wide.
  click($('#menuBtn'));
  ok(w.document.body.classList.contains('nav-collapsed') && w.localStorage.getItem('sheet.navCollapsed') === '1', '☰ hides the sidebar on a wide screen');
  click($('#menuBtn'));
  ok(!w.document.body.classList.contains('nav-collapsed') && w.localStorage.getItem('sheet.navCollapsed') === '0', '☰ shows it again');

  ok(!$('#page-bulk') && !$('[href="#bulk"]'), 'there is no Bulk add page');
  ok(!$('#tbody [data-act="open-vessel"]') && $('#tbody [data-act="summary"]'), 'rows have Summary but no separate Edit button');
  ok(ROLE === 'viewer' ? !$('#tbody [data-act="del-vessel-row"]') : !!$('#tbody [data-act="del-vessel-row"]'), 'rows have a Delete button only for users who can edit');

  /* ---- date range, server-side search and paging ---- */
  const monthStart = localNow().slice(0, 8) + '01';
  ok($('#f-from').value === monthStart && $('#f-to').value.slice(0, 7) === monthStart.slice(0, 7), 'date range defaults to this month');
  ok($('#page-size') && [...$('#page-size').options].map((o) => o.value).join() === '10,25,50,100' && $('#page-size').value === '50', 'rows per page: 10 / 25 / 50 / 100, default 50');
  ok($('#pager').textContent.includes('Showing'), 'pager shows "Showing x–y of n"');
  type($('#search'), 'zzzz-no-match');
  ok($$('#tbody tr').length > 0, 'search waits for a pause before asking the server');
  ok(await waitFor(() => $$('#tbody tr').length === 0 && shown($('#empty'))), 'search with no match shows the empty state (from the server)');
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
    ok(shown($('#portSelect')), 'read-only: sees the port selector');
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
      ok(!shown($(`#${p}-add`)) && /Cost/.test($(`#${p}-head`).textContent) && /Revenue/.test($(`#${p}-head`).textContent), `read-only: ${page} has no Add button but sees cost and revenue`);
      ok(shown($(`#${p}-port`)), `read-only: ${page} has the port selector`);
    }
    await checkTheme();
    await checkDashboard();
    await checkHistory();
    return finish();
  }

  if (ROLE === 'alex') ok($('#portBanner').textContent.includes('Alexandria'), 'port user sees the port banner');
  if (ROLE === 'admin') ok(shown($('#qa-port')) && shown($('#portSelect')), 'admin sees the port selectors');
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
    await go('vessels');
    type($('#portSelect'), 'suez');
    ok(await waitFor(() => $('#qa-port').value === 'suez' && [...$('#qa-agent').options].some((o) => o.textContent === 'SMOKE SUEZ AGENT')), 'quick add follows the header port selector');
    type($('#portSelect'), 'ALL');
    await waitFor(() => $('#portSelect').value === 'ALL');
    await go('master');
    const agentChoices = () => [...$('#vessel-form [name=arrival_agent]').options].map((o) => o.textContent);
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
  ok($('#vessel-form select[name=opr]') && $('#vessel-form select[name=poc]') && $('#vessel-form select[name=arrival_agent]') && $('#vessel-form select[name=sailing_agent]'), 'vessel form uses master-data dropdowns');
  ok($('#vessel-form [name=arrival_agent]').value === '' && $('#vessel-form [name=sailing_agent]').value === '', 'a new vessel starts with no agents');
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
  ok($('#vessel-form [name=arrival_agent]').value === 'SMOKE AGENT' && $('#vessel-form [name=sailing_agent]').value === '', 'quick add set only the arrival agent');
  ok(modalText().includes('Arrival agent') && modalText().includes('Sailing agent'), 'the dialog lists both agents');
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
  ok($('#svc-form select[name=agent]') && $('#svc-form [name=agent]').value === '', 'a new service starts with no agent');
  type($('#svc-form [name=agent]'), 'SMOKE AGENT');
  type($('[name=quantity]'), '40'); type($('[name=revenue]'), '100'); type($('[name=revenueCurrency]'), 'USD'); type($('[name=cost]'), '2000');
  ok($('#preview').textContent.includes('No exchange rate'), 'preview warns when the month has no rate');
  type($('[name=exchangeRate]'), '50');
  ok($('#preview').textContent.includes('5,000.00') && $('#preview').textContent.includes('3,000.00'), 'preview: 100 USD at 50 = 5,000 revenue, 3,000 profit');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('Quantity (tons): 40')), 'Fresh Water saved');
  ok($$('.svc-card').some((c) => c.textContent.includes('Fresh Water') && c.textContent.includes('Agent: SMOKE AGENT')), 'the service card shows its agent');

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
  ok(await waitFor(() => shown($('#bellBadge')) && $('#notifBanner').textContent.includes('SMOKE TODAY')), 'bell badge and banner show vessels due today (alerts load alongside the table)');
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
  // Past vessels missing an agent (seed_demo: SEA BREEZE, Alexandria, yesterday — no sailing agent, Landing without agent).
  if (ROLE !== 'suez') {
    ok(await waitFor(() => /\d+ missing an agent/.test($('#notifBanner').textContent) && $('#notifBanner').textContent.includes('SEA BREEZE')), 'banner shows vessels missing an agent');
    const missRow = $$('#notifBanner .notif-row.missing').find((r) => r.textContent.includes('SEA BREEZE'));
    ok(missRow && missRow.textContent.includes('Sailing') && missRow.textContent.includes('Landing'), 'the row says what is missing');
    click($('#bell'));
    ok($('#notifPanel').textContent.includes('Missing agent') && $('#notifPanel').textContent.includes('SEA BREEZE'), 'bell panel has a Missing agent group');
    click($('#bell'));
    if (ROLE === 'alex') {
      // More than 20 vessels missing an agent: the banner stops at 20 and "+ N more" opens the full list.
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': meta() };
      const extra = [];
      for (let i = 1; i <= 21; i += 1) {
        const res = await w.fetch('/api/vessels/', { method: 'POST', headers, body: JSON.stringify({ name: `SMOKE GAP ${i}`, date: '2019-03-01' }) });
        extra.push((await res.json()).id);
      }
      type($('#qa-name'), 'smoke gap trigger'); type($('#qa-date'), localNow()); click($('#qa-add')); // a save reloads the alerts
      ok(await waitFor(() => $$('#notifBanner .notif-row.missing').length === 20 && /\+ \d+ more/.test($('#notifBanner').textContent)), 'banner caps missing-agent rows at 20 with "+ N more"');
      click($('#notifBanner [data-act="show-alerts-panel"]'));
      ok($('#notifPanel').classList.contains('open') && $$('#notifPanel .notif-item.missing').length >= 22, '"+ N more" opens the bell panel with every vessel missing an agent');
      click($('#bell'));
      for (const id of extra) await w.fetch(`/api/vessels/${id}/`, { method: 'DELETE', headers });
    }
  }

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

  // Markup-like texts in bookings: the vessel picker, a guest and the hotels table show them literally.
  if (hostileId) {
    click($('#h-add'));
    await waitFor(() => $('#bkd-vessel-q'));
    type($('#bkd-vessel-q'), 'SMOKE <i>');
    const hostileButton = () => $$('#bkd-vessel-results [data-act="booking-pick-vessel"]').find((b) => b.dataset.id === String(hostileId));
    ok(await waitFor(() => hostileButton()), 'dialog: vessel search finds the markup-like vessel');
    ok(hostileButton().textContent.includes(HOSTILE) && noMarkup($('#bkd-vessel-results')), 'dialog: vessel picker shows the name literally');
    click(hostileButton());
    ok(await waitFor(() => $('.bkd-vessel')?.textContent.includes(HOSTILE)) && noMarkup($('#modal')), 'dialog: chosen vessel shows literally');
    await waitFor(() => $('#bkd-crew')?.textContent.includes('No crew change') || $('#bkd-crew input')); // crew loaded
    await sleep(100); // let that request finish before the next write (SQLite allows one writer at a time)
    closeModal();
    const res = await w.fetch('/api/hotels/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
      body: JSON.stringify({ vessel: hostileId, hotel: '<b>G</b> hotel', check_in: todayIso, nights: 1, guests: [{ name: '<b>G</b>', rank: '<i>X</i>' }] }),
    });
    const hostileStay = (await res.json()).id;
    await go('vessels'); await go('hotels');
    const hostileRow = () => $(`#h-tbody tr[data-id="${hostileStay}"]`) || $$('#h-tbody tr').find((t) => t.textContent.includes(HOSTILE));
    ok(await waitFor(() => hostileRow()), 'hotels: stay on the markup-like vessel is listed');
    ok(hostileRow().textContent.includes('<B>G</B>') && hostileRow().textContent.includes(HOSTILE) && noMarkup($('#h-tbody')), 'hotels: guest, rank and vessel show literally');
    click(hostileRow());
    ok(await waitFor(() => $('#bkd-guests [data-g-f="name"]')?.value === '<B>G</B>') && noMarkup($('#modal')), 'dialog: guest name kept as the exact value');
    closeModal();
    await w.fetch(`/api/hotels/${hostileStay}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
    await go('vessels'); await go('hotels');
  }

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

  await checkTheme();

  /* ======== dashboard ======== */
  await checkDashboard();

  /* ======== clean up ======== */
  await go('vessels');
  for (const name of [NAME, '<img', 'SMOKE TODAY', 'SMOKE GAP TRIGGER', 'PORT MOVE']) {
    const row = $$('#tbody tr').find((t) => t.textContent.includes(name));
    if (!row) continue;
    click(row.querySelector('[data-act="del-vessel-row"]')); // the Delete button in the table row
    await waitFor(() => !$$('#tbody tr').some((t) => t.dataset.id === row.dataset.id));
  }
  ok(await waitFor(() => !$$('#tbody tr').some((t) => /UI SMOKE|SMOKE TODAY|SMOKE GAP|<img|PORT MOVE/.test(t.textContent))), 'test vessels deleted (the list reloads after the dialog closes)');
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

  await checkHistory();
  finish();

  /** Dark / light switch in the sidebar: flips the page, relabels itself, sets the cookie; works with storage blocked. */
  async function checkTheme() {
    const root = w.document.documentElement;
    const label = () => $('#themeBtn .label').textContent;
    const before = root.dataset.theme || 'light';
    click($('#themeBtn'));
    const after = root.dataset.theme;
    ok(after === (before === 'dark' ? 'light' : 'dark') && label() === (after === 'dark' ? 'Light mode' : 'Dark mode'), 'theme: the switch flips the mode and its label');
    ok(w.document.cookie.includes(`theme=${after}`), 'theme: the choice is kept in a cookie');
    const storage = Object.getOwnPropertyDescriptor(w, 'localStorage');
    Object.defineProperty(w, 'localStorage', { configurable: true, get() { throw new Error('blocked'); } });
    const errorsBefore = jsErrors.length;
    click($('#themeBtn'));
    Object.defineProperty(w, 'localStorage', storage);
    ok(root.dataset.theme === before && w.document.cookie.includes(`theme=${before}`) && jsErrors.length === errorsBefore, 'theme: switching back works with storage blocked');
  }

  /** The Dashboard: OPR charts and cards, jobs per agent, services and money per month, and its filters. */
  async function checkDashboard() {
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
    ok(['#chart-agents', '#chart-months', '#tbl-agents', '#tbl-months', '#tbl-money'].every((s) => $(s).textContent.includes('No data.')), 'dashboard: an empty range shows "No data." in every new panel');
    click($('#d-clear'));
    ok(await waitFor(() => $('#d-from').value === '' && $('#dash-count').textContent !== '0'), '"All dates" clears the range');
    type($('#d-from'), keepFrom); type($('#d-to'), keepTo);
    await waitFor(() => $('#f-from').value === keepFrom);

    // Jobs per agent, services per month and money per month, with the Dashboard's own filters.
    const agentRows = () => $$('#tbl-agents tbody tr:not(.total)');
    const agentHeads = () => $$('#tbl-agents thead th').map((t) => t.textContent);
    ok(await waitFor(() => agentRows().some((r) => r.textContent.includes('DELTA SHIPPING'))), 'dashboard: jobs per agent lists DELTA SHIPPING');
    ok(agentRows().at(-1).textContent.includes('(no agent)') && agentRows().at(-1).classList.contains('no-agent'), 'dashboard: "(no agent)" row comes last');
    ok(agentHeads().includes('Arrivals') && agentHeads().includes('Sailings') && agentHeads().at(-1) === 'Total', 'dashboard: agents table has Arrivals, Sailings and Total');
    ok($$('#chart-agents .hbar').length === agentRows().length && $$('#chart-months .stack-col').length > 0, 'dashboard: agent bars and month columns are drawn');
    ok($$('#tbl-months tbody tr').at(-1).classList.contains('total') && /[A-Z][a-z]{2} \d{4}/.test($('#tbl-months thead').textContent), 'dashboard: services per month has month columns and a Total row');
    ok($$('#tbl-money tbody tr').map((r) => r.firstElementChild.textContent).join() === 'Cost,Revenue,Profit', 'dashboard: money per month has Cost, Revenue and Profit rows');
    ok(shown($('#d-port')) === (ROLE !== 'alex'), 'dashboard: own port selector only for users who see every port');
    type($('#d-service'), 'Fresh Water');
    ok(await waitFor(() => !agentHeads().includes('Arrivals') && !agentHeads().includes('Sailings')), 'dashboard: a service filter hides Arrivals and Sailings');
    type($('#d-service'), '');
    ok(await waitFor(() => agentHeads().includes('Arrivals')), 'dashboard: clearing the service filter brings them back');
    type($('#d-opr'), 'MSK');
    ok(await waitFor(() => $$('#opr-cards .opr-card').length === 1 && $('#opr-cards').textContent.includes('MSK')), 'dashboard: the OPR filter narrows the OPR cards');
    type($('#d-opr'), '');
    type($('#d-agent'), 'DELTA SHIPPING');
    ok(await waitFor(() => agentRows().length === 1 && agentRows()[0].textContent.includes('DELTA SHIPPING')), 'dashboard: the agent filter leaves that agent only');
    click(agentRows()[0]);
    ok(await waitFor(() => modalText().includes('MSC AURORA') && modalText().includes('Arrival')), "dashboard: an agent row opens that agent's jobs");
    click($$('#modal [data-act="open-vessel"]').find((b) => b.textContent.includes('MSC AURORA')));
    ok(await waitFor(() => $('#modal h2')?.textContent.includes('MSC AURORA')), 'dashboard: a job opens its vessel');
    closeModal();
    // NILE AGENCY did a service on MSC AURORA only; SEA BREEZE (also MSK) must not be in the OPR summary then.
    type($('#d-agent'), 'NILE AGENCY');
    const msk = () => $$('#opr-cards .opr-card').find((c) => c.textContent.includes('MSK'));
    ok(await waitFor(() => agentRows().length === 1 && agentRows()[0].textContent.includes('NILE') && msk()), 'dashboard: NILE AGENCY filter applied');
    click(msk());
    ok(await waitFor(() => modalText().includes('Services summary') && modalText().includes('MSC AURORA')) && !modalText().includes('SEA BREEZE'), 'dashboard: the OPR summary follows the agent filter');
    closeModal();
    type($('#d-agent'), '');
    ok(await waitFor(() => agentRows().length > 1), 'dashboard: clearing the agent filter shows every agent');
    if (hostileId) {
      const row = () => agentRows().find((r) => r.textContent.includes(HOSTILE_AGENT));
      ok(await waitFor(() => row()) && noMarkup($('#tbl-agents')) && noMarkup($('#chart-agents')) && $('#d-agent').textContent.includes(HOSTILE_AGENT), 'dashboard: markup-like agent shows literally in table, chart and filter');
      click(row());
      ok(await waitFor(() => modalText().includes(HOSTILE)) && modalText().includes(HOSTILE_AGENT) && noMarkup($('#modal')), 'dashboard: jobs dialog shows names literally');
      closeModal();
    }
    if (ROLE === 'admin') {
      const allPorts = $('#dash-count').textContent;
      type($('#d-port'), 'suez');
      ok(await waitFor(() => $('#portSelect').value === 'suez' && $('#dash-count').textContent !== allPorts), 'dashboard: its port selector moves the shared port');
      type($('#d-port'), 'ALL');
      await waitFor(() => $('#portSelect').value === 'ALL' && $('#dash-count').textContent === allPorts);
    }
  }

  /** The change history: admins read it on the History page; everyone else gets no page and a 403. */
  async function checkHistory() {
    const historyStatus = (await w.fetch('/api/history/')).status;
    if (ROLE === 'admin') {
      ok(historyStatus === 200, 'history: admin may read the change history');
      await go('history');
      const historyRows = () => $$('#hi-tbody tr');
      ok(await waitFor(() => historyRows().length > 0), 'history: the page lists changes');
      ok(historyRows().some((r) => r.textContent.includes('admin') && r.textContent.includes('Deleted Vessel')), "history: this run's own deletes are listed");
      ok(historyRows().some((r) => r.textContent.includes(HOSTILE)) && noMarkup($('#hi-tbody')), 'history: a markup-like vessel name shows literally');
      ok([...$('#hi-pager #hi-page-size').options].map((o) => o.value).join() === '10,25,50,100', 'history: rows per page 10/25/50/100');
      type($('#hi-type'), 'exchangerate');
      ok(await waitFor(() => historyRows().length > 0 && historyRows().every((r) => r.textContent.includes('Exchange rate'))), 'history: filter by what changed');
    } else {
      ok(historyStatus === 403, `history: ${ROLE} gets 403 from the history API`);
      ok(!$('#nav [data-page="history"]') && !$('#page-history'), `history: ${ROLE} has no History page`);
      w.location.hash = 'history';
      ok(await waitFor(() => $('#pageTitle').textContent === 'Vessels'), `history: ${ROLE} opening #history lands on Vessels`);
    }
  }

  function finish() {
    ok(jsErrors.length === 0, `no JavaScript errors${jsErrors.length ? ': ' + jsErrors.join('; ') : ''}`);
    console.log(failures ? `\n${failures} FAILED` : '\nALL PASSED');
    process.exit(failures ? 1 : 0);
  }
})().catch((e) => { console.error(e); process.exit(1); });
