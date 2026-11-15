// Bulk add page: paste many vessels, then fix them in an editable table, then create them in one go.
import { api } from '../api.js';
import { setStatus } from '../feedback.js';
import { ME, PORTS } from '../config.js';
import { checkRows, parseBulk } from '../bulkParsing.js';
import { optionChoices } from '../components.js';
import { refreshAfterChange, widenRangeTo } from '../data.js';
import { navigate } from '../router.js';
import { fillQuickSelects } from '../render/list.js';
import { optionValues } from '../state.js';
import { $, $$, esc, today } from '../util.js';

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
  box.style.display = message ? 'block' : 'none';
};

const known = () => ({
  opr: new Set(optionValues('opr')), poc: new Set(optionValues('poc')), agent: new Set(optionValues('agent')),
});

const defaults = () => ({ date: $('#bk-date').value, opr: $('#bk-opr').value, poc: $('#bk-poc').value, agent: $('#bk-agent').value });

const targetPort = () => (ME.isAdmin ? $('#bk-port').value : ME.port);

export function initBulkPage() {
  fillQuickSelects();
  if (!$('#bk-date').value) $('#bk-date').value = today();
  if (ME.isAdmin && !$('#bk-port').options.length) {
    $('#bk-port').innerHTML = PORTS.map((p) => `<option value="${p.key}">${p.label}</option>`).join('');
    $('#bk-port-wrap').style.display = '';
  }
}

/* ---- drawing ---- */

const rowState = (row) => {
  if (row.errors.length) return { mark: '✗', css: 'st-bad', trCss: 'row-error', text: row.errors.join(' ') };
  if (row.skip) return { mark: '↷', css: 'st-warn', trCss: 'row-skip', text: row.warnings.join(' ') };
  if (row.warnings.length) return { mark: '⚠', css: 'st-warn', trCss: 'row-warn', text: row.warnings.join(' ') };
  return { mark: '✓', css: 'st-ok', trCss: '', text: 'Ready' };
};

const readyRows = () => rows.filter((r) => !r.errors.length && !r.skip);

function summaryHtml() {
  const failed = rows.filter((r) => r.errors.length).length;
  const skipped = rows.filter((r) => r.skip).length;
  const ready = readyRows().length;
  const canCreate = ready && !failed && !checking && !checkFailed && !saving;
  return `<span class="st-ok"><b>${ready}</b> ready</span>
    ${skipped ? `<span class="st-warn"><b>${skipped}</b> duplicate${skipped === 1 ? '' : 's'} skipped</span>` : ''}
    ${failed ? `<span class="st-bad"><b>${failed}</b> with errors — fix them in the table or remove them</span>` : ''}
    ${checking ? '<span class="none">Checking for duplicates…</span>' : ''}
    ${checkFailed && !checking ? "<span class=\"st-bad\">Couldn't check for duplicates — edit a cell or press Preview to try again.</span>" : ''}
    ${saving ? '<span class="none">Saving…</span>' : ''}
    <button class="btn primary" data-act="bulk-create" ${canCreate ? '' : 'disabled'}>Create ${ready} vessel${ready === 1 ? '' : 's'}</button>`;
}

function rowHtml(row, i) {
  const st = rowState(row);
  const select = (kind) => `<select class="select" data-f="${kind}" aria-label="${kind.toUpperCase()}">${optionChoices(kind, row[kind])}</select>`;
  return `<tr data-i="${i}" class="${st.trCss}">
    <td class="num">${i + 1}</td>
    <td><input class="input" data-f="name" value="${esc(row.name)}" maxlength="120" aria-label="Vessel name"></td>
    <td><input class="input" type="date" data-f="date" value="${esc(row.date)}" aria-label="Date"></td>
    <td>${select('opr')}</td><td>${select('poc')}</td><td>${select('agent')}</td>
    <td class="bk-check ${st.css}">${st.mark} ${esc(st.text)}</td>
    <td><button class="btn ghost small" data-act="bulk-del-row" data-i="${i}" title="Remove this row">🗑</button></td></tr>`;
}

/** Draw the whole table (after Preview, adding, removing or "Set on all rows"). */
function renderPreview() {
  const box = $('#bk-preview');
  if (!rows.length) {
    box.innerHTML = '';
    return;
  }
  const allSelect = (kind) => `<select class="select" id="bk-all-${kind}" aria-label="${kind.toUpperCase()} for all rows">${optionChoices(kind, '')}</select>`;
  box.innerHTML = `
    <div class="bulk-all"><span>Set on all rows:</span>
      <input class="input" type="date" id="bk-all-date" aria-label="Date for all rows">
      ${allSelect('opr')} ${allSelect('poc')} ${allSelect('agent')}
      <button class="btn ghost small" data-act="bulk-apply-all">Apply</button></div>
    <div class="bulk-summary" id="bk-summary">${summaryHtml()}</div>
    <div class="table-wrap"><table class="bulk-table bulk-edit"><thead><tr><th>#</th><th>Vessel</th><th>Date</th><th>OPR</th><th>POC</th><th>Agent</th><th>Check</th><th></th></tr></thead>
    <tbody>${rows.map(rowHtml).join('')}</tbody></table></div>
    <button class="btn ghost small" data-act="bulk-add-row">+ Add row</button>`;
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
  if (summary) summary.innerHTML = summaryHtml();
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
  if (rows.length) scheduleCheck();
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
    $('#bk-preview').innerHTML = `<div class="ok-box">✅ Added ${vessels.length} vessel${vessels.length === 1 ? '' : 's'}. <a href="#vessels" data-act="bulk-view">View them</a></div>`;
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
