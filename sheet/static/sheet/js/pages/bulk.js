// Bulk add page: paste many vessels, then fix them in an editable table, then create them in one go.
import { api } from '../api.js';
import { setStatus } from '../feedback.js';
import { ME } from '../config.js';
import { checkRows, parseBulk } from '../bulkParsing.js';
import { optionChoicesEl, portOptionEls } from '../components.js';
import { refreshAfterChange, widenRangeTo } from '../data.js';
import { h, setChildren } from '../dom.js';
import { navigate } from '../router.js';
import { fillQuickSelects } from '../render/list.js';
import { optionValues } from '../state.js';
import { $, $$, today } from '../util.js';

const MAX_ROWS = 200; // keep in step with BULK_MAX_ROWS in sheet/constants.py
const CHECK_DELAY_MS = 300; // ask the server about duplicates once edits pause
const LIMIT_MESSAGE = `The limit is ${MAX_ROWS} vessels at a time. Split it into smaller batches.`;

let rows = [];          // the table's rows (see bulkParsing.checkRows for the shape)
let edited = false;     // has the user changed the table since the last Preview?
let checking = false;   // is a duplicate check due or on its way?
let checkFailed = false; // did the last duplicate check fail? (Create stays off until one succeeds)
let saving = false;     // is Create on its way? (a double click must not create twice)
let checkTimer;
let checkTicket = 0;    // bumped by every change to the table, so older check answers are ignored

const showError = (message) => {
  const box = $('#bk-error');
  box.textContent = message;
  box.hidden = !message;
};

const known = () => ({
  opr: new Set(optionValues('opr')), poc: new Set(optionValues('poc')), agent: new Set(optionValues('agent')),
});

const defaults = () => ({ date: $('#bk-date').value, opr: $('#bk-opr').value, poc: $('#bk-poc').value, agent: $('#bk-agent').value });

const targetPort = () => (ME.isAdmin ? $('#bk-port').value : ME.port);

export function initBulkPage() {
  if (!$('#bk-date').value) $('#bk-date').value = today();
  if (ME.isAdmin && !$('#bk-port').options.length) {
    setChildren($('#bk-port'), portOptionEls());
    $('#bk-port-wrap').hidden = false;
  }
  fillQuickSelects(); // after the port select exists, so the default lists follow its port
}

/* ---- drawing ---- */

const rowState = (row) => {
  if (row.errors.length) return { mark: '✗', css: 'st-bad', trCss: 'row-error', text: row.errors.join(' ') };
  if (row.skip) return { mark: '↷', css: 'st-warn', trCss: 'row-skip', text: row.warnings.join(' ') };
  if (row.warnings.length) return { mark: '⚠', css: 'st-warn', trCss: 'row-warn', text: row.warnings.join(' ') };
  return { mark: '✓', css: 'st-ok', trCss: '', text: 'Ready' };
};

const readyRows = () => rows.filter((r) => !r.errors.length && !r.skip);

function summaryEls() {
  const failed = rows.filter((r) => r.errors.length).length;
  const skipped = rows.filter((r) => r.skip).length;
  const ready = readyRows().length;
  const canCreate = ready && !failed && !checking && !checkFailed && !saving;
  const part = (cls, count, text) => h('span', { class: cls }, h('b', null, count), text);
  return [
    part('st-ok', ready, ' ready'),
    skipped ? part('st-warn', skipped, ` duplicate${skipped === 1 ? '' : 's'} skipped`) : null,
    failed ? part('st-bad', failed, ' with errors — fix them in the table or remove them') : null,
    checking ? h('span', { class: 'none' }, 'Checking for duplicates…') : null,
    checkFailed && !checking ? h('span', { class: 'st-bad' }, "Couldn't check for duplicates — edit a cell or press Preview to try again.") : null,
    saving ? h('span', { class: 'none' }, 'Saving…') : null,
    h('button', { class: 'btn primary', dataset: { act: 'bulk-create' }, disabled: !canCreate }, `Create ${ready} vessel${ready === 1 ? '' : 's'}`),
  ];
}

