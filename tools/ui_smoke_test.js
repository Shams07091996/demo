// End-to-end smoke test: loads the real page in jsdom, logs in over HTTP and clicks through the app.
//
//   python manage.py seed_demo --password "some-long-password" --two-step-key <32 base32 characters>
//   python manage.py runserver 8765          (in another terminal)
//   UI_TEST_PASSWORD="some-long-password" UI_TEST_TOTP_KEY=<the same key> node ui_smoke_test.js [alex|admin|viewer|suez]
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
  // Every new vessel is for a ship. With none picked, Enter in the name box opens the New ship panel under it
  // (`box`): tick No IMO and save; the box closes and the ship is picked.
  const newShipVia = async (input, box) => {
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    if (!await waitFor(() => shown($(box)) && $(`${box} [name=no_imo]`))) return false;
    const tick = $(`${box} [name=no_imo]`);
    tick.checked = true; tick.dispatchEvent(new w.Event('change', { bubbles: true }));
    click($$(`${box} button`).find((b) => b.textContent === 'Save ship'));
    return waitFor(() => !shown($(box)));
  };
  let apiShipId = null; // a ship for vessels the test makes through the API
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
    const shipRes = await w.fetch('/api/ships/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
      body: JSON.stringify({ name: 'SMOKE API SHIP', no_imo: true }),
    });
    apiShipId = (await shipRes.json()).id;
    ok(shipRes.status === 201 || shipRes.status === 200, `ships: a ship with No IMO is created (HTTP ${shipRes.status})`);
    const res = await w.fetch('/api/vessels/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta() },
      body: JSON.stringify({ ship_id: apiShipId, name: HOSTILE, arrival_agent: HOSTILE_AGENT, opr: '<i>O</i>', poc: 'ALY', port: 'alexandria', date: localNow() }),
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
    const portCol = $$('#c-head th').findIndex((th) => th.textContent.trim().startsWith('Port'));
    ok($$('#c-head th').length === calcRows()[0].children.length
      && (portCol < 0 || calcRows()[0].children[portCol].textContent.length > 0), 'calculations: the Port column lines up with its rows');
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
    await waitFor(() => $('[data-new="agent"]'));
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

  // A Marine employee (run: node ui_smoke_test.js marine): seed_demo gives them the Marine template — Vessels and
  // Services only; add / edit vessels and services, mark Completed, money in forms; no delete, cancel, exports.
  if (ROLE === 'marine') {
    ok($$('#nav .nav-item').map((a) => a.dataset.page).join() === 'vessels,services', 'marine: the sidebar is Vessels and Services');
    ok(!$('[data-group="operation"]') && (await w.fetch('/api/operation/visits/')).status === 403, 'marine: no Operation folder, its API refuses them');
    ok(await waitFor(() => $$('#tbody tr').length > 0) && !$('#tbody [data-act="del-vessel-row"]'), 'marine: no Delete button on vessel rows');
    ok(shown($('#addVesselBtn')), 'marine: + Add Vessel is there');
    // No customers.edit: the ship type-ahead offers existing ships only, never "+ New ship" (the server would refuse).
    type($('#qa-name'), 'MSC');
    ok(await waitFor(() => $$('#quickAdd .ship-opt').length > 0) && !$$('#quickAdd .ship-opt').some((o) => o.textContent.startsWith('+ New ship')),
      'marine: the ship list has no + New ship');
    $('#qa-name').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    type($('#qa-name'), '');
    await openRow('MSC AURORA');
    ok(!$('#modal [data-act="del-vessel"]') && !!$('#modal [data-act="edit-vessel"]') && !!$('#modal [data-act="add-service"]'),
      'marine: the vessel dialog edits but cannot delete');
    ok(!$('#modal [data-act="receipt"]'), 'marine: no Receipt button without documents');
    // Money (piece 3): they type money (money.edit) but get no overview (no money.view).
    ok(!$('#modal').textContent.includes('Total profit') && !$('#modal').textContent.includes('Total cost'),
      'marine: the vessel dialog shows no total cost or profit');
    click($('#modal [data-act="edit-service"]'));
    ok(await waitFor(() => $('#svc-form [name=status]')), 'marine: a service opens for editing');
    ok(!!$('#svc-form [name=cost]') && !!$('#svc-form #preview'), 'marine: the service dialog has its Cost box and the preview');
    const option = (value) => [...$('#svc-form [name=status]').options].find((o) => o.value === value);
    ok(!option('completed').disabled && option('cancelled').disabled, 'marine: Completed can be chosen, Cancelled cannot');
    closeModal();
    await go('services');
    ok(!$('#page-services [data-act="page-export"]'), 'marine: no Excel button');
    w.location.hash = 'calculations';
    ok(await waitFor(() => $('#pageTitle').textContent === 'Vessels'), 'marine: #calculations lands on Vessels');
    ok((await w.fetch('/api/calculations/')).status === 403, 'marine: the Calculations API refuses them');
    ok((await w.fetch('/api/history/')).status === 403, 'marine: the History API refuses them');
    ok((await w.fetch('/api/vessels/?sort=total_cost_egp')).status === 403, 'marine: sorting vessels by money is refused');
    const listed = await (await w.fetch('/api/vessels/')).json();
    ok(!('profit_egp' in listed.totals) && listed.vessels.every((v) => !('total_profit_egp' in v)),
      'marine: the vessel list sends no totals or profit');
    return finish();
  }

  // A User of three ports (run: node ui_smoke_test.js viewer): Alexandria (home), Port Said and Damietta, never Suez.
  // A short, separate run: the full edit flows are walked by alex.
  if (ROLE === 'viewer') {
    const labels = (el) => [...el.options].map((o) => o.textContent).join();
    ok(!!$('#nav [data-page="history"]') && !$('#nav [data-page="accounts"]') && !$('#nav [data-page="ports"]'),
      'three-port user: History (they have it), no Accounts or Ports in the sidebar');
    ok(!!$('#nav [data-page="op_list"]') && !$('#nav [data-page="terminals"]') && !$('#nav [data-page="op_windows"]')
      && !$('[data-act="vl-new"]'), 'three-port user: the vessel list to read, no Terminals or Berthing windows');
    ok($('#roleLabel').textContent === 'Alexandria, Port Said, Damietta', 'three-port user: the sidebar names their ports');
    ok(shown($('#portSelect')) && labels($('#portSelect')) === 'All my ports,Alexandria,Port Said,Damietta',
      'three-port user: the port filter offers exactly their three ports');
    ok(shown($('#qa-port')) && labels($('#qa-port')) === 'Alexandria,Port Said,Damietta' && $('#qa-port').value === 'alexandria',
      'three-port user: quick add offers their ports, starting on Alexandria');
    click($('#addVesselBtn'));
    ok(await waitFor(() => $('#vessel-form [name=port]')) && labels($('#vessel-form [name=port]')) === 'Alexandria,Port Said,Damietta'
      && $('#vessel-form [name=port]').value === 'alexandria', 'three-port user: the vessel form offers their ports, default Alexandria');
    closeModal();
    // A vessel saved in Damietta (one of their extra ports) appears; no Suez vessel anywhere.
    const { ships } = await (await w.fetch('/api/ships/?limit=200')).json();
    const ship = ships.find((s) => s.name === 'MSC AURORA');
    const name = `SMOKE DAMI ${Date.now().toString(36).toUpperCase()}`;
    const { options } = await (await w.fetch('/api/options/')).json();
    const poc = options.find((o) => o.kind === 'poc' && ['', 'damietta'].includes(o.port))?.value || '';
    const res = await w.fetch('/api/vessels/', { method: 'POST', headers: { 'X-CSRFToken': meta(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ship_id: ship.id, date: localNow(), port: 'damietta', opr: ship.opr, poc }) });
    const made = await res.json();
    ok(res.status === 201 && made.port === 'damietta', `three-port user: a vessel is saved in Damietta${res.ok ? '' : `: ${made.error}`}`);
    type($('#portSelect'), 'damietta');
    ok(await waitFor(() => rowFor(name)), 'three-port user: the Damietta vessel is listed');
    type($('#portSelect'), 'ALL');
    const { vessels } = await (await w.fetch('/api/vessels/?page_size=100&port=suez')).json();
    ok(vessels.length > 0 && vessels.every((v) => v.port !== 'suez'), 'three-port user: asking for Suez never shows a Suez vessel');
    await waitFor(() => $$('#tbody tr').length > 0);
    ok(!$('#tbody').textContent.includes('Suez'), 'three-port user: no Suez vessel in the list');
    const refused = await w.fetch('/api/vessels/', { method: 'POST', headers: { 'X-CSRFToken': meta(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'SMOKE SUEZ', ship_id: ship.id, date: localNow(), port: 'suez', opr: ship.opr }) });
    ok(refused.status === 403, 'three-port user: a vessel in Suez is refused');
    // Port closures: both seeded closures (Alexandria, Port Said) are theirs; the dialog offers their three ports.
    await go('closures');
    click($('#pc-clear'));
    ok(await waitFor(() => $$('#pc-tbody tr').length >= 2) && /Port/.test($('#pc-head').textContent), 'three-port user: closures of their ports, with a Port column');
    click($('[data-act="closure-new"]'));
    ok(await waitFor(() => $('#closure-form [name=port]')) && labels($('#closure-form [name=port]')) === 'Alexandria,Port Said,Damietta',
      'three-port user: the closure dialog offers their ports');
    closeModal();
    // Calculations: with Close / reopen lines (seed_demo gives full Users everything) the switch is there.
    await go('calculations');
    ok(await waitFor(() => $$('#c-tbody tr').length > 0) && !!$('#c-tbody [data-act="acct-toggle"]'),
      'three-port user: Calculations has the Open / Closed switch');
    ok((await w.fetch(`/api/vessels/${made.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } })).ok, 'three-port user: the Damietta vessel is deleted');
    await checkHistory();
    return finish();
  }

  /* ======== layout: sidebar and pages ======== */
  const navItems = $$('#nav .nav-item').filter((a) => a.style.display !== 'none');
  ok($('#sidebar') && navItems.length === (ROLE === 'admin' ? 22 : 20), 'sidebar lists the pages (Admins also have Accounts and Ports; no Bulk add)');
  const pageOrder = 'vessels,services,closures,ships,op_vessels,op_live,op_analysis,op_charts,op_list,terminals,op_windows,dashboard,disposal,hotels,transport,calculations,master,customers,rates'
    + (ROLE === 'admin' ? ',ports,accounts' : '') + ',history';
  ok($$('#nav .nav-item').map((a) => a.dataset.page).join() === pageOrder, 'sidebar: Marine, Operation, Reports, Master data folders in order; History last');
  ok(!$('.tabs') && $('.sidebar'), 'navigation is a sidebar, not a tab bar');
  ok(!$('#page-vessels').hidden && $('#pageTitle').textContent === 'Vessels', 'starts on the Vessels page');
  for (const [page, title] of [['services', 'Services'], ['hotels', 'Hotels'], ['transport', 'Transport'], ['closures', 'Port closures'], ['disposal', 'Garbage & Sludge'], ['calculations', 'Calculations'], ['dashboard', 'Dashboard'], ['ships', 'Ships'], ['customers', 'Customers'], ['master', 'Master data'], ['rates', 'Exchange rates'], ['vessels', 'Vessels']]) {
    await go(page);
    ok($$('.page').filter((p) => !p.hidden).length === 1 && $('#pageTitle').textContent === title && $(`#nav [data-page="${page}"]`).classList.contains('active'), `sidebar opens "${title}"`);
  }

  /* ---- Operation folder: Vessel Data, Live data, Analysis reports, Report charts (seed_demo: the workbook's visits,
     NORDIC STAR working at ACCHCO - ALX) ---- */
  for (const [page, title] of [['op_vessels', 'Vessel Data'], ['op_live', 'Live data'], ['op_analysis', 'Analysis reports'], ['op_charts', 'Report charts']]) {
    await go(page);
    ok($('#pageTitle').textContent === title && $(`#nav [data-page="${page}"]`).closest('[data-group="operation"]'), `operation: "${title}" opens from the Operation folder`);
  }
  await go('op_live');
  ok(await waitFor(() => $('#ol-cards').textContent.includes('NORDIC STAR')), 'operation: Live data shows the vessel under operation');
  const liveChip = (name) => $$('#ol-terminals [data-terminal]').find((b) => b.textContent === name);
  ok(await waitFor(() => liveChip('All')?.classList.contains('active') && liveChip('ACCHCO - ALX')), 'operation: Live data has All and a button per terminal');
  click(liveChip('ACCHCO - ALX'));
  ok(await waitFor(() => $$('#ol-cards .op-card').length === 1 && $('#ol-cards h3').textContent.startsWith('ACCHCO - ALX')),
    'operation: a terminal button shows only that terminal');
  // The smoke server's letterhead folder has terminals/EGALY.png (ACCHCO - ALX) only.
  const pic = $('#ol-cards img.op-pic');
  ok(!!pic && (await w.fetch(pic.getAttribute('src'))).headers.get('content-type') === 'image/png', 'operation: the terminal picture shows');
  click(liveChip('All'));
  ok(await waitFor(() => $$('#ol-cards .op-card').length >= 5), 'operation: All shows every terminal again');
  await go('op_analysis');
  ok(await waitFor(() => $$('#oa-tiles .stat').length >= 5 && Number($('#oa-tiles .stat b').textContent) > 0), 'operation: Analysis shows the vessel calls');
  ok($$('#oa-terminals tbody tr').length >= 5 && $('#oa-lines').textContent.includes('ARKAS'), 'operation: Analysis has the terminal and shipping line tables');
  await go('op_charts');
  ok(await waitFor(() => $$('#oc-calls .bar').length >= 5 && $$('#oc-hours .bar').length >= 5), 'operation: Report charts draws the bars');
  if (ROLE === 'alex') {
    await go('op_vessels');
    const ovRow = (name) => $$('#ov-tbody tr').find((r) => r.children[1].textContent === name);
    ok(await waitFor(() => $$('#ov-tbody tr').length > 0), 'operation: Vessel Data lists the visits');
    click($('[data-act="opv-new"]'));
    ok(await waitFor(() => $('#visit-form [name=terminal]')), 'operation: + Add visit opens the dialog');
    const vf = (name) => $(`#visit-form [name="${name}"]`);
    type(vf('shipping_line'), 'MAERSK');
    type(vf('vessel_name'), 'nordic star');
    ok(await waitFor(() => vf('loa').value === '210' && vf('shipping_line').value === 'ARKAS'),
      'operation: a name from the vessel list fills its LOA and its operator');
    type(vf('loa'), '');
    type(vf('vessel_name'), 'smoke visit');
    type(vf('terminal'), [...vf('terminal').options].find((o) => o.textContent === 'ACCHCO - ALX').value);
    type(vf('eta'), '2026-11-26T08:00'); // a Thursday: MAERSK's next window there is Fri 22:00
    type(vf('shipping_line'), 'MAERSK');
    ok(await waitFor(() => !$('#visit-window').hidden && $('#visit-window').textContent
      === 'Window: Fri 27.11 22:00 → Sat 28.11 20:00 · ETA 38 h before'), 'operation: the visit shows its line\'s nearest berthing window');
    type(vf('shipping_line'), 'ARKAS');
    ok(await waitFor(() => $('#visit-window').hidden), 'operation: a line without windows shows none');
    type(vf('eta'), '2026-11-20T08:00');
    type(vf('cranes'), '2');
    click($('[data-act="opv-save"]'));
    ok(await waitFor(() => ovRow('SMOKE VISIT')?.textContent.includes('Planned')), 'operation: a new visit is saved upper-case and Planned');
    click(ovRow('SMOKE VISIT').querySelector('td'));
    ok(await waitFor(() => $('#modal h2')?.textContent.includes('SMOKE VISIT')), 'operation: a visit opens');
    type(vf('ata'), '2026-11-20T09:00');
    type(vf('atb'), '2026-11-20T11:00');
    type(vf('atd'), '2026-11-20T21:00');
    type(vf('discharge'), '300');
    type(vf('loading'), '200');
    click($('[data-act="opv-save"]'));
    ok(await waitFor(() => ovRow('SMOKE VISIT')?.textContent.includes('Completed')), 'operation: with ATD the visit is Completed');
    const done = ovRow('SMOKE VISIT').children;
    ok(done[15].textContent === '2' && done[16].textContent === '10' && done[20].textContent === '50',
      `operation: waiting, operation and moves/hr worked out (${done[15].textContent} / ${done[16].textContent} / ${done[20].textContent})`);
    click(ovRow('SMOKE VISIT').querySelector('td'));
    await waitFor(() => $('#modal [data-act="opv-del"]'));
    click($('#modal [data-act="opv-del"]'));
    ok(await waitFor(() => !ovRow('SMOKE VISIT')), 'operation: a visit is deleted');
  }
  if (ROLE === 'admin') {
    await go('terminals');
    const tmRow = (name) => $$('#tm-tbody tr').find((r) => r.children[0].textContent === name);
    ok(await waitFor(() => tmRow('ACCHCO - ALX')), 'terminals: the page lists the terminals');
    const tname = `Smoke${Date.now().toString(36)}`;
    click($('[data-act="terminal-new"]'));
    await waitFor(() => $('#terminal-form'));
    const tf = (name) => $(`#terminal-form [name="${name}"]`);
    type(tf('name'), tname);
    type(tf('code'), 'SMK');
    type(tf('port'), 'alexandria');
    type(tf('quay_length'), '400');
    type(tf('cranes'), '3');
    type($('#terminal-form [data-berth]'), 'S1');
    click($('[data-act="terminal-save"]'));
    ok(await waitFor(() => tmRow(tname)), 'terminals: + Add terminal adds one');
    click(tmRow(tname));
    await waitFor(() => $('#terminal-lines [data-line="ARKAS"]'));
    $('#terminal-lines [data-line="ARKAS"]').checked = true;
    click($('[data-act="terminal-save"]'));
    ok(await waitFor(() => tmRow(tname)?.children[6].textContent === 'ARKAS'), 'terminals: a terminal keeps its shipping lines');
    await go('op_list');
    const vlRow = (name) => $$('#vl-tbody tr').find((r) => r.children[0].textContent === name);
    ok(await waitFor(() => vlRow('NORDIC STAR')?.children[1].textContent === 'ARKAS' && vlRow('NORDIC STAR').children[2].textContent === '210'),
      'vessel list: the demo vessels, their operator and LOA');
    click($('[data-act="vl-new"]'));
    await waitFor(() => $('#listed-form'));
    type($('#listed-form [name=name]'), 'smoke listed');
    type($('#listed-form [name=loa]'), '123.4');
    type($('#listed-form [name=line]'), 'SOC');
    click($('[data-act="vl-save"]'));
    ok(await waitFor(() => vlRow('SMOKE LISTED')?.children[2].textContent === '123.4' && vlRow('SMOKE LISTED').children[1].textContent === 'SOC'),
      'vessel list: + Add vessel adds one with its operator');
    click(vlRow('SMOKE LISTED'));
    await waitFor(() => $('#modal [data-act="vl-del"]'));
    click($('#modal [data-act="vl-del"]'));
    ok(await waitFor(() => !vlRow('SMOKE LISTED')), 'vessel list: an Admin deletes an entry');
    await go('op_windows');
    const wnRows = () => $$('#wn-tbody tr').map((r) => [...r.children].map((c) => c.textContent).join('|'));
    ok(await waitFor(() => wnRows().includes('ACCHCO - ALX · Alexandria|MAERSK|Tue 06:00 → Wed 18:00|36 h')
      && wnRows().some((r) => r.startsWith('PSD EAST'))), 'berthing windows: the page lists every port\'s windows');
    click($('[data-act="window-new"]'));
    await waitFor(() => $('#window-form'));
    const wf = (name) => $(`#window-form [name="${name}"]`);
    type(wf('terminal'), [...wf('terminal').options].find((o) => o.textContent === 'AICT - ALX').value);
    type(wf('line'), 'SOC');
    type(wf('start_day'), '6');
    type(wf('start_time'), '20:00');
    type(wf('end_day'), '0');
    type(wf('end_time'), '06:00');
    click($('[data-act="window-save"]'));
    const smokeRow = () => $$('#wn-tbody tr').find((r) => r.textContent.includes('Sun 20:00 → Mon 06:00'));
    ok(await waitFor(() => smokeRow()?.children[3].textContent === '10 h'), 'berthing windows: + Add window adds one over the week end');
    click(smokeRow());
    await waitFor(() => $('#modal [data-act="window-delete"]'));
    click($('#modal [data-act="window-delete"]'));
    ok(await waitFor(() => !smokeRow()), 'berthing windows: a window is deleted');
  }
  if (ROLE === 'alex') {
    await go('terminals');
    ok(await waitFor(() => $$('#tm-tbody tr').length >= 5) && !$$('#tm-tbody tr').some((r) => r.textContent.includes('PSD EAST')),
      'terminals: the edit-terminals tick shows only their own ports\' terminals');
    await go('op_windows');
    ok(await waitFor(() => $$('#wn-tbody tr').length === 2) && !$('#wn-tbody').textContent.includes('PSD EAST'),
      'berthing windows: the edit-terminals tick shows only their own ports\' windows');
    await go('op_list');
    await waitFor(() => $$('#vl-tbody tr').length > 0);
    click($$('#vl-tbody tr').find((r) => r.children[0].textContent === 'NORDIC STAR'));
    ok(await waitFor(() => $('#listed-form')) && !!$('#modal [data-act="vl-save"]') && !$('#modal [data-act="vl-del"]'),
      'vessel list: the tick edits entries, only Admins delete');
    closeModal();
  }

  /* ---- services page: the work list (seed_demo: MSC AURORA's Crew Change has draft bookings, SEA BREEZE's
     Landing has no agent) ---- */
  await go('services');
  const svCard = (vessel) => $$('#sv-cards .sv-vessel').find((c) => c.querySelector('.sv-vessel-name').textContent === vessel);
  const svRow = (vessel, type) => [...(svCard(vessel)?.querySelectorAll('.sv-svc') || [])].find((s) => s.querySelector('strong').textContent === type);
  ok(await waitFor(() => svRow('MSC AURORA', 'Crew Change')), 'services: the page lists services under their vessels');
  ok(svCard('MSC AURORA').querySelector('.sv-vessel-body').hidden, 'services: a vessel card starts closed');
  click(svCard('MSC AURORA').querySelector('[data-act="sv-toggle"]'));
  ok(await waitFor(() => !svCard('MSC AURORA').querySelector('.sv-vessel-body').hidden && svCard('MSC AURORA').querySelector('.sv-count').textContent.endsWith('services')), 'services: a vessel card opens to its services');
  ok($('#sv-status-filter summary').textContent === 'Status: In progress', 'services: opens with In progress ticked');
  ok(svRow('MSC AURORA', 'Crew Change').textContent.includes('Bookings'), 'services: a Crew Change with draft bookings is missing Bookings');
  ok(svRow('SEA BREEZE', 'Landing')?.textContent.includes('Agent') && svRow('SEA BREEZE', 'Landing').textContent.includes('Sailed'), 'services: a sailed vessel\'s open service is marked Sailed, its missing agent shown');
  $('#sv-missing').checked = true; $('#sv-missing').dispatchEvent(new w.Event('change', { bubbles: true }));
  ok(await waitFor(() => !svRow('MSC AURORA', 'Fresh Water') && svRow('SEA BREEZE', 'Landing')), 'services: Missing details only hides complete services');
  $('#sv-missing').checked = false; $('#sv-missing').dispatchEvent(new w.Event('change', { bubbles: true }));
  await waitFor(() => svRow('MSC AURORA', 'Fresh Water'));
  const svTick = (value, on) => { const box = $(`#sv-ticks [data-tick=svstatus][value=${value}]`); box.checked = on; box.dispatchEvent(new w.Event('change', { bubbles: true })); };
  svTick('completed', true);
  ok(await waitFor(() => svRow('MSC AURORA', 'Fresh Water')?.textContent.includes('Completed:')), 'services: ticking Completed shows the completed date on the service cards');
  svTick('completed', false);
  await waitFor(() => svRow('MSC AURORA', 'Fresh Water') && !svRow('MSC AURORA', 'Fresh Water').textContent.includes('Completed:'));
  {
    const exports = [];
    const plainFetch = w.fetch;
    w.fetch = async (url, options) => {
      const response = await plainFetch(url, options);
      if (String(url).includes('/api/export/')) exports.push({ url: String(url), status: response.status });
      return response;
    };
    if (!w.URL.createObjectURL) w.URL.createObjectURL = () => 'blob:smoke';
    if (!w.URL.revokeObjectURL) w.URL.revokeObjectURL = () => {};
    click($('#page-services [data-act="page-export"]'));
    ok(await waitFor(() => exports.length) && exports[0].status === 200 && exports[0].url.includes('/api/export/services/?status=in_progress') && !/[?&]page(_size)?=/.test(exports[0].url), 'services: Excel downloads the filtered list (every page)');
    w.fetch = plainFetch;
  }
  click(svRow('MSC AURORA', 'Fresh Water'));
  if (ROLE === 'viewer') {
    ok(await waitFor(() => $('#modal h2')?.textContent.includes('MSC AURORA') && !$('#svc-form')), 'services: a read-only user gets the vessel');
    closeModal();
  } else {
    ok(await waitFor(() => $('#svc-form')), 'services: a row opens its service');
    click($('[data-act="save-service"]'));
    ok(await waitFor(() => !$('#svc-form') && !$('#overlay').classList.contains('open') && !$('#page-services').hidden), 'services: saving goes back to the list');
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
    click($('[data-type="Others / Remarks"]')); await waitFor(() => $('#svc-form'));
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

  /* ---- service status and accounting: Calculations columns, tick-box filters, the Open / Closed switch ---- */
  const calcHeads = () => $$('#c-head th').map((th) => th.textContent.trim());
  ok(calcHeads().includes('Status') && calcHeads().includes('Accounting'), 'calculations: Status and Accounting columns');
  ok(calcHeads().includes('Billing party') && calcHeads().includes('Billing'), 'calculations: Billing party and Billing columns');
  ok(await waitFor(() => waterRow()?.textContent.includes('On account')), 'calculations: a service line shows On account');
  ok([...$('#c-party').options].map((o) => o.textContent).slice(0, 2).join() === 'All billing parties,No billing party', 'calculations: billing party filter');
  ok(await waitFor(() => waterRow()?.querySelector('.svc-status')?.textContent === 'In progress'), 'calculations: a service line shows its status label');
  ok($('#c-status-filter summary')?.textContent === 'Status: All' && $('#c-accounting-filter summary')?.textContent === 'Accounting: All', 'calculations: tick-box filters for Status and Accounting');
  const tick = (name, value) => $(`[data-tick="${name}"][value="${value}"]`);
  const setTick = (name, value, on) => { const box = tick(name, value); box.checked = on; box.dispatchEvent(new w.Event('change', { bubbles: true })); };
  setTick('billing', 'account', false);
  ok(await waitFor(() => !waterRow() && $('#c-billing-filter summary')?.textContent === 'Billing: Cash'), 'calculations: unticking On account leaves only Cash lines');
  setTick('billing', 'account', true);
  ok(await waitFor(() => waterRow()), 'calculations: ticking On account again shows the line');
  setTick('status', 'completed', false);
  ok(await waitFor(() => $('#c-status-filter summary').textContent === 'Status: All except Completed' && waterRow()), 'calculations: "All except Completed" keeps the in-progress lines');
  setTick('status', 'in_progress', false);
  ok(await waitFor(() => !waterRow()), 'calculations: unticking In progress hides its lines');
  setTick('status', 'in_progress', true); setTick('status', 'completed', true);
  ok(await waitFor(() => $('#c-status-filter summary').textContent === 'Status: All' && waterRow()), 'calculations: ticking everything again shows every line');
  ok(/Open \d+ · Closed \d+/.test($('#c-totals').textContent), 'calculations: totals count Open and Closed lines');
  const setMonthRate = async (rate) => {
    await go('rates');
    type($('#rate-form [name=month]'), localNow().slice(0, 7)); type($('#rate-form [name=rate]'), rate);
    click($('[data-act="save-rate"]'));
    await waitFor(() => $('#rates-panel').textContent.includes(rate));
    await go('calculations');
    await waitFor(() => waterRow());
  };
  if (ROLE === 'admin') {
    // Rates are stored with 4 decimals; the working shows them in full so the multiplication adds up.
    await setMonthRate('48.2525');
    ok(await waitFor(() => waterRow()?.textContent.includes('USD 900.00 × 48.2525 = 43,427.25')), 'calculations: a 4-decimal rate is shown in full');
  }
  if (ROLE === 'viewer' || ROLE === 'admin') {
    click(waterRow().querySelector('[data-act="acct-toggle"]'));
    ok(await waitFor(() => waterRow()?.querySelector('.acct-switch.closed')), 'accounting: the switch closes a line');
    setTick('accounting', 'closed', false);
    ok(await waitFor(() => $('#c-accounting-filter summary').textContent === 'Accounting: Open' && !waterRow()), 'accounting: the Open filter hides the closed line');
    setTick('accounting', 'closed', true);
    ok(await waitFor(() => waterRow()), 'accounting: ticking Closed again shows it');
    if (ROLE === 'admin') {
      click(waterRow().querySelector('[data-act="summary"]'));
      await waitFor(() => $('#modal [data-act="open-vessel"]'));
      click($('#modal [data-act="open-vessel"]'));
      const waterCard = () => $$('.svc-card').find((c) => c.textContent.includes('Fresh Water'));
      ok(await waitFor(() => waterCard()?.textContent.includes('Closed by accounting')), 'accounting: the service card says Closed by accounting');
      click(waterCard().querySelector('[data-act="edit-service"]'));
      await waitFor(() => $('[data-act="save-service"]'));
      click($('[data-act="save-service"]'));
      ok(await waitFor(() => $('#modal .error')?.textContent.includes('Accounting has closed this')), 'accounting: editing a closed service shows the lock message');
      closeModal();
      await go('calculations');
      await waitFor(() => waterRow());
    }
    click(waterRow().querySelector('[data-act="acct-toggle"]'));
    ok(await waitFor(() => waterRow()?.querySelector('.acct-switch:not(.closed)')), 'accounting: the switch reopens the line');
    if (ROLE === 'admin') {
      await setMonthRate('50');
      ok(await waitFor(() => waterRow()?.textContent.includes('× 48.2525 = 43,427.25')), 'accounting: the rate kept on closing stays after reopening and a new month rate');
      // A person clears the kept rate: the line follows the month rate again (and the next role sees the seeded figures).
      click(waterRow().querySelector('[data-act="summary"]'));
      await waitFor(() => $('#modal [data-act="open-vessel"]'));
      click($('#modal [data-act="open-vessel"]'));
      const waterCard = () => $$('.svc-card').find((c) => c.textContent.includes('Fresh Water'));
      await waitFor(() => waterCard());
      click(waterCard().querySelector('[data-act="edit-service"]'));
      await waitFor(() => $('#svc-form [name=exchangeRate]'));
      ok($('#svc-form [name=exchangeRate]').value === '48.2525', 'accounting: the kept rate shows in the service form');
      type($('#svc-form [name=exchangeRate]'), '');
      click($('[data-act="save-service"]'));
      await waitFor(() => !$('#svc-form'));
      closeModal();
      await go('calculations');
      ok(await waitFor(() => waterRow()?.textContent.includes('USD 900.00 × 50.00 = 45,000.00')), 'accounting: clearing the kept rate goes back to the month rate');
    }
  } else {
    ok(!!waterRow().querySelector('[data-act="acct-toggle"]'), 'accounting: a User with Close / reopen lines has the switch');
  }
  if (ROLE === 'alex') {
    // Operations: a service set to Cancelled needs a reason, its money goes to 0, its card says so.
    await go('vessels');
    await openRow('MSC AURORA');
    click($('[data-act="add-service"]'));
    click($('[data-type="Others / Remarks"]')); await waitFor(() => $('#svc-form'));
    type($('#svc-form [name=note]'), 'status smoke'); type($('#svc-form [name=cost]'), '9');
    ok($('#svc-form [name=status]').value === 'in_progress' && $('#svc-reason').hidden, 'status: a new service starts In progress, no reason box');
    click($('[data-act="save-service"]'));
    const smokeCard = () => $$('.svc-card').find((c) => c.textContent.includes('status smoke'));
    await waitFor(() => smokeCard());
    click(smokeCard().querySelector('[data-act="edit-service"]'));
    await waitFor(() => $('#svc-form [name=status]'));
    type($('#svc-form [name=status]'), 'cancelled');
    ok(!$('#svc-reason').hidden && $('#svc-form [name=cost]').value === '0', 'status: choosing Cancelled shows the reason box and sets the money to 0');
    click($('[data-act="save-service"]'));
    ok(await waitFor(() => $('#modal .error')?.textContent.includes('Write why the service was cancelled')), 'status: Cancelled without a reason is refused');
    type($('#svc-form [name=cancel_reason]'), 'Owner cancelled <b>B</b>');
    click($('[data-act="save-service"]'));
    ok(await waitFor(() => smokeCard()?.querySelector('.svc-status')?.textContent === 'Cancelled'), 'status: the card shows Cancelled');
    ok(smokeCard().textContent.includes('Reason: Owner cancelled <b>B</b>') && noMarkup(smokeCard()), 'status: the card shows the reason literally');
    click(smokeCard().querySelector('[data-act="del-service"]'));
    await waitFor(() => !smokeCard());
    closeModal();
    ok(await waitFor(() => rowFor('MSC AURORA')?.textContent.includes('in progress')), 'status: the vessel list shows how many services are in progress');
    await go('calculations');
    await waitFor(() => waterRow());
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
  ok($$('#master-grid .panel h3').map((h) => h.textContent).join() === 'OPR,POC,Agent,Hotel,Airport,Port,Delay reason,Closure reason,Terminal,Shipping line', 'master data has OPR, POC, Agent, Hotel, Airport, Port, Delay reason, Closure reason, Terminal and Shipping line lists');
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
    ok($$('select[data-new-port]').length === 10 && portChoices($('select[data-new-port="agent"]')) === ',alexandria,portsaid,damietta,suez', 'admin: every list has a port choice (All ports + each port)');
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
  ok(await waitFor(() => shown($('#qa-newship')) && $('#qa-newship [name=name]')?.value === NAME), 'quick add: Add with no ship picked opens New ship with the name');
  const qaImo = $('#qa-newship [name=imo]');
  click($$('#qa-newship button').find((b) => b.textContent === 'Save ship'));
  await sleep(500);
  ok(shown($('#qa-newship')) && !rowFor(NAME), 'quick add: New ship without IMO or No IMO is refused (the panel stays)');
  ok(!qaImo.disabled, 'new ship: the IMO box is on until No IMO is ticked');
  click($$('#qa-newship button').find((b) => b.textContent === 'Cancel'));
  ok(await waitFor(() => !shown($('#qa-newship'))), 'new ship: Cancel closes the panel');
  ok(await newShipVia($('#qa-name'), '#qa-newship'), 'quick add: + New ship with No IMO saves and closes');
  click($('#qa-add'));
  ok(await waitFor(() => $('#rangeNotice').textContent.includes('15.01.2020 is outside the current date range')), 'notice for a vessel saved outside the range');
  ok(!rowFor(NAME), 'the range is not changed by itself');
  click($('[data-act="show-outside"]'));
  ok(await waitFor(() => rowFor(NAME)) && $('#f-from').value === '2020-01-15' && $('#rangeNotice').hidden, 'Show it widens the range and shows the row');
  ok(rowFor(NAME).textContent.includes('SMOKE AGENT'), 'the agent shows in the table');
  await go('master');
  ok(await waitFor(() => $$('.opt-row').find((r) => r.textContent.includes('SMOKE AGENT'))?.textContent.includes('1 vessel')), 'master data: usage count goes up');
  await go('vessels');

  /* ======== ships and customers ======== */
  await go('ships');
  const shipRow = (name) => $$('#sh-tbody tr').find((r) => r.textContent.includes(name));
  ok(await waitFor(() => shipRow('MSC AURORA')?.textContent.includes('9074729')), 'ships: the page lists ships with their IMO');
  ok(shipRow('MSC AURORA').textContent.includes('Blue Owners') && shipRow('MSC AURORA').textContent.includes('MSK'), 'ships: OPR and customer shown');
  ok(ROLE === 'viewer' ? !shipRow('MSC AURORA').dataset.act : shipRow('MSC AURORA').dataset.act === 'ship-open', 'ships: only edit roles open a ship');
  type($('#sh-q'), '9321483');
  ok(await waitFor(() => $$('#sh-tbody tr').length > 0 && $$('#sh-tbody tr').every((r) => r.textContent.includes('9321483'))), 'ships: search by IMO');
  type($('#sh-q'), '');
  await go('customers');
  const customerRow = (name) => $$('#cu-tbody tr').find((r) => r.textContent.includes(name));
  ok(await waitFor(() => customerRow('Blue Owners')), 'customers: the page lists customers');
  click(customerRow('Blue Owners'));
  ok(await waitFor(() => $('#customer-form')), 'customers: a customer opens');
  const rateBox = (type) => $(`#customer-form .rate-row[data-type="${type}"] [name=r_amount]`);
  ok(rateBox('Fresh Water').value === '50' || rateBox('Fresh Water').value === '50.00', 'customers: the agreed rates show');
  ok($('#customer-form').textContent.includes('MSC AURORA'), 'customers: linked ships listed');
  if (ROLE === 'admin') {
    type(rateBox('Landing'), '12');
    click($('[data-act="customer-save"]'));
    ok(await waitFor(() => !$('#customer-form') && customerRow('Blue Owners')?.children[2].textContent === '3'), 'customers: admin saves a new rate');
    click(customerRow('Blue Owners'));
    await waitFor(() => $('#customer-form'));
    ok(rateBox('Landing').value.startsWith('12'), 'customers: the saved rate shows again');
    type(rateBox('Landing'), '');
    click($('[data-act="customer-save"]'));
    await waitFor(() => !$('#customer-form'));
  } else {
    // seed_demo's port Users have customers.edit and money.edit (piece 2): they may change a customer's rates.
    ok(!rateBox('Fresh Water').disabled && !!$('[data-act="customer-save"]') && !$('[data-act="customer-del"]'),
      `customers: ${ROLE} may edit the rates but not delete the customer`);
    closeModal();
  }
  await go('vessels');
  if (ROLE !== 'viewer') {
    // The name box offers ships as you type; picking one fills the name and its OPR.
    type($('#qa-name'), 'msc aur');
    const auroraOpt = () => $$('#quickAdd .ship-opt').find((o) => o.textContent.startsWith('MSC AURORA'));
    ok(await waitFor(() => auroraOpt()), 'quick add: typing a name lists matching ships');
    ok($$('#quickAdd .ship-opt').at(-1).textContent.startsWith('+ New ship'), 'quick add: "+ New ship" is the last choice');
    auroraOpt().dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true }));
    ok($('#qa-name').value === 'MSC AURORA' && $('#qa-opr').value === 'MSK' && $('#quickAdd .ship-menu').hidden, 'quick add: picking a ship fills its name and OPR');
    type($('#qa-name'), '');
  }

  /* ======== add-vessel form (+ XSS) ======== */
  click($('#addVesselBtn'));
  ok($('#vessel-form select[name=opr]') && $('#vessel-form select[name=poc]') && $('#vessel-form select[name=arrival_agent]') && $('#vessel-form select[name=sailing_agent]'), 'vessel form uses master-data dropdowns');
  ok($('#vessel-form [name=arrival_agent]').value === '' && $('#vessel-form [name=sailing_agent]').value === '', 'a new vessel starts with no agents');
  ok($$('#vessel-form [type=datetime-local]').length === 5, 'vessel form has the five port-call time fields');
  type($('#vessel-form [name=name]'), '<img src=x onerror=window.__xss=1>');
  type($('#vessel-form [name=date]'), '2020-01-20');
  if (ROLE !== 'admin') {
    click($('[data-act="save-vessel"]'));
    ok(await waitFor(() => /Choose a ship/.test($('#modal .error')?.textContent || '')), 'a new vessel without a ship is refused');
  }
  if (ROLE === 'admin') {
    // On All ports nothing is assumed: the admin chooses the port.
    ok($('#vessel-form [name=port]').value === '', 'admin on All ports: the new vessel has no port yet');
    click($('[data-act="save-vessel"]'));
    ok(await waitFor(() => /Choose a port/.test($('#modal .error')?.textContent || '')), 'admin: a new vessel without a port is refused');
    type($('#vessel-form [name=port]'), 'alexandria');
    click($('[data-act="save-vessel"]'));
    ok(await waitFor(() => /Choose a ship/.test($('#modal .error')?.textContent || '')), 'a new vessel without a ship is refused');
  }
  ok(await newShipVia($('#vessel-form [name=name]'), '#vf-newship'), 'vessel form: + New ship with No IMO saves right in the form');
  ok(/IMO none/.test($('#vf-imo').textContent), 'vessel form: the picked ship shows its IMO');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /Choose an OPR/.test($('#modal .error')?.textContent || '')), 'a new vessel without an OPR is refused');
  type($('#vessel-form [name=opr]'), 'MSK');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /Choose a POC/.test($('#modal .error')?.textContent || '')), 'a new vessel without a POC is refused');
  type($('#vessel-form [name=poc]'), 'ALY');
  type($('[data-sum="Vendor Name"]'), 'ACME & SONS');
  click($('[data-act="save-vessel"]'));
  await waitFor(() => $('#modal h2')?.textContent.includes('<IMG'));
  ok($('#modal h2').textContent.includes('<IMG') && !w.__xss && !$('#modal h2 img'), 'XSS payload in a vessel name does not execute');
  closeModal();
  ok(!$$('#tbody img').length, 'XSS payload is escaped in the table too');

  /* ======== saving into another port than the one shown (admin) ======== */
  if (ROLE === 'admin') {
    type($('#portSelect'), 'suez');
    await waitFor(() => $('#portBanner').textContent.includes('Suez'));
    click($('#addVesselBtn'));
    type($('#vessel-form [name=name]'), 'PORT MOVE');
    type($('#vessel-form [name=port]'), 'alexandria');
    await newShipVia($('#vessel-form [name=name]'), '#vf-newship');
    type($('#vessel-form [name=opr]'), 'MSK'); type($('#vessel-form [name=poc]'), 'ALY');
    type($('#vessel-form [name=date]'), localNow());
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
  // Typing over the name of a linked vessel clears its ship: the save asks for one, picking it again works.
  type($('#vessel-form [name=name]'), `${NAME} II`);
  ok($('#vf-imo').textContent === '', 'vessel form: typing over the name clears the ship');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => /Choose a ship/.test($('#modal .error')?.textContent || '')), 'vessel form: a renamed vessel must pick its ship again');
  type($('#vessel-form [name=name]'), NAME);
  const ownShip = () => $$('#vessel-form .ship-opt').find((o) => o.textContent.startsWith(`${NAME} ·`));
  ok(await waitFor(() => ownShip()), 'vessel form: the name box lists the ship again');
  ownShip().dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true }));
  ok($('#vf-imo').textContent === 'IMO none', 'vessel form: the ship is picked again');
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
  const terminal = [...$('#vessel-form [name=terminal]').options].find((o) => o.value)?.value;
  ok(terminal, 'vessel form: the Terminal list offers the port\'s terminals');
  type($('#vessel-form [name=terminal]'), terminal);
  type($('#vessel-form [name=berth]'), '98/1');
  click($('[data-act="save-vessel"]'));
  ok(await waitFor(() => modalText().includes('15.01.2020 08:30') && modalText().includes('SMOKE AGENT')), 'times and agent saved and shown in the Port call block');
  ok(modalText().includes('Delay reason') && modalText().includes('PORT CLOSED'), 'the delay reason is shown with the times');
  ok(modalText().includes(terminal) && modalText().includes('98/1'), 'terminal and berth are shown with the times');
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
  click($('[data-type="Fresh Water"]')); await waitFor(() => $('#svc-form'));
  ok($('#svc-form select[name=agent]') && $('#svc-form [name=agent]').value === '', 'a new service starts with no agent');
  type($('#svc-form [name=agent]'), 'SMOKE AGENT');
  ok($('#svc-form [name=billing]').value === 'account' && $('#svc-form [name=billing_party]').value === '', 'a new service is On account, no billing party (the ship has no customer)');
  type($('#svc-form [name=billing_party]'), [...$('#svc-form [name=billing_party]').options].find((o) => o.textContent === 'Blue Owners').value);
  ok($('#svc-rate').textContent === 'Agreed rate: USD 50 per unit', 'service: the billing party\'s agreed rate shows');
  type($('[name=quantity]'), '40');
  ok($('[name=revenue]').value === '2000' && $('[name=revenueCurrency]').value === 'USD', 'service: revenue filled from the rate (40 x USD 50)');
  const partyValue = (name) => [...$('#svc-form [name=billing_party]').options].find((o) => o.textContent === name).value;
  type($('#svc-form [name=billing_party]'), partyValue('Red Managers'));
  ok($('[name=revenue]').value === '' && $('#svc-rate').textContent === '', 'service: a payer with no rate clears the filled revenue');
  type($('#svc-form [name=billing_party]'), partyValue('Blue Owners'));
  ok($('[name=revenue]').value === '2000', 'service: back to the payer with a rate fills it again');
  type($('#svc-form [name=billing]'), 'cash');
  type($('[name=revenue]'), '100');
  type($('[name=quantity]'), '41'); type($('[name=quantity]'), '40');
  ok($('[name=revenue]').value === '100', 'service: a typed revenue is kept when the quantity changes');
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
  click($('[data-type="Cash to Master"]')); await waitFor(() => $('#svc-form'));
  type($('[name=amount]'), '1000'); type($('[name=amountCurrency]'), 'USD'); type($('[name=percentage]'), '5'); type($('[name=exchangeRate]'), '50');
  const preview = () => $('#preview').textContent;
  ok(preview().includes('2,500.00') && preview().includes('47,500.00'), 'cash: 5% of 1000 USD = 2,500 ours, 47,500 to the master');
  type($('[name=percentage]'), '10');
  ok(preview().includes('5,000.00') && preview().includes('45,000.00'), 'cash: revenue updates live');
  type($('[name=shareMode]'), 'fixed'); type($('[name=fixedRevenue]'), '100');
  ok(preview().includes('5,000.00'), 'cash: fixed 100 USD gives 5,000 revenue');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => $('[data-act="add-service"]') && modalText().includes('our share fixed USD 100.00')), 'Cash to Master saved');

  /* ======== a service with its own fields: Suez Canal Transit ======== */
  click($('[data-act="add-service"]'));
  click($('[data-type="Suez Canal Transit"]')); await waitFor(() => $('#svc-form'));
  ok($('#svc-form select[name=direction]') && $('#svc-form [name=canalEntry]').type === 'datetime-local'
    && $('#svc-form [name=expectedTransit]').type === 'date', 'suez: its own fields (direction, canal entry, expected transit)');
  const scaLabel = $$('#svc-form .field label').find((l) => l.textContent === 'SCA charges');
  ok(scaLabel && scaLabel.parentElement.querySelector('[name=costCurrency]').value === 'USD', 'suez: the cost is SCA charges in USD');
  type($('#svc-form [name=direction]'), 'Northbound');
  type($('#svc-form [name=canalEntry]'), '2020-01-16T05:30');
  type($('#svc-form [name=cost]'), '1000');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => !$('#svc-form') && modalText().includes('Direction: Northbound') && modalText().includes('Canal entry: 16.01.2020 05:30')),
    'suez: saved, its fields show on the card');

  /* ======== multi-entry ======== */
  click($('[data-act="add-service"]'));
  click($('[data-type="Delivery Parcels"]')); await waitFor(() => $('#svc-form'));
  click($('[data-act="add-entry"]')); click($('[data-act="add-entry"]'));
  const [first, second] = $$('.entry');
  type(first.querySelector('[data-f=awb]'), 'AWB-1'); type(first.querySelector('[data-f=weight]'), '3');
  type(first.querySelector('[data-f=cost]'), '250'); type(first.querySelector('[data-f=revenue]'), '10');
  click(second.querySelector('[data-act="rm-entry"]'));
  const boxOf = (name) => $(`#svc-form [name=${name}]`).closest('.field');
  ok(boxOf('receivingVessel').hidden && boxOf('courier').hidden, 'parcels: receiving vessel and courier wait for a transfer type');
  type($('#svc-form [name=transferType]'), 'Vessel-to-Vessel');
  ok(shown(boxOf('receivingVessel')) && boxOf('courier').hidden, 'parcels: Vessel-to-Vessel shows the receiving vessel');
  type($('#svc-form [name=receivingVessel]'), 'MSC LUNA');
  type($('#svc-form [name=payment]'), 'Paid');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('AWB-1') && modalText().includes('3 kg')), 'Delivery Parcels saved');
  ok(modalText().includes('Receiving vessel: MSC LUNA') && modalText().includes('Courier payment: Paid'), 'parcels: the transfer details show on the card');

  /* ======== crew change ======== */
  click($('[data-act="add-service"]'));
  click($('[data-type="Crew Change"]')); await waitFor(() => $('#svc-form'));
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
  // Saved: each card has Hotel / Transport; on-signers have Broken visa and a LOG link (off-signers neither).
  click($$('.svc-card').find((c) => c.textContent.includes('Crew Change')).querySelector('[data-act="edit-service"]'));
  ok(await waitFor(() => $('.crew-card[data-group="onSigners"] [data-act="crew-log"]')), 'crew change: a saved on-signer has a LOG link');
  const onCardSaved = $('.crew-card[data-group="onSigners"]');
  const offCardSaved = $('.crew-card[data-group="offSigners"]');
  ok(onCardSaved.querySelector('[data-act="crew-hotel"]') && onCardSaved.querySelector('[data-act="crew-transport"]') && onCardSaved.querySelector('[data-crew="visa.cost"]') && offCardSaved.querySelector('[data-act="crew-hotel"]') && offCardSaved.querySelector('[data-act="crew-transport"]') && !offCardSaved.querySelector('[data-crew="visa.cost"]') && !offCardSaved.querySelector('[data-act="crew-log"]'), 'crew change: Hotel / Transport on every card, Broken visa and LOG on on-signers only');
  // Hotel / Transport: pressed, the boxes open filled from the flight (none here: the vessel date); saved, they are the
  // member's drafts on the Hotels / Transport pages; released, the draft goes.
  const onCard = () => $('.crew-card[data-group="onSigners"]');
  ok(onCard().querySelector('[data-act="crew-transport"]').getAttribute('aria-pressed') === 'false' && !onCard().querySelector('[data-crew="transport.at"]'), 'crew: Transport starts released');
  click(onCard().querySelector('[data-act="crew-transport"]'));
  ok(onCard().querySelector('[data-crew="transport.from"]').value === 'airport' && onCard().querySelector('[data-crew="transport.to"]').value === 'port'
    && onCard().querySelector('[data-crew="transport.at"]').value === '2020-01-15T00:00', 'crew: Transport opens From / To / At filled in');
  click(onCard().querySelector('[data-act="crew-hotel"]'));
  // The first hotel on the vessel's port's list (the markup-like one for Alexandria).
  const hotelName = [...onCard().querySelector('[data-crew="hotel.name"]').options].map((o) => o.value).find(Boolean);
  type(onCard().querySelector('[data-crew="hotel.name"]'), hotelName);
  ok(onCard().querySelector('[data-crew="hotel.checkIn"]').value === '2020-01-15' && onCard().querySelector('[data-crew="hotel.checkOut"]').value === '2020-01-16', 'crew: Hotel opens check-in / check-out filled in');
  type(onCard().querySelector('[data-crew="hotel.checkOut"]'), '2020-01-18');
  click($('[data-act="save-service"]'));
  ok(await waitFor(() => modalText().includes('On-signers (1): Ahmed Test') && !$('#svc-form')), 'crew change saved with Hotel / Transport');
  const bookingsOf = async (kind) => (await (await w.fetch(`/api/${kind}/?from=2020-01-01&to=2020-01-31&page_size=200`)).json()).bookings
    .filter((b) => b.guests.some((g) => g.name === 'AHMED TEST') && b.vessel.name === NAME);
  const [stay] = await bookingsOf('hotels');
  ok(stay && hotelName && stay.hotel === hotelName && stay.nights === 3, 'crew: the hotel typed on the card is on the Hotels page (3 nights)');
  ok((await bookingsOf('transfers')).length === 1, 'crew: the pressed Transport is on the Transport page');
  click($$('.svc-card').find((c) => c.textContent.includes('Crew Change')).querySelector('[data-act="edit-service"]'));
  ok(await waitFor(() => onCard()?.querySelector('[data-crew="hotel.name"]')?.value === hotelName), 'crew: the typed hotel comes back');
  click(onCard().querySelector('[data-act="crew-transport"]'));
  click($('[data-act="save-service"]'));
  await waitFor(() => !$('#svc-form'));
  ok((await bookingsOf('transfers')).length === 0, 'crew: releasing Transport removes the draft');
  click($$('.svc-card').find((c) => c.textContent.includes('Crew Change')).querySelector('[data-act="edit-service"]'));
  await waitFor(() => $('#svc-form'));
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
  click($$('[data-act="edit-service"]')[0]); await waitFor(() => $('#svc-form'));
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
  await newShipVia($('#qa-name'), '#qa-newship');
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
        const res = await w.fetch('/api/vessels/', { method: 'POST', headers, body: JSON.stringify({ ship_id: apiShipId, name: `SMOKE GAP ${i}`, opr: 'MSK', poc: 'ALY', date: '2019-03-01' }) });
        extra.push((await res.json()).id);
      }
      type($('#qa-name'), 'smoke gap trigger'); await newShipVia($('#qa-name'), '#qa-newship');
      type($('#qa-date'), localNow()); click($('#qa-add')); // a save reloads the alerts
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

  if (ROLE === 'alex') {
    // Choosing Cancelled on the crew change lists its saved bookings, ticked (closed without saving here).
    await go('vessels');
    await openRow('MSC AURORA');
    const crewCard = () => $$('.svc-card').find((c) => c.textContent.includes('Crew Change'));
    click(crewCard().querySelector('[data-act="edit-service"]'));
    await waitFor(() => $('#svc-form [name=status]'));
    ok($('#svc-bookings').hidden, 'cancel bookings: no list while the crew change is not cancelled');
    type($('#svc-form [name=status]'), 'cancelled');
    const listed = () => $$('#svc-bookings input[data-bk]').find((i) => i.closest('label').textContent.includes('SMOKE HOTEL'));
    ok(await waitFor(() => !$('#svc-bookings').hidden && listed()?.checked), 'cancel bookings: the saved hotel stay is listed, ticked');
    ok(!$$('#svc-bookings label').some((l) => l.textContent.includes('no hotel yet')), 'cancel bookings: drafts are not listed');
    type($('#svc-form [name=status]'), 'completed');
    ok($('#svc-bookings').hidden && !$('#svc-bookings input'), 'cancel bookings: the list goes when Cancelled is unchosen');
    closeModal();
    await go('hotels');
    await waitFor(() => stayRow());

    // A booking's own Cancelled tick: money to 0, the row says Cancelled; unticking keeps what was typed.
    click(stayRow());
    await waitFor(() => $('[data-bf="cancelled"]'));
    ok(!$('[data-bf="cancelled"]').checked, 'booking: not cancelled by default');
    click($('[data-bf="cancelled"]'));
    ok(await waitFor(() => $('[data-bf="cancelled"]')?.checked && $('[data-bf="cost"]').value === '0' && $('[data-bf="revenue"]').value === '0'), 'booking: ticking Cancelled sets the money to 0');
    type($('[data-bf="cost"]'), '15'); // a cancellation fee
    click($('[data-act="booking-save"]'));
    ok(await waitFor(() => stayRow()?.querySelector('.svc-status')?.textContent === 'Cancelled'), 'booking: the row shows Cancelled');
    click(stayRow());
    await waitFor(() => $('[data-bf="cancelled"]')?.checked);
    click($('[data-bf="cancelled"]'));
    await waitFor(() => !$('[data-bf="cancelled"]').checked);
    type($('[data-bf="cost"]'), '80'); type($('[data-bf="revenue"]'), '4500');
    click($('[data-act="booking-save"]'));
    ok(await waitFor(() => !stayRow()?.querySelector('.svc-status') && stayRow()?.textContent.includes('EGP 4,500.00')), 'booking: unticked, it is a normal booking again');
  }

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
  for (const name of [NAME, '<IMG', 'SMOKE TODAY', 'SMOKE GAP TRIGGER', 'PORT MOVE']) {
    const row = $$('#tbody tr').find((t) => t.textContent.includes(name));
    if (!row) continue;
    click(row.querySelector('[data-act="del-vessel-row"]')); // the Delete button in the table row
    await waitFor(() => !$$('#tbody tr').some((t) => t.dataset.id === row.dataset.id));
  }
  ok(await waitFor(() => !$$('#tbody tr').some((t) => /UI SMOKE|SMOKE TODAY|SMOKE GAP|<IMG|PORT MOVE/.test(t.textContent))), 'test vessels deleted (the list reloads after the dialog closes)');
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
  if (ROLE === 'admin') {
    // Only admins delete ships; a ship with no vessels left goes (the port user's ones stay as data).
    const { ships } = await (await w.fetch('/api/ships/?limit=200')).json();
    const mine = ships.filter((s) => /^(SMOKE|UI SMOKE|<IMG|PORT MOVE)/.test(s.name) && s.calls === 0);
    let gone = 0;
    for (const s of mine) if ((await w.fetch(`/api/ships/${s.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': meta() } })).ok) gone += 1;
    ok(gone === mine.length, 'ships: test ships without vessels deleted');
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
    // The sidebar folders: Reports closes, and opening one of its pages opens it again.
    const reports = $('#nav .nav-group[data-group="reports"]');
    ok($$('#nav .nav-group').map((g) => g.dataset.group).join() === 'marine,operation,reports,master', 'sidebar: Marine, Operation, Reports, Master data folders');
    await go('vessels');
    click(reports.querySelector('[data-act="toggle-nav-group"]'));
    ok(reports.querySelector('.nav-group-items').hidden && reports.querySelector('.nav-group-head').getAttribute('aria-expanded') === 'false', 'sidebar: a folder closes');
    await go('dashboard');
    ok(!reports.querySelector('.nav-group-items').hidden, 'sidebar: going to a page opens its folder');
    ok($('#d-from') && !$('#dash-year') && $('#d-from').value === $('#f-from').value, 'dashboard uses the same date range');
    ok(await waitFor(() => $$('#opr-cards .opr-card').length > 0) && $('#chart-vessels svg .donut-slice'), 'dashboard: the OPR donut and OPR cards render');
    const dashTab = (view) => $(`[data-act="dash-view"][data-view="${view}"]`);
    const dashShown = () => $$('[data-dash-view]').filter((el) => !el.hidden).map((el) => el.dataset.dashView).join();
    ok(['agents', 'opr', 'customers', 'overview'].every((v) => dashTab(v)), 'dashboard: four views (Agent jobs, OPR, Customers, Overview)');
    click(dashTab('customers'));
    ok(dashShown() === 'customers' && dashTab('customers').getAttribute('aria-pressed') === 'true' && $('#d-agent').hidden, 'dashboard: Customers shows only its view, without the agent filter');
    ok(await waitFor(() => $('#tbl-customers').textContent.includes('Blue Owners')) && $('#heat-customers td.heat'), 'dashboard: jobs per customer and the POC / port table');
    ok(w.localStorage.getItem('sheet.dashboard.view') === 'customers', 'dashboard: the view is remembered');
    click(dashTab('opr'));
    ok(dashShown() === 'opr' && $('#d-opr').hidden && !$('#d-agent').hidden, 'dashboard: OPR shows its view, without the OPR filter');
    click(dashTab('agents'));
    ok(dashShown() === 'agents' && $('#hl-agents').textContent.includes('jobs'), 'dashboard: Agent jobs has its headline');
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
    ok($$('#tbl-status tbody tr').map((r) => r.firstElementChild.textContent).join() === 'In progress,Completed,Cancelled,Open lines,Closed lines', 'dashboard: service status table per month');
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

    // Plain-table Excel files for other programs: each page's button sends that page's filters (no paging) and
    // downloads; All data sends the Dashboard's range and port.
    const fetched = [];
    const realFetch = w.fetch;
    w.fetch = async (url, options) => {
      const response = await realFetch(url, options);
      if (String(url).includes('/api/export/')) fetched.push({ url: String(url), status: response.status });
      return response;
    };
    if (!w.URL.createObjectURL) w.URL.createObjectURL = () => 'blob:smoke';
    if (!w.URL.revokeObjectURL) w.URL.revokeObjectURL = () => {};
    const exported = async (button) => {
      const before = fetched.length;
      click(button);
      await waitFor(() => fetched.length > before);
      return fetched[fetched.length - 1] || { url: '', status: 0 };
    };
    const monthStart = `${today.slice(0, 8)}01`;
    // All data allows at most 24 months. Let the last range change finish loading first: its reply redraws the
    // (unfocused) date boxes and would put the old From back while the new dates wait out the typing pause.
    await sleep(1500);
    await waitFor(() => $('#status-text').textContent === 'Synced');
    type($('#d-from'), monthStart); type($('#d-to'), today);
    await waitFor(() => $('#f-from').value === monthStart && $('#f-to').value.slice(0, 8) === today.slice(0, 8));
    let got = await exported($('[data-act="dashboard-data-export"]'));
    ok(got.status === 200 && got.url.includes('/api/export/all/') && got.url.includes(`from=${monthStart}`) && got.url.includes(`to=${today.slice(0, 8)}`), `export: All data downloads for the Dashboard range`); // the Dashboard takes whole months
    type($('#d-from'), rangeFrom); type($('#d-to'), rangeTo);
    await waitFor(() => $('#f-from').value === rangeFrom && $('#f-to').value === rangeTo);
    for (const [page, key] of [['vessels', 'vessels'], ['hotels', 'hotels'], ['transport', 'transfers'], ['closures', 'closures'], ['disposal', 'disposal'], ['calculations', 'calculations']]) {
      await go(page);
      if (page === 'hotels') {
        type($('#h-search'), 'ahmed');
        await sleep(400);
      }
      got = await exported($(`#page-${page} [data-act="page-export"]`));
      ok(got.status === 200 && got.url.includes(`/api/export/${key}/`) && !/[?&]page(_size)?=/.test(got.url), `export: ${page} Excel downloads all its filtered rows`);
      if (page === 'hotels') {
        ok(got.url.includes('q=ahmed'), 'export: the hotels file uses the page search');
        type($('#h-search'), '');
      }
    }
    w.fetch = realFetch;
    await go('dashboard');
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
      // seed_demo's port Users have History: only their own ports' records, never people / shared records.
      ok(historyStatus === 200, `history: ${ROLE} (History ticked) may read it`);
      const mine = JSON.parse($('#me-data').textContent).ports;
      const { records } = await (await w.fetch('/api/history/?page_size=100')).json();
      ok(records.every((r) => mine.includes(r.port) && r.object_type !== 'profile'), `history: ${ROLE} sees only their ports' records`);
      ok(await go('history'), `history: ${ROLE} has the History page`);
    }
    await checkAccounts();
    await checkPorts();
  }

  /** Accounts: an Admin (seed_demo's admin) adds one, changes its ports, turns it off and on; others get 403. */
  async function checkAccounts() {
    const status = (await w.fetch('/api/accounts/')).status;
    if (ROLE !== 'admin') {
      ok(status === 403, `accounts: ${ROLE} gets 403 from the accounts API`);
      ok(!$('#nav [data-page="accounts"]') && !$('#page-accounts'), `accounts: ${ROLE} has no Accounts page`);
      return;
    }
    ok(status === 200, 'accounts: the superuser may read the accounts');
    await go('accounts');
    const acRow = (name) => $$('#ac-tbody tr').find((r) => r.children[0].textContent === name);
    ok(await waitFor(() => acRow('alex')), 'accounts: the page lists alex');
    const username = `smoke${Date.now().toString(36)}`;
    click($('[data-act="account-new"]'));
    ok(await waitFor(() => $('#account-form')), 'accounts: + Add account opens the dialog');
    type($('#account-form [name=username]'), username);
    type($('#account-form [name=first_name]'), 'Smoke');
    const tick = (key) => $(`#account-form [data-port="${key}"]`);
    ok(!!$('#account-form [name=home_port]') && ['alexandria', 'portsaid', 'damietta', 'suez'].every((k) => tick(k)),
      'accounts: the dialog has Home port and Extra ports');
    type($('#account-form [name=home_port]'), 'damietta');
    ok(tick('damietta').checked && tick('damietta').disabled, "accounts: the home port's tick is on and fixed");
    tick('portsaid').checked = true;
    type($('#account-form [name=password]'), 'Smoke-test-password-2026');
    click($('[data-act="account-save"]'));
    ok(await waitFor(() => acRow(username)?.textContent.includes('Damietta (home), Port Said') && acRow(username).textContent.includes('Waiting')),
      'accounts: a new account is listed with its ports, waiting for its Authenticator');
    click(acRow(username));
    ok(await waitFor(() => $('#account-form') && !$('#account-form [name=password]')), 'accounts: an account opens without a password box');
    type($('#account-form [name=home_port]'), 'suez');
    tick('damietta').checked = false;
    tick('portsaid').checked = false;
    // Template: Branch manager fills in every tick (the Accounts employee template was cancelled, 2026-11-25).
    const perm = (key) => $(`#account-form [data-perm="${key}"]`);
    const page = (key) => $(`#account-form [data-tick-page="${key}"]`);
    ok(perm('history.view').disabled && page('calculations').disabled && page('vessels').checked && page('vessels').disabled,
      'accounts: ticks that need See money are disabled; Vessels is always on');
    ok($$('#account-form .tick-all').map((l) => l.textContent.trim()).join('|')
      === 'All|Marine|Operation|Reports|Master data|Marine|Operation|General', 'accounts: Pages and Can come in groups, each with All');
    const opAll = $('#account-form [data-all^="perm:operation."]');
    opAll.checked = true;
    opAll.dispatchEvent(new w.Event('change', { bubbles: true }));
    ok(perm('operation.edit').checked && perm('operation.master').checked && page('op_vessels').checked && !perm('vessels.edit').checked,
      "accounts: Operation's All ticks the Operation work and the Vessel Data page it needs, not Marine");
    type($('#account-form [name=template]'), 'manager');
    ok(perm('money.view').checked && perm('accounting.close').checked && perm('vessels.edit').checked
      && page('calculations').checked && page('history').checked && page('history').disabled
      && $$('#account-form [data-all]').every((a) => a.checked),
      'accounts: the Branch manager template ticks every box (and every All shows ticked)');
    click($('[data-act="account-save"]'));
    ok(await waitFor(() => acRow(username)?.children[2].textContent === 'Suez (home)'), 'accounts: the ports change');
    ok(acRow(username).children[3].textContent === '19 of 19', 'accounts: the Can column counts the permissions');
    click(acRow(username));
    ok(await waitFor(() => $('#account-form') && $('#account-form [data-perm="exports"]')?.checked
      && $('#account-form [data-perm="vessels.delete"]').checked), 'accounts: the ticks are saved');
    perm('money.view').checked = false;
    perm('money.view').dispatchEvent(new w.Event('change', { bubbles: true }));
    ok(!perm('history.view').checked && !page('calculations').checked && !perm('accounting.close').checked,
      'accounts: unticking See money unticks what needs it');
    closeModal();
    click(acRow(username));
    await waitFor(() => $('[data-act="account-toggle"]'));
    click($('[data-act="account-toggle"]'));
    ok(await waitFor(() => acRow(username)?.classList.contains('inactive') && acRow(username).textContent.endsWith('Off')), 'accounts: Turn off greys it');
    click(acRow(username));
    await waitFor(() => $('[data-act="account-toggle"]')?.textContent === 'Turn on');
    click($('[data-act="account-toggle"]'));
    ok(await waitFor(() => acRow(username) && !acRow(username).classList.contains('inactive')), 'accounts: Turn on brings it back');
    click(acRow('admin'));
    ok(await waitFor(() => $('#account-form') && !$('[data-act="account-save"]') && !$('[data-act="account-toggle"]')),
      'accounts: a superuser account is read-only here');
    closeModal();
  }

  /** Ports: an Admin lists the four ports, adds one, renames it and turns it off (ports are never deleted). */
  async function checkPorts() {
    const status = (await w.fetch('/api/ports/')).status;
    if (ROLE !== 'admin') {
      ok(status === 403 && !$('#nav [data-page="ports"]') && !$('#page-ports'), `ports: ${ROLE} has no Ports page`);
      return;
    }
    await go('ports');
    const ptRow = (name) => $$('#pt-tbody tr').find((r) => r.children[0].textContent === name);
    ok(await waitFor(() => ['Alexandria', 'Port Said', 'Damietta', 'Suez'].every((n) => ptRow(n))), 'ports: the page lists the four ports');
    ok(ptRow('Alexandria').children[1].textContent === 'alexandria' && Number(ptRow('Alexandria').children[3].textContent) > 0,
      'ports: a row shows the key and its vessels');
    const name = `Smoke${Date.now().toString(36)}`;
    click($('[data-act="port-new"]'));
    await waitFor(() => $('#port-form'));
    type($('#port-form [name=name]'), name);
    click($('[data-act="port-save"]'));
    ok(await waitFor(() => ptRow(name)?.children[2].textContent === 'On'), 'ports: + Add port adds a turned-on port');
    click(ptRow(name));
    await waitFor(() => $('#port-form'));
    type($('#port-form [name=name]'), `${name} R`);
    click($('[data-act="port-save"]'));
    ok(await waitFor(() => ptRow(`${name} R`)), 'ports: a port is renamed');
    click(ptRow(`${name} R`));
    await waitFor(() => $('[data-act="port-toggle"]')?.textContent === 'Turn off');
    click($('[data-act="port-toggle"]'));
    ok(await waitFor(() => ptRow(`${name} R`)?.classList.contains('inactive') && ptRow(`${name} R`).children[2].textContent === 'Off'),
      'ports: Turn off greys it');
  }

  function finish() {
    ok(jsErrors.length === 0, `no JavaScript errors${jsErrors.length ? ': ' + jsErrors.join('; ') : ''}`);
    console.log(failures ? `\n${failures} FAILED` : '\nALL PASSED');
    process.exit(failures ? 1 : 0);
  }
})().catch((e) => { console.error(e); process.exit(1); });
