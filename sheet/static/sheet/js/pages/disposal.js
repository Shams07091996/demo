// The Garbage & Sludge page: the vessels of a date range and port, each with its garbage (m³) and sludge (t). A
// quantity saves when its box is left; the server works out revenue / cost / profit in EGP and USD (/api/disposal/).
import { api, mutate } from '../api.js';
import { closedNoteEl, portOptionEls } from '../components.js';
import { ME } from '../config.js';
import { h, icon, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { state } from '../state.js';
import { $, dmy, fmt } from '../util.js';

const DATE_DELAY_MS = 400;
const typingYear = (iso) => iso && Number(iso.slice(0, 4)) < 1900;
const SHOW = [['all', 'All'], ['with', 'With garbage or sludge'], ['none', 'Not entered yet'], ['hidden', 'Hidden']];

let filter = null; // starts from the Vessels page's range and port the first time the page opens
let data = { rows: [], totals: null };
let ticket = 0;
let totalsTicket = 0; // a full load also brings the totals, so it cancels any totals-only reload still on its way
let wired = false;

const money = (value) => (value === null || value === undefined ? '—' : fmt(value));
const pair = (egp, usd, cls = '') => h('td', { class: `num ${cls}`.trim() },
  `LE ${money(egp)}`, h('div', { class: 'none calc-note' }, `USD ${money(usd)}`));

function quantityCell(row, kind) {
  const value = row[kind];
  if (!ME.canEdit || row.hidden || row.closed) return h('td', { class: 'num' }, value === null ? '—' : String(value));
  return h('td', { class: 'num' }, h('input', {
    class: 'input qty',
    attrs: { type: 'number', step: 'any', min: 0, name: kind, 'aria-label': kind === 'garbage' ? 'Garbage m³' : 'Sludge t' },
    dataset: { qty: kind, id: row.vessel.id },
    value: value === null ? '' : String(value),
  }));
}

function flags(row) {
  return [
    row.price_missing ? h('div', { class: 'warn-text calc-note' }, 'No price for this port and month') : null,
    row.rate_missing ? h('div', { class: 'warn-text calc-note' }, 'No exchange rate for this month') : null,
  ];
}

function rowEl(row) {
  const action = row.closed ? closedNoteEl() : !ME.canEdit ? null : row.hidden
    ? h('button', { class: 'btn ghost small', dataset: { act: 'disposal-show', id: row.vessel.id } }, 'Bring back')
    : h('button', { class: 'btn ghost small', dataset: { act: 'disposal-hide', id: row.vessel.id }, attrs: { title: 'No garbage or sludge' } }, icon('ban'), ' Hide');
  return h('tr', { dataset: { vessel: row.vessel.id } },
    h('td', null, dmy(row.vessel.date)),
    h('td', null, h('a', { href: '#disposal', dataset: { act: 'summary', id: row.vessel.id } }, row.vessel.name), flags(row)),
    h('td', null, row.vessel.opr || '—'),
    ME.multiPort ? h('td', null, row.vessel.port_label) : null,
    quantityCell(row, 'garbage'),
    quantityCell(row, 'sludge'),
    pair(row.revenue_egp, row.revenue_usd),
    pair(row.cost_egp, row.cost_usd),
    pair(row.profit_egp, row.profit_usd, row.profit_egp < 0 ? 'neg' : ''),
    h('td', null, action));
}

function totalsEl(t) {
  if (!t) return null;
  const flagged = t.price_missing_rows + t.rate_missing_rows;
  return [
    `Revenue LE ${money(t.revenue_egp)} / USD ${money(t.revenue_usd)} · Cost LE ${money(t.cost_egp)} / USD ${money(t.cost_usd)}`
      + ` · Profit LE ${money(t.profit_egp)} / USD ${money(t.profit_usd)}`,
    flagged ? [' ', h('span', { class: 'warn-text' }, icon('alert'),
      ` ${flagged} vessel${flagged === 1 ? '' : 's'} without a price or rate (left out)`)] : null,
  ];
}

function render() {
  const heads = ['Date', 'Vessel', 'OPR', ...(ME.multiPort ? ['Port'] : []), 'Garbage m³', 'Sludge t', 'Revenue', 'Cost', 'Profit', ''];
  setChildren($('#g-head'), h('tr', null, heads.map((title) => h('th', null, title))));
  setChildren($('#g-tbody'), data.rows.map(rowEl));
  $('#g-empty').hidden = data.rows.length > 0;
  setChildren($('#g-totals'), totalsEl(data.totals));
  const from = $('#g-from');
  const to = $('#g-to');
  if (document.activeElement !== from) from.value = filter.from;
  if (document.activeElement !== to) to.value = filter.to;
  $('#g-show').value = filter.show;
}

function params() {
  const values = { from: filter.from, to: filter.to, port: filter.port === 'ALL' ? '' : filter.port, show: filter.show };
  return new URLSearchParams(Object.entries(values).filter(([, v]) => v));
}

async function load() {
  wire();
  const mine = ++ticket;
  totalsTicket += 1;
  let answer;
  try {
    answer = await api(`/api/disposal/?${params()}`);
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
    return;
  }
  if (mine !== ticket) return; // a newer request is on its way
  data = answer;
  render();
}

function setFilter(patch) {
  Object.assign(filter, patch);
  return load();
}

/** Put a saved row's new figures on the page without touching its quantity boxes (one may be being typed in). */
function patchRow(row) {
  data.rows = data.rows.map((r) => (r.vessel.id === row.vessel.id ? row : r));
  const tr = $(`#g-tbody tr[data-vessel="${row.vessel.id}"]`);
  if (!tr) return;
  const fresh = rowEl(row);
  [...tr.children].forEach((cell, i) => {
    if (!cell.querySelector('input')) cell.replaceWith(fresh.children[i].cloneNode(true));
  });
}

/** Reload only the totals (the rows on screen are already up to date, and may hold a box being typed in). */
async function loadTotals() {
  const mine = ++totalsTicket;
  try {
    const answer = await api(`/api/disposal/?${params()}`);
    if (mine !== totalsTicket) return;
    data.totals = answer.totals;
    setChildren($('#g-totals'), totalsEl(data.totals));
  } catch (error) {
    if (mine === totalsTicket) setStatus('error', error.message);
  }
}

/** Save a quantity: the row's figures and the totals update; rows stay put until the filter or range changes. */
async function saveQuantity(input) {
  if (input.validity.badInput) { // the browser hides a half-typed number as "": never clear the saved one for it
    setStatus('error', 'Enter a number.');
    return;
  }
  let row;
  try {
    row = await mutate(() => api(`/api/disposal/${input.dataset.id}/`, 'PUT', { [input.dataset.qty]: input.value }));
  } catch {
    return; // mutate has shown the error
  }
  patchRow(row);
  await loadTotals();
}

/** Hide or bring back a vessel, then reload (it leaves the current list). */
async function setHidden(id, hidden) {
  try {
    await mutate(() => api(`/api/disposal/${id}/`, 'PUT', { hidden }));
  } catch {
    return;
  }
  await load();
}

function wire() {
  if (wired) return;
  wired = true;
  filter = { from: '', to: '', port: 'ALL', show: 'all' };
  setChildren($('#g-show'), optionEls(SHOW, 'all'));
  $('#g-show').addEventListener('change', (event) => setFilter({ show: event.target.value }));
  if (ME.multiPort) {
    const select = $('#g-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => setFilter({ port: select.value }));
  }
  let dateTimer;
  const onDate = () => {
    clearTimeout(dateTimer);
    dateTimer = setTimeout(() => {
      const from = $('#g-from').value;
      const to = $('#g-to').value;
      if (typingYear(from) || typingYear(to)) return;
      if (from && to && from > to) {
        setStatus('error', 'From must be on or before To.');
        return;
      }
      if (from !== filter.from || to !== filter.to) setFilter({ from, to });
    }, DATE_DELAY_MS);
  };
  $('#g-from').addEventListener('change', onDate);
  $('#g-to').addEventListener('change', onDate);
  $('#g-tbody').addEventListener('change', (event) => {
    const input = event.target.closest('[data-qty]');
    if (input) saveQuantity(input);
  });
}

/** Opening the page takes the Vessels page's date range and port (the two pages share them). */
function open() {
  wire();
  Object.assign(filter, { from: state.filter.from, to: state.filter.to, port: state.filter.port || 'ALL' });
  if (ME.multiPort) $('#g-port').value = filter.port;
  return load();
}

/** The list query without paging: what the Excel button exports (every row these filters show). */
function exportQuery() {
  const query = params();
  query.delete('page');
  query.delete('page_size');
  return query;
}

export const disposalPage = {
  load: open,
  exportQuery,
  hide: (id) => setHidden(id, true),
  show: (id) => setHidden(id, false),
};