function rowEl(row, i) {
  const st = rowState(row);
  const select = (kind) => h('select', { class: 'select', dataset: { f: kind }, attrs: { 'aria-label': kind.toUpperCase() } },
    optionChoicesEl(kind, row[kind], targetPort()));
  return h('tr', { class: st.trCss, dataset: { i } },
    h('td', { class: 'num' }, i + 1),
    h('td', null, h('input', { class: 'input', dataset: { f: 'name' }, attrs: { maxlength: 120, 'aria-label': 'Vessel name' }, value: row.name })),
    h('td', null, h('input', { class: 'input', dataset: { f: 'date' }, attrs: { type: 'date', 'aria-label': 'Date' }, value: row.date })),
    h('td', null, select('opr')), h('td', null, select('poc')), h('td', null, select('agent')),
    h('td', { class: `bk-check ${st.css}` }, `${st.mark} ${st.text}`),
    h('td', null, h('button', { class: 'btn ghost small', dataset: { act: 'bulk-del-row', i }, attrs: { title: 'Remove this row' } }, '🗑')));
}

/** Draw the whole table (after Preview, adding, removing or "Set on all rows"). */
function renderPreview() {
  const box = $('#bk-preview');
  if (!rows.length) {
    setChildren(box);
    return;
  }
  const allSelect = (kind) => h('select', { class: 'select', id: `bk-all-${kind}`, attrs: { 'aria-label': `${kind.toUpperCase()} for all rows` } },
    optionChoicesEl(kind, '', targetPort()));
  const headers = ['#', 'Vessel', 'Date', 'OPR', 'POC', 'Agent', 'Check', ''].map((label) => h('th', null, label));
  setChildren(box,
    h('div', { class: 'bulk-all' }, h('span', null, 'Set on all rows:'), ' ',
      h('input', { class: 'input', id: 'bk-all-date', attrs: { type: 'date', 'aria-label': 'Date for all rows' } }), ' ',
      allSelect('opr'), ' ', allSelect('poc'), ' ', allSelect('agent'), ' ',
      h('button', { class: 'btn ghost small', dataset: { act: 'bulk-apply-all' } }, 'Apply')),
    h('div', { class: 'bulk-summary', id: 'bk-summary' }, summaryEls()),
    h('div', { class: 'table-wrap' }, h('table', { class: 'bulk-table bulk-edit' },
      h('thead', null, h('tr', null, headers)),
      h('tbody', null, rows.map(rowEl)))),
    h('button', { class: 'btn ghost small', dataset: { act: 'bulk-add-row' } }, '+ Add row'));
}

/** Re-run the checks and update only the check cells and the summary, so the input being typed in keeps focus. */
function updateChecks() {
  checkRows(rows, known());
  $$('#bk-preview tbody tr').forEach((tr) => {
    const row = rows[Number(tr.dataset.i)];
    if (!row) return;
    const st = rowState(row);
    tr.className = st.trCss;
    const cell = tr.querySelector('.bk-check');
    cell.className = `bk-check ${st.css}`;
    cell.textContent = `${st.mark} ${st.text}`;
  });
  const summary = $('#bk-summary');
  if (summary) setChildren(summary, summaryEls());
}

/* ---- duplicates already saved (server) ---- */

/** Ask the server which rows already exist. Only the answer for the table as it is now is used. */
async function checkExisting() {
  const ticket = checkTicket;
  if (!rows.length) {
    checking = false;
    return;
  }
  const sent = rows.slice(); // the answer's indexes refer to these rows, whatever happens to the table meanwhile
  checking = true;
  updateChecks();
  let existing;
  try {
    ({ existing } = await api('/api/vessels/bulk/check/', 'POST', {
      rows: sent.map(({ name, date }) => ({ name, date })),
      port: targetPort(),
    }));
  } catch {
    if (ticket !== checkTicket) return; // the table changed meanwhile; a newer check is coming
    checkFailed = true;
    checking = false;
    updateChecks();
    return;
  }
  if (ticket !== checkTicket) return;
  const found = new Set(existing);
  sent.forEach((row, i) => { row.exists = found.has(i); });
  checkFailed = false;
  checking = false;
  updateChecks();
}

/** The table changed: forget any check on its way and run a new one once edits pause. */
function scheduleCheck() {
  clearTimeout(checkTimer);
  checkTicket += 1;
  checking = true;
  updateChecks();
  checkTimer = setTimeout(checkExisting, CHECK_DELAY_MS);
}

/* ---- actions ---- */

export async function previewBulk() {
  if (edited && rows.length && !confirm('Replace the rows below with the pasted text?')) return;
  showError('');
  const parsed = parseBulk($('#bk-text').value, defaults(), [], known());
  if (!parsed.length) {
    showError('Paste at least one vessel first.');
    return;
  }
  if (parsed.length > MAX_ROWS) {
    showError(`That is ${parsed.length} lines; the limit is ${MAX_ROWS} at a time. Split it into smaller batches.`);
    return;
  }
  rows = parsed;
  edited = false;
  checkFailed = false;
  clearTimeout(checkTimer);
  checkTicket += 1;
  checking = true;
  renderPreview();
  await checkExisting();
}

