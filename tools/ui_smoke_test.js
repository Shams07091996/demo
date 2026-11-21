// End-to-end smoke test: loads the real page in jsdom, logs in over HTTP and clicks through the app.
//
//   python manage.py seed_demo --password "some-long-password" --two-step-key <32 base32 characters>
//   python manage.py runserver 8765          (in another terminal)
//   UI_TEST_PASSWORD="some-long-password" UI_TEST_TOTP_KEY=<the same key> node ui_smoke_test.js [alex|admin|viewer]
//
// It creates and removes its own vessels, master-data values and a January-2020 exchange rate.
const crypto = require('crypto');
const path = require('path');
const { buildSync } = require('esbuild');
const { JSDOM } = require('jsdom');

const BASE = process.env.UI_TEST_URL || 'http://localhost:8765';
const PASSWORD = process.env.UI_TEST_PASSWORD;
const ROLE = process.argv[2] || 'alex';
if (!PASSWORD) { console.error('Set UI_TEST_PASSWORD to the password given to seed_demo.'); process.exit(2); }
const TOTP_KEY = process.env.UI_TEST_TOTP_KEY;
if (!TOTP_KEY) { console.error('Set UI_TEST_TOTP_KEY to the key given to seed_demo --two-step-key.'); process.exit(2); }