/** A change in a table cell: store it, re-check, and ask the server about duplicates after a pause. */
export function onPreviewEdit(event) {
  const input = event.target;
  const tr = input.closest('tr[data-i]');
  if (!tr || !input.dataset.f) return;
  const row = rows[Number(tr.dataset.i)];
  const field = input.dataset.f;
  let value = input.value;
  if (field === 'name') {
    value = value.toUpperCase();
    if (input.value !== value) {
      const { selectionStart, selectionEnd } = input;
      input.value = value;
      input.setSelectionRange?.(selectionStart, selectionEnd);
    }
  }
  // Browsers also fire "change" when you leave a cell; with nothing changed, leave everything as it is
  // (otherwise the click that left the cell, e.g. on Create, would land on a button being redrawn).
  if (row[field] === value && !(field === 'date' && row.badDate)) return;
  row[field] = value;
  if (field === 'date') row.badDate = '';
  edited = true;
  scheduleCheck();
}

export function addBulkRow() {
  if (rows.length >= MAX_ROWS) {
    showError(LIMIT_MESSAGE);
    return;
  }
  const d = defaults();
  rows.push({ line: 0, name: '', date: d.date, opr: d.opr, poc: d.poc, agent: d.agent, errors: [], warnings: [], skip: false });
  edited = true;
  checkRows(rows, known());
  renderPreview();
  scheduleCheck();
  $(`#bk-preview tr[data-i="${rows.length - 1}"] [data-f=name]`)?.focus();
}

export function removeBulkRow(index) {
  rows.splice(index, 1);
  edited = true;
  checkRows(rows, known());
  renderPreview();
  scheduleCheck();
}

/** "Set on all rows": every chosen value overwrites that column; empty choices are ignored. */
export function applyToAllRows() {
  const values = { date: $('#bk-all-date').value, opr: $('#bk-all-opr').value, poc: $('#bk-all-poc').value, agent: $('#bk-all-agent').value };
  const chosen = Object.entries(values).filter(([, v]) => v);
  if (!chosen.length) return;
  for (const row of rows) {
    for (const [field, value] of chosen) row[field] = value;
    if (values.date) row.badDate = '';
  }
  edited = true;
  checkRows(rows, known());
  renderPreview();
  scheduleCheck();
}

/** Admins: the duplicate marks depend on the target port, so re-check when it changes. */
export function onBulkPortChange() {
  fillQuickSelects(); // the default OPR / POC / Agent lists follow the port
  if (!rows.length) return;
  renderPreview(); // so do the table's lists
  scheduleCheck();
}

let created = { from: '', to: '' };

/** "View them": widen the date range to cover the vessels just added, then show the Vessels page. */
export async function viewCreated() {
  if (created.from) await widenRangeTo(created.from, created.to);
  navigate('vessels');
}

export async function createBulk() {
  const toCreate = readyRows();
  if (!toCreate.length || checking || checkFailed || saving || rows.some((r) => r.errors.length)) return;
  const payload = { rows: toCreate.map(({ name, date, opr, poc, agent }) => ({ name, date, opr, poc, agent })) };
  if (ME.isAdmin) payload.port = $('#bk-port').value;
  saving = true;
  updateChecks();
  setStatus('saving', 'Saving…');
  try {
    const { vessels } = await api('/api/vessels/bulk/', 'POST', payload);
    setStatus('ok', `Added ${vessels.length} ✓`);
    rows = [];
    edited = false;
    clearTimeout(checkTimer);
    checkTicket += 1;
    checking = false;
    $('#bk-text').value = '';
    const dates = vessels.map((v) => v.date).sort();
    created = { from: dates[0] || '', to: dates[dates.length - 1] || '' };
    await refreshAfterChange();
    setChildren($('#bk-preview'), h('div', { class: 'ok-box' },
      `✅ Added ${vessels.length} vessel${vessels.length === 1 ? '' : 's'}. `,
      h('a', { href: '#vessels', dataset: { act: 'bulk-view' } }, 'View them')));
  } catch (error) {
    setStatus('error', 'Failed');
    showError(error.message); // nothing was saved: the server is all-or-nothing
  } finally {
    saving = false;
    if (rows.length) updateChecks();
  }
}

export function clearBulk() {
  rows = [];
  edited = false;
  clearTimeout(checkTimer);
  checkTicket += 1;
  checking = false;
  checkFailed = false;
  $('#bk-text').value = '';
  showError('');
  renderPreview();
}