// The six-digit code Authenticator would show (RFC 6238: HMAC-SHA1, 30-second steps).
function totp(base32) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of base32.replace(/[\s=]/g, '').toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const mac = crypto.createHmac('sha1', key).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0');
}

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
  // Two-step login: nothing works on the password alone; the code page takes the current code.
  res = await fetch(`${BASE}/api/vessels/`, { headers: { Cookie: cookies() } });
  ok(res.status === 401, 'two-step: the API answers 401 after the password alone');
  res = await fetch(`${BASE}/`, { headers: { Cookie: cookies() }, redirect: 'manual' });
  ok(res.status === 302 && res.headers.get('location') === '/login/code/', 'two-step: the page sends you to Enter code');
  res = await fetch(`${BASE}/login/code/`, { headers: { Cookie: cookies() } }); remember(res);
  ok((await res.text()).includes('Remember this computer for 30 days'), 'two-step: Enter code page shown');
  res = await fetch(`${BASE}/login/code/`, {
    method: 'POST', redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Cookie: cookies(), Referer: `${BASE}/login/code/` },
    body: new URLSearchParams({ code: totp(TOTP_KEY), csrfmiddlewaretoken: jar.csrftoken }),
  });
  remember(res);
  if (res.status !== 302) throw new Error(`Code step failed (HTTP ${res.status}) - wrong UI_TEST_TOTP_KEY, or the same code used twice within 30 seconds?`);
  ok(!jar.remember, 'two-step: unticked box remembers nothing');
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
    const { prices } = await (await w.fetch('/api/disposal-prices/')).json();
    for (const p of prices.filter((x) => x.month === '2020-01')) await w.fetch(`/api/disposal-prices/${p.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } });
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
    // List values must come from Master data, so the markup-like agent / OPR are added there first.
    for (const [kind, value] of [['agent', HOSTILE_AGENT], ['opr', '<i>O</i>'], ['hotel', '<b>G</b> hotel']]) {
      const added = await w.fetch('/api/options/', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
        body: JSON.stringify({ kind, value, port: 'alexandria' }),
      });
      ok(added.status === 201 || added.status === 200, `markup-like ${kind} added to Master data (HTTP ${added.status})`);
    }
    const res = await w.fetch('/api/vessels/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
      body: JSON.stringify({ name: HOSTILE, arrival_agent: HOSTILE_AGENT, opr: '<i>O</i>', poc: 'ALY', port: 'alexandria', date: localNow() }),
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
    // Port closures: seed_demo has an Alexandria and a Port Said closure; a Suez user sees neither.
    await go('closures');
    click($('#pc-clear'));
    ok(await waitFor(() => shown($('#pc-empty'))) && !$('#pc-tbody tr') && !!$('[data-act="closure-new"]'), "suez user: no other port's closures, and + Add closure");
    await checkHistory();
    return finish();
  }

  /* ======== layout: sidebar and pages ======== */
  const navItems = $$('#nav .nav-item').filter((a) => a.style.display !== 'none');
  ok($('#sidebar') && navItems.length === (ROLE === 'admin' ? 10 : 9), 'sidebar lists the pages (admins also have History; no Bulk add)');
  const pageOrder = 'vessels,hotels,transport,closures,disposal,calculations,dashboard,master,rates' + (ROLE === 'admin' ? ',history' : '');
  ok($$('#nav .nav-item').map((a) => a.dataset.page).join() === pageOrder, 'Port closures and Calculations sit after Transport; History (admins) last');
  ok(!$('.tabs') && $('.sidebar'), 'navigation is a sidebar, not a tab bar');
  ok(!$('#page-vessels').hidden && $('#pageTitle').textContent === 'Vessels', 'starts on the Vessels page');
  for (const [page, title] of [['hotels', 'Hotels'], ['transport', 'Transport'], ['closures', 'Port closures'], ['disposal', 'Garbage & Sludge'], ['calculations', 'Calculations'], ['dashboard', 'Dashboard'], ['master', 'Master data'], ['rates', 'Exchange rates'], ['vessels', 'Vessels']]) {
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
    ok($('#addVesselBtn').hidden && $('#quickAdd').hidden, 'read-only: add controls hidden');
    ok(shown($('#portSelect')), 'read-only: sees the port selector');
    click($$('#tbody tr')[0]);
    await waitFor(() => $('#modal [data-act="summary"]')); // the dialog opens once the vessel is at hand
    ok(!$('[data-act="add-service"]') && !$('[data-act="del-vessel"]') && !$('[data-act="edit-vessel"]'), 'read-only: no edit buttons in the dialog');
    ok(!$('[data-act="receipt"]'), 'read-only: no Receipt button');
    click($('#modal [data-act="summary"]'));
    ok(await waitFor(() => modalText().includes('Port call') && modalText().includes('Services on this vessel')), 'read-only: summary of services opens');
    closeModal();
    await go('master');
    ok($$('#master-grid .panel').length === 8 && !$('[data-act="add-option"]') && !$('[data-act="del-option"]'), 'read-only: master data is view-only');
    await go('rates');
    ok(!$('#rate-form') && !$('#price-form'), 'read-only: cannot edit exchange rates or Garbage & Sludge prices');
    ok(await waitFor(() => $('#prices-table') && $('#prices-panel').textContent.includes('Alexandria')), 'read-only: Garbage & Sludge prices are listed');
    await go('disposal');
    ok(await waitFor(() => $$('#g-tbody tr').some((t) => t.textContent.includes('MSC AURORA'))), 'read-only: the Garbage & Sludge page lists vessels');
    ok(!$('#g-tbody [data-qty]') && !$('#g-tbody [data-act="disposal-hide"]'), 'read-only: no quantity boxes or Hide buttons');
    for (const [page, p] of [['hotels', 'h'], ['transport', 't']]) {
      await go(page);
      ok(await waitFor(() => $(`#${p}-head`).textContent.includes('Vessel')), `read-only: ${page} list renders`);
      ok(!shown($(`#${p}-add`)) && /Cost/.test($(`#${p}-head`).textContent) && /Revenue/.test($(`#${p}-head`).textContent), `read-only: ${page} has no Add button but sees cost and revenue`);
      ok(shown($(`#${p}-port`)), `read-only: ${page} has the port selector`);
    }
    // Port closures: every port, nothing to add, edit or remove (seed_demo: Alexandria WEATHER, Port Said FOG open).
    await go('closures');
    click($('#pc-clear'));
    const vClosure = (text) => $$('#pc-tbody tr').find((t) => t.textContent.includes(text));
    ok(await waitFor(() => vClosure('Strong wind') && vClosure('Still closed')?.textContent.includes('Port Said')) && shown($('#pc-port')), 'read-only: closures of every port, with a port filter');
    ok(!$('[data-act="closure-new"]') && !$('#pc-tbody [data-act="closure-del"]') && !$('#pc-tbody tr.clickable'), 'read-only: closures cannot be added, edited or removed');
    await go('vessels');
    ok(await waitFor(() => /\d+ missing details/.test($('#notifBanner').textContent) && $('#notifBanner').textContent.includes('SEA BREEZE')), 'read-only: banner shows vessels missing details');
    checkIcons();
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
  ok($$('#master-grid .panel h3').map((h) => h.textContent).join() === 'OPR,POC,Agent,Hotel,Airport,Port,Delay reason,Closure reason', 'master data has OPR, POC, Agent, Hotel, Airport, Port, Delay reason and Closure reason lists');
  ok($$('#master-grid details.master-list').every((d) => !d.open), 'master data: every list starts folded');
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
    ok($$('select[data-new-port]').length === 8 && portChoices($('select[data-new-port="agent"]')) === ',alexandria,portsaid,damietta,suez', 'admin: every list has a port choice (All ports + each port)');
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
    const moved = optionRow('SMOKE SUEZ AGENT').querySelector('select[data-option-port]');
    type(moved, '');
    // The page is drawn again from the server's answer: wait for the new select, not the one just changed.
    ok(await waitFor(() => {
      const select = optionRow('SMOKE SUEZ AGENT')?.querySelector('select[data-option-port]');
      return select && select !== moved && select.value === '';
    }), 'admin: moving a value to All ports saves');
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
  type($('#qa-opr'), 'MSK'); type($('#qa-poc'), 'ALY'); // both required for a new vessel
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
  type($('#vessel-form [name=date]'), '2020-01-20');
  if (ROLE === 'admin') {
    // On All ports nothing is assumed: the admin chooses the port.
    ok($('#vessel-form [name=port]').value === '', 'admin on All ports: the new vessel has no port yet');
    click($('[data-act="save-vessel"]'));
    ok(await waitFor(() => /Choose a port/.test($('#modal .error')?.textContent || '')), 'admin: a new vessel without a port is refused');
    type($('#vessel-form [name=port]'), 'alexandria');
  }
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /Choose an OPR/.test($('#modal .error')?.textContent || '')), 'a new vessel without an OPR is refused');
  type($('#vessel-form [name=opr]'), 'MSK');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /Choose a POC/.test($('#modal .error')?.textContent || '')), 'a new vessel without a POC is refused');
  type($('#vessel-form [name=poc]'), 'ALY');
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
    type($('#vessel-form [name=opr]'), 'MSK'); type($('#vessel-form [name=poc]'), 'ALY');
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
  // Berthed 2h30 after arrival: the delay reason shows and is required.
  ok(shown($('#delay-row')) && [...$('#vessel-form [name=delay_reason]').options].some((o) => o.value === 'PORT CLOSED'), 'berthing more than 2 hours after arrival shows the delay reason (from Master data)');
  type($('[name=berthing_at]'), '2020-01-15T08:00');
  ok(!shown($('#delay-row')), 'exactly 2 hours: no delay reason');
  type($('[name=berthing_at]'), '2020-01-15T08:30');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /Choose a delay reason/.test($('#modal .error')?.textContent || '')), 'a delayed vessel without a reason is refused');
  type($('#vessel-form [name=delay_reason]'), 'PORT CLOSED');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => modalText().includes('15.01.2020 08:30') && modalText().includes('SMOKE AGENT')), 'times and agent saved and shown in the Port call block');
  ok(modalText().includes('Delay reason') && modalText().includes('PORT CLOSED'), 'the delay reason is shown with the times');
  ok(modalText().includes('9h 30m') && modalText().includes('6h') && modalText().includes('12h'), 'durations: 9h 30m at berth, 6h operations, 12h in port');
  ok($('#modal .status-chip')?.textContent === 'Sailed', 'status chip shows "Sailed"');
  closeModal();
  ok(rowFor(NAME).querySelector('.status-chip')?.textContent === 'Sailed', 'status chip is also in the table');

  /* ======== edit conflicts: a save over someone else's newer save is refused, nothing is lost ======== */
  const jsonHeaders = () => ({ 'Content-Type': 'application/json', 'X-CSRFToken': meta() });
  const VESSEL_KEYS = ['name', 'opr', 'poc', 'port', 'date', 'arrival_agent', 'sailing_agent', 'delay_reason', 'summary',
    'arrival_at', 'berthing_at', 'ops_start_at', 'ops_end_at', 'sailing_at', 'version'];
  const otherVesselSave = async (id, changes) => {
    const current = await (await w.fetch(`/api/vessels/${id}/`)).json();
    const body = Object.fromEntries(VESSEL_KEYS.map((k) => [k, current[k] ?? '']));
    return (await w.fetch(`/api/vessels/${id}/`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify({ ...body, ...changes }) })).status;
  };
  if (ROLE !== 'viewer') {
    const id = Number(rowFor(NAME).dataset.id);
    const sumInput = () => $('#vessel-form [data-sum]');
    await openRow(NAME);
    click($('#modal [data-act="edit-vessel"]'));
    await waitFor(() => $('#vessel-form'));
    ok(await otherVesselSave(id, { sailing_agent: 'SMOKE AGENT' }) === 200, 'conflict: another save made meanwhile');
    type(sumInput(), 'SMOKE MINE');
    click($('[data-act="save-vessel"]'));
    ok(await waitFor(() => $('#conflict-panel')), 'conflict: the save is refused with a warning');
    const panel = () => $('#conflict-panel')?.textContent || '';
    ok(panel().includes('changed this vessel') && panel().includes('in another window') && panel().includes('Sailing agent'), 'conflict: says who (same person: another window) and which fields');
    ok(panel().includes('Nothing of yours was saved') && $('#status-text').textContent === 'Not saved' && !$('#modal .error'), 'conflict: "Not saved", no generic error');
    ok(sumInput().value === 'SMOKE MINE', 'conflict: what was typed stays in the form');
    const onServer = async () => (await (await w.fetch(`/api/vessels/${id}/`)).json());
    ok(!Object.values((await onServer()).summary || {}).includes('SMOKE MINE'), 'conflict: nothing was saved');
    click($('[data-act="conflict-force"]'));
    ok(await waitFor(() => !$('#vessel-form') && $('#modal h2')?.textContent.includes(NAME)), 'conflict: Save mine anyway saves');
    const saved = await onServer();
    ok(Object.values(saved.summary || {}).includes('SMOKE MINE') && saved.sailing_agent === '', 'conflict: what is in the form is saved over theirs');
    click($('#modal [data-act="edit-vessel"]'));
    await waitFor(() => $('#vessel-form'));
    ok(await otherVesselSave(id, { sailing_agent: 'SMOKE AGENT' }) === 200, 'conflict: another save again');
    type(sumInput(), 'SMOKE DROPPED');
    click($('[data-act="save-vessel"]'));
    ok(await waitFor(() => $('#conflict-panel')), 'conflict: warned again');
    click($('[data-act="conflict-reload"]'));
    ok(await waitFor(() => $('#vessel-form') && !$('#conflict-panel') && $('#vessel-form [name=sailing_agent]').value === 'SMOKE AGENT'), 'conflict: Show their version reloads the form with the saved record');
    ok(sumInput().value === 'SMOKE MINE', 'conflict: what was typed is dropped on Show their version');
    closeModal();
  }

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

  /* ======== Master receipt ======== */
  ok($$('.svc-card').every((c) => c.querySelector('[data-act="receipt"]')), 'receipt: every service card has a Receipt button');
  click($$('.svc-card').find((c) => c.textContent.includes('Fresh Water')).querySelector('[data-act="receipt"]'));
  ok(await waitFor(() => $('#receipt-form [name=services]')?.value === 'Fresh Water with cost $100'), 'receipt: the services line is pre-filled from the revenue');
  ok($('#receipt-form [name=vessel]').value === NAME && $('#receipt-form [name=port]').value !== '' && /^\d\d\/\d\d\/\d{4}$/.test($('#receipt-form [name=date]').value), 'receipt: port, date and vessel are pre-filled');
  type($('#receipt-form [name=services]'), '   ');
  click($('[data-act="receipt-download"]'));
  ok(await waitFor(() => /Write the services\./.test($('#modal .error')?.textContent || '')), 'receipt: an empty services box is refused');
  click($('[data-act="back"]'));
  ok(await waitFor(() => $('#modal .svc-card') && !$('#receipt-form')), 'receipt: Back returns to the vessel');

  /* ======== Garbage & Sludge page (January 2020 has no price at first) ======== */
  closeModal();
  await go('disposal');
  type($('#g-from'), '2020-01-01'); type($('#g-to'), '2020-01-31');
  await waitFor(() => false, 900); // the range applies after a short pause; let it load before typing quantities
  const gRow = () => $$('#g-tbody tr').find((t) => t.textContent.includes(NAME));
  ok(await waitFor(() => gRow()), 'garbage & sludge: the vessel is on the page');
  type(gRow().querySelector('[data-qty=garbage]'), '5');
  // Tab on to sludge and start typing while garbage saves: the save must not wipe the box being typed in.
  const sludgeBox = gRow().querySelector('[data-qty=sludge]');
  sludgeBox.focus(); sludgeBox.value = '3';
  ok(await waitFor(() => gRow()?.querySelector('[data-qty=garbage]')?.value === '5' && gRow().textContent.includes('No price for this port and month')),
    'garbage & sludge: a quantity saves on its own; the missing price is flagged');
  await waitFor(() => false, 600); // let the totals reload too
  ok(gRow().querySelector('[data-qty=sludge]') === sludgeBox && sludgeBox.value === '3' && w.document.activeElement === sludgeBox,
    'garbage & sludge: typing in the next box survives the save');
  type(sludgeBox, '');
  sludgeBox.blur();
  if (ROLE === 'admin') {
    await go('rates');
    const pf = (name) => $(`#price-form [name="${name}"]`);
    type(pf('month'), '2020-01'); type(pf('port'), 'suez'); // the admin's smoke vessel is in Suez by now
    const blocks = { 'garbage.revenue': ['3', '250', 'USD', '60'], 'garbage.cost': ['3', '5200', 'EGP', '1500'], 'sludge.revenue': ['25', '875', 'USD', '30'], 'sludge.cost': ['25', '11000', 'EGP', '400'] };
    for (const [key, values] of Object.entries(blocks)) ['min_qty', 'min', 'currency', 'extra'].forEach((name, i) => type(pf(`${key}.${name}`), values[i]));
    click($('[data-act="save-price"]'));
    ok(await waitFor(() => $('#prices-table')?.textContent.includes('01.2020') && $('#prices-table').textContent.includes('3 m³ min · USD 250.00 + 60.00 / m³')), 'garbage & sludge: admin saves a month and port price');
    type(pf('month'), '2020-02'); type(pf('garbage.revenue.min'), '');
    click($('[data-act="copy-price"]'));
    ok(pf('garbage.revenue.min').value === '250' && pf('sludge.cost.extra').value === '400', 'garbage & sludge: Copy from last month fills the form');
    await go('disposal');
    // 5 m³: revenue 250 + 2 × 60 = USD 370; January 2020 has no rate, so the EGP side is left blank and flagged
    ok(await waitFor(() => gRow()?.textContent.includes('USD 370.00') && gRow().textContent.includes('No exchange rate')), 'garbage & sludge: the price applies, in USD and EGP');
    await go('calculations');
    type($('#c-from'), '2020-01-01'); type($('#c-to'), '2020-01-31');
    const gLine = () => $$('#c-tbody tr').find((t) => t.textContent.includes('Garbage · 5 m³'));
    ok(await waitFor(() => gLine()?.textContent.includes('USD 370.00 × 1 (no rate) = 370.00')), 'calculations: the garbage line shows its working');
    await go('disposal');
  }
  type($('#g-show'), 'with');
  ok(await waitFor(() => gRow()), 'garbage & sludge: "With garbage or sludge" lists it');
  type($('#g-show'), 'none');
  ok(await waitFor(() => !gRow()), 'garbage & sludge: "Not entered yet" leaves it out');
  type($('#g-show'), 'all');
  await waitFor(() => gRow());
  click(gRow().querySelector('[data-act="disposal-hide"]'));
  ok(await waitFor(() => !gRow()), 'garbage & sludge: Hide takes the vessel off the page');
  type($('#g-show'), 'hidden');
  ok(await waitFor(() => gRow()?.querySelector('[data-act="disposal-show"]')), 'garbage & sludge: hidden vessels are listed with Bring back');
  click(gRow().querySelector('[data-act="disposal-show"]'));
  ok(await waitFor(() => !gRow()), 'garbage & sludge: Bring back');
  type($('#g-show'), 'all');
  ok(await waitFor(() => gRow()?.querySelector('[data-qty=garbage]')?.value === ''), 'garbage & sludge: back without quantities (hiding cleared them)');
  await go('vessels');
  await openRow(NAME);

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
  // Saved: each card has Needs hotel; on-signers have Broken visa and a LOG link (off-signers neither).
  click($$('.svc-card').find((c) => c.textContent.includes('Crew Change')).querySelector('[data-act="edit-service"]'));
  ok(await waitFor(() => $('.crew-card[data-group="onSigners"] [data-act="crew-log"]')), 'crew change: a saved on-signer has a LOG link');
  const onCardSaved = $('.crew-card[data-group="onSigners"]');
  const offCardSaved = $('.crew-card[data-group="offSigners"]');
  ok(onCardSaved.querySelector('[data-crew="needsHotel"]') && onCardSaved.querySelector('[data-crew="visa.cost"]') && offCardSaved.querySelector('[data-crew="needsHotel"]') && !offCardSaved.querySelector('[data-crew="visa.cost"]') && !offCardSaved.querySelector('[data-act="crew-log"]'), 'crew change: Needs hotel on every card, Broken visa and LOG on on-signers only');
  click($('[data-act="back"]'));
  await waitFor(() => $$('.svc-card').length > 0);

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
  type($('#qa-opr'), 'MSK'); type($('#qa-poc'), 'ALY');
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
  // Past vessels missing details (seed_demo: SEA BREEZE, Alexandria, yesterday — no times, no sailing agent, Landing
  // without agent).
  if (ROLE !== 'suez') {
    ok(await waitFor(() => /\d+ missing details/.test($('#notifBanner').textContent) && $('#notifBanner').textContent.includes('SEA BREEZE')), 'banner shows vessels missing details');
    const missRow = $$('#notifBanner .notif-row.missing').find((r) => r.textContent.includes('SEA BREEZE'));
    ok(missRow && ['Arrived', 'Berthed', 'Sailed', 'Sailing agent', 'Landing agent'].every((x) => missRow.textContent.includes(x)) && !missRow.textContent.includes('Arrival agent'), 'the row says what is missing (times and agents)');
    click($('#bell'));
    ok($('#notifPanel').textContent.includes('Missing details') && $('#notifPanel').textContent.includes('SEA BREEZE'), 'bell panel has a Missing details group');
    click($('#bell'));
    // seed_demo: Ali Sayed (MSC AURORA, Alexandria, today) lands 3 days before the vessel.
    const earlyRow = () => $$('#notifBanner .notif-row.early').find((r) => r.textContent.includes('MSC AURORA'));
    ok(await waitFor(() => earlyRow()?.textContent.includes('Ali Sayed') && /early arrival/.test($('#notifBanner').textContent)), 'banner shows an Early arrival on-signer');
    click($('#bell'));
    ok($('#notifPanel').textContent.includes('Early arrival') && $('#notifPanel').textContent.includes('Ali Sayed'), 'bell panel has an Early arrival group');
    click($('#bell'));
    // The LOG letter of a seeded on-signer: a PDF for those who can edit Alexandria, refused for read-only users.
    const early = (await (await w.fetch('/api/vessels/alerts/')).json()).early.find((e) => e.name === 'MSC AURORA');
    const aurora = await (await w.fetch(`/api/vessels/${early.id}/`)).json();
    const crewService = aurora.services.find((s) => s.type === 'Crew Change');
    const logResponse = await w.fetch(`/api/services/${crewService.id}/log/${crewService.data.onSigners[0].uid}/`);
    if (ROLE === 'viewer') ok(logResponse.status === 403, 'LOG: read-only users cannot make it');
    else ok(logResponse.status === 200 && logResponse.headers.get('Content-Type') === 'application/pdf', 'LOG: the on-signer\'s letter downloads as a PDF');
    const receiptResponse = await w.fetch(`/api/services/${crewService.id}/receipt/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
      body: JSON.stringify({ port: 'Alexandria', date: '20/11/2026', vessel: 'MSC AURORA', services: 'Crew change with cost $50' }),
    });
    if (ROLE === 'viewer') ok(receiptResponse.status === 403, 'receipt: read-only users cannot make it');
    else ok(receiptResponse.status === 200 && receiptResponse.headers.get('Content-Type') === 'application/pdf', 'receipt: downloads as a PDF');
    if (ROLE === 'alex') {
      // More than 20 vessels missing details: the banner stops at 20 and "+ N more" opens the full list.
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': meta() };
      const extra = [];
      for (let i = 1; i <= 21; i += 1) {
        const res = await w.fetch('/api/vessels/', { method: 'POST', headers, body: JSON.stringify({ name: `SMOKE GAP ${i}`, opr: 'MSK', poc: 'ALY', date: '2019-03-01' }) });
        extra.push((await res.json()).id);
      }
      type($('#qa-name'), 'smoke gap trigger'); type($('#qa-date'), localNow()); click($('#qa-add')); // a save reloads the alerts
      ok(await waitFor(() => $$('#notifBanner .notif-row.missing').length === 20 && /\+ \d+ more/.test($('#notifBanner').textContent)), 'banner caps missing-details rows at 20 with "+ N more"');
      click($('#notifBanner [data-act="show-alerts-panel"]'));
      ok($('#notifPanel').classList.contains('open') && $$('#notifPanel .notif-item.missing').length >= 22, '"+ N more" opens the bell panel with every vessel missing details');
      click($('#bell'));
      for (const id of extra) await w.fetch(`/api/vessels/${id}/`, { method: 'DELETE', headers });
    }
  }

  /* ======== port closures (seed_demo: Alexandria WEATHER yesterday 06:00-14:00, Port Said FOG still closed) ======== */
  await go('closures');
  click($('#pc-clear'));
  const closureRow = (text) => $$('#pc-tbody tr').find((t) => t.textContent.includes(text));
  ok(await waitFor(() => closureRow('Strong wind')), 'closures: the Alexandria closure is listed');
  ok(closureRow('Strong wind').textContent.includes('8.0') && closureRow('Strong wind').textContent.includes('WEATHER'), 'closures: hours and reason shown');
  if (ROLE === 'alex') ok(!closureRow('Still closed') && !/Port/.test($('#pc-head').textContent), 'port user: only their own port, no Port column');
  else ok(closureRow('Still closed')?.textContent.includes('Port Said') && shown($('#pc-port')), 'admin / read-only: every port, with a port filter');
  if (ROLE === 'viewer') {
    ok(!$('[data-act="closure-new"]') && !$('#pc-tbody [data-act="closure-del"]') && !$('#pc-tbody tr.clickable'), 'read-only: closures cannot be added, edited or removed');
  } else {
    click($('[data-act="closure-new"]'));
    ok(await waitFor(() => $('#closure-form')), 'closures: + Add closure opens the dialog');
    ok(ROLE === 'admin' ? !!$('#closure-form [name=port]') : !$('#closure-form [name=port]'), 'closures: only admins choose the port');
    ok([...$('#closure-form [name=reason]').options].some((o) => o.value === 'FOG'), 'closures: reasons come from the Closure reason list');
    type($('#closure-form [name=start_at]'), '2020-02-01T06:00');
    type($('#closure-form [name=end_at]'), '2020-02-01T05:00');
    type($('#closure-form [name=reason]'), 'FOG');
    click($('[data-act="closure-save"]'));
    ok(await waitFor(() => /Reopened cannot be before closed from/.test($('#modal .error')?.textContent || '')), 'closures: reopened before closed is refused');
    type($('#closure-form [name=end_at]'), '2020-02-01T09:30');
    click($('[data-act="closure-save"]'));
    ok(await waitFor(() => !$('#overlay').classList.contains('open') && closureRow('01.02.2020 06:00')?.textContent.includes('3.5')), 'closures: saved and listed with its hours');
    click(closureRow('01.02.2020 06:00').querySelector('td'));
    ok(await waitFor(() => $('#closure-form [name=start_at]')?.value === '2020-02-01T06:00'), 'closures: a row opens its closure');
    const listed = (await (await w.fetch('/api/closures/?from=2020-02-01&to=2020-02-01')).json()).closures.find((c) => c.start_at === '2020-02-01T06:00');
    const other = { port: listed.port, start_at: listed.start_at, end_at: listed.end_at, reason: listed.reason, notes: 'THEIR NOTE', version: listed.version };
    ok((await w.fetch(`/api/closures/${listed.id}/`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify(other) })).status === 200, 'closures: another save made meanwhile');
    type($('#closure-form [name=notes]'), 'SMOKE CLOSURE');
    click($('[data-act="closure-save"]'));
    ok(await waitFor(() => ($('#conflict-panel')?.textContent || '').includes('changed this port closure')) && $('#conflict-panel').textContent.includes('Notes'), 'closures: a save over a newer one is warned about');
    click($('[data-act="conflict-force"]'));
    ok(await waitFor(() => closureRow('SMOKE CLOSURE')), 'closures: edited (Save mine anyway)');
    click(closureRow('SMOKE CLOSURE').querySelector('[data-act="closure-del"]'));
    ok(await waitFor(() => !closureRow('SMOKE CLOSURE')), 'closures: removed from its row');
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
  if (ROLE !== 'suez') {
    ok(await waitFor(() => $$('#h-tbody tr').some((t) => t.textContent.includes('AHMED TEST') && t.textContent.includes('To complete'))), 'hotels: the crew change made a draft stay tagged To complete');
  }
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
  // AHMED TEST also has the automatic draft stay from the seeded crew change ("To complete"): skip that one.
  const stayRow = () => $$('#h-tbody tr').find((t) => t.textContent.includes('AHMED TEST') && !t.textContent.includes('To complete'));
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

  checkIcons();
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

  /** Line icons instead of emojis: the sidebar draws them from the page's sprite and no screen text holds an emoji. */
  function checkIcons() {
    const uses = $$('#sidebar svg.ic use');
    ok(uses.length >= 7 && uses.every((u) => w.document.getElementById(u.getAttribute('href').slice(1))), 'icons: sidebar icons point at symbols of the sprite');
    const emoji = /[←↑↓-⇿⌀-⏿①-➿⬀-⯿\u{1F000}-\u{1FFFF}️]/u;
    ok(!emoji.test(w.document.body.textContent), 'icons: no emoji in any text on the page');
  }

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
    // The management Excel: every role may download it, for a From–To range.
    ok($('[data-act="dashboard-export"]'), 'dashboard: Excel button shown');
    const today = localNow().slice(0, 10);
    const sheet = await w.fetch(`/api/dashboard/export/?from=${today.slice(0, 8)}01&to=${today}`);
    ok(sheet.status === 200 && (sheet.headers.get('Content-Type') || '').includes('spreadsheetml'), 'dashboard: Excel file downloads');
    const rangeFrom = $('#d-from').value;
    const rangeTo = $('#d-to').value;
    click($('#d-clear'));
    // Let the cleared range finish loading first: its "Synced" would otherwise replace the error line.
    await waitFor(() => $('#d-from').value === '' && $('#d-to').value === '' && $('#status-text').textContent === 'Synced', 8000);
    click($('[data-act="dashboard-export"]'));
    ok(await waitFor(() => $('#status-text').textContent.includes('Choose a From and To date.')), 'dashboard: Excel needs a From and To date');
    type($('#d-from'), rangeFrom); type($('#d-to'), rangeTo);
    await waitFor(() => $('#f-from').value === rangeFrom && $('#f-to').value === rangeTo);
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
