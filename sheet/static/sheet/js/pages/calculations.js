// The Calculations page: every money line (services, hotel stays, transfers) of the vessels in a vessel-date range,
// OPR and port, with its working and one totals line. Everything is worked out by the server (/api/calculations/).
// Each line shows its service's operations status and its accounting state; accounting (read-only accounts) and
// admins switch a line Open / Closed. Two tick-box filters narrow by status and by accounting state.
import { api, mutate } from '../api.js';
import { portOptionEls, serviceStatusEl, sortIcon } from '../components.js';
import { IS_ACCOUNTING, ME, SERVICE_STATUS } from '../config.js';
import { h, icon, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { pagerEl } from '../render/pager.js';
import { PAGE_SIZES, defaultRange, rememberVessels } from '../state.js';
import { $, dmy, fmt } from '../util.js';

const SIZE_KEY = 'sheet.calculations.pageSize';
const DATE_DELAY_MS = 400;
const typingYear = (iso) => iso && Number(iso.slice(0, 4)) < 1900;

const COLUMNS = [
  { title: 'Date', sort: 'date' },
  { title: 'Vessel', sort: 'vessel' },
  { title: 'OPR', sort: 'opr' },
  { title: 'Item', sort: 'kind' },
  { title: 'Cost', sort: 'cost' },
  { title: 'Revenue', sort: 'revenue' },
  { title: 'Profit LE', sort: 'profit' },
  { title: 'Status' },
  { title: 'Accounting' },
];
const ACCOUNTING = { open: 'Open', closed: 'Closed' };

function savedSize() {
  try {
    const n = Number(localStorage.getItem(SIZE_KEY));
    return PAGE_SIZES.includes(n) ? n : 50;
  } catch {
    return 50;
  }
}

const filter = {
  ...defaultRange(), opr: '', port: 'ALL', sort: 'date', dir: 'desc', page: 1, pageSize: savedSize(),
  status: Object.keys(SERVICE_STATUS), accounting: Object.keys(ACCOUNTING), // ticked values; all ticked = no filter
};
let data = { rows: [], count: 0, pages: 1, page: 1, totals: null, oprs: [] };
let ticket = 0;
let wired = false;

// Exchange rates are stored with up to 4 decimals: show them in full so the working multiplies out.
const fmtRate = (rate) => Number(rate).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });

/** One side of a line with its working: "USD 80.00 × 2 × 50.00 = 8,000.00", "EGP 900.00", or "—". */
function sideCell(side) {
  if (!side) return '—';
  let text = `${side.currency} ${fmt(side.amount)}`;
  // times is a count of nights / people (shown whenever it is not exactly 1)
  const times = side.times !== 1;
  if (times) text += ` × ${Number(side.times).toLocaleString('en-US', { maximumFractionDigits: 3 })}`;
  if (side.currency === 'USD') text += side.rate ? ` × ${fmtRate(side.rate)}` : ' × 1 (no rate)';
  if (side.currency === 'USD' || times) text += ` = ${fmt(side.egp)}`;
  return text;
}

function itemCell(row) {
  return [
    row.label,
    row.rate_missing ? [' ', h('span', { class: 'warn-text', attrs: { title: 'No exchange rate: USD counted 1:1' } }, icon('alert'))] : null,
    row.price_missing ? h('div', { class: 'warn-text calc-note' }, 'No price for this port and month') : null,
    row.note ? h('div', { class: 'none calc-note' }, row.note) : null,
  ];
}

function statusCell(row) {
  if (!row.status) return '—';
  return [serviceStatusEl(row.status), row.cancel_reason ? h('div', { class: 'none calc-note' }, row.cancel_reason) : null];
}

function accountingCell(row) {
  const label = row.closed ? 'Closed' : 'Open';
  if (!row.ref) return '—'; // garbage & sludge with nothing entered yet: nothing to close
  if (!IS_ACCOUNTING) return h('span', { class: `acct-label ${row.closed ? 'closed' : ''}`.trim() }, label);
  return h('button', {
    class: `acct-switch ${row.closed ? 'closed' : ''}`.trim(),
    dataset: { act: 'acct-toggle', kind: row.ref.kind, id: row.ref.id, closed: row.closed ? '1' : '', vessel: row.vessel.id },
    attrs: { title: row.closed ? 'Reopen this line' : 'Close this line', 'aria-pressed': row.closed ? 'true' : 'false' },
  }, row.closed ? icon('lock') : icon('check'), ` ${label}`);
}

function rowEl(row) {
  return h('tr', null,
    h('td', null, dmy(row.vessel.date)),
    h('td', null, h('a', { href: '#calculations', dataset: { act: 'summary', id: row.vessel.id } }, row.vessel.name)),
    h('td', null, row.vessel.opr || '—'),
    h('td', null, itemCell(row)),
    h('td', { class: 'num' }, sideCell(row.cost)),
    h('td', { class: 'num' }, sideCell(row.revenue)),
    h('td', { class: `num ${row.profit_egp < 0 ? 'neg' : ''}`.trim() }, fmt(row.profit_egp),
      row.profit_usd != null ? h('div', { class: 'none calc-note' }, `USD ${fmt(row.profit_usd)}`) : null),
    h('td', null, statusCell(row)),
    h('td', null, accountingCell(row)));
}

/** "All", "All except Completed" or the ticked names. */
function tickSummary(title, labels, ticked) {
  const all = Object.keys(labels);
  if (ticked.length === all.length) return `${title}: All`;
  const left = all.filter((key) => !ticked.includes(key));
  if (left.length === 1 && all.length > 2) return `${title}: All except ${labels[left[0]]}`;
  return `${title}: ${ticked.map((key) => labels[key]).join(', ')}`;
}

function tickFilterEl(name, title, labels) {
  return h('details', { class: 'tick-filter', id: `c-${name}-filter` },
    h('summary', null, tickSummary(title, labels, filter[name])),
    h('div', { class: 'tick-list' }, Object.entries(labels).map(([key, label]) => h('label', null,
      h('input', { attrs: { type: 'checkbox' }, dataset: { tick: name }, value: key, checked: filter[name].includes(key) }),
      label))));
}

function renderTicks() {
  for (const [name, title, labels] of [['status', 'Status', SERVICE_STATUS], ['accounting', 'Accounting', ACCOUNTING]]) {
    const old = $(`#c-${name}-filter`);
    const fresh = tickFilterEl(name, title, labels);
    fresh.open = Boolean(old?.open);
    if (old) old.replaceWith(fresh);
    else $('#c-ticks').append(fresh);
  }
}

function totalsEls(t) {
  if (!t) return null;
  const lines = `${t.lines} line${t.lines === 1 ? '' : 's'}`;
  return [
    `Revenue LE ${fmt(t.revenue_egp)} · Cost LE ${fmt(t.cost_egp)} · Profit LE ${fmt(t.profit_egp)} · ${lines}`,
    ` · Open ${t.open} · Closed ${t.closed}`,
    t.rate_missing_lines
      ? [' ', h('span', { class: 'warn-text' },
        icon('alert'), ` ${t.rate_missing_lines} line${t.rate_missing_lines === 1 ? ' uses' : 's use'} USD without a rate (counted 1:1)`)]
      : null,
    t.cost_usd || t.revenue_usd
      ? h('div', null, `USD lines: Revenue USD ${fmt(t.revenue_usd)} · Cost USD ${fmt(t.cost_usd)} · Profit USD ${fmt(t.profit_usd)}`)
      : null,
    t.price_missing_lines
      ? h('div', { class: 'warn-text' }, icon('alert'),
        ` ${t.price_missing_lines} Garbage & Sludge line${t.price_missing_lines === 1 ? ' has' : 's have'} no price`)
      : null,
  ];
}

function render() {
  setChildren($('#c-head'), h('tr', null, COLUMNS.map((c) => (c.sort
    ? h('th', { dataset: { csort: c.sort } }, c.title, ' ', h('span', { class: 'arrow' }, sortIcon(filter.sort === c.sort, filter.dir)))
    : h('th', null, c.title)))));
  renderTicks();
  setChildren($('#c-tbody'), data.rows.map(rowEl));
  $('#c-empty').hidden = data.rows.length > 0;
  setChildren($('#c-totals'), totalsEls(data.totals));
  const oprs = filter.opr && !data.oprs.includes(filter.opr) ? [...data.oprs, filter.opr] : data.oprs;
  setChildren($('#c-opr'), optionEls([['', 'All OPRs'], ...oprs.map((o) => [o, o])], filter.opr));
  setChildren($('#c-pager'), pagerEl({
    count: data.count, pages: data.pages, page: data.page, size: filter.pageSize, noun: 'lines', sizeId: 'c-page-size',
    prev: { act: 'calc-page', step: -1 }, next: { act: 'calc-page', step: 1 },
  }));
  const from = $('#c-from');
  const to = $('#c-to');
  if (document.activeElement !== from) from.value = filter.from;
  if (document.activeElement !== to) to.value = filter.to;
  from.max = filter.to;
  to.min = filter.from;
}

function params() {
  const values = {
    from: filter.from, to: filter.to, opr: filter.opr, port: filter.port === 'ALL' ? '' : filter.port,
    sort: filter.sort, dir: filter.dir, page: filter.page, page_size: filter.pageSize,
    // all ticked = no filter (so lines without a status, the bookings and garbage, stay)
    status: filter.status.length < Object.keys(SERVICE_STATUS).length ? filter.status.join(',') : '',
    accounting: filter.accounting.length < Object.keys(ACCOUNTING).length ? filter.accounting.join(',') : '',
  };
  return new URLSearchParams(Object.entries(values).filter(([, v]) => v !== '' && v !== null && v !== undefined));
}

async function load() {
  wire();
  const mine = ++ticket;
  let answer;
  try {
    answer = await api(`/api/calculations/?${params()}`);
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
    return;
  }
  if (mine !== ticket) return; // a newer request is on its way
  if (!answer.rows.length && filter.page > answer.pages) {
    filter.page = answer.pages;
    load();
    return;
  }
  data = answer;
  render();
}

function setFilter(patch) {
  Object.assign(filter, patch);
  if (!('page' in patch)) filter.page = 1;
  if ('pageSize' in patch) {
    try {
      localStorage.setItem(SIZE_KEY, String(patch.pageSize));
    } catch {
      // not remembered
    }
  }
  return load();
}

/** Hook up the page's controls once, the first time it is shown. */
function wire() {
  if (wired) return;
  wired = true;
  if (ME.seesAll) {
    const select = $('#c-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => setFilter({ port: select.value }));
  }
  $('#c-opr').addEventListener('change', (event) => setFilter({ opr: event.target.value }));
  let dateTimer;
  const onDate = () => {
    clearTimeout(dateTimer);
    dateTimer = setTimeout(() => {
      const from = $('#c-from').value;
      const to = $('#c-to').value;
      if (typingYear(from) || typingYear(to)) return;
      if (from && to && from > to) {
        setStatus('error', 'From must be on or before To.');
        return;
      }
      if (from !== filter.from || to !== filter.to) setFilter({ from, to });
    }, DATE_DELAY_MS);
  };
  $('#c-from').addEventListener('change', onDate);
  $('#c-to').addEventListener('change', onDate);
  $('#c-clear').addEventListener('click', () => setFilter({ from: '', to: '' }));
  $('#c-head').addEventListener('click', (event) => {
    const th = event.target.closest('[data-csort]');
    if (!th) return;
    const sort = th.dataset.csort;
    setFilter({ sort, dir: filter.sort === sort && filter.dir === 'desc' ? 'asc' : 'desc' });
  });
  $('#c-ticks').addEventListener('change', (event) => {
    const box = event.target.closest('[data-tick]');
    if (!box) return;
    const name = box.dataset.tick;
    const ticked = [...document.querySelectorAll(`[data-tick=${name}]`)].filter((b) => b.checked).map((b) => b.value);
    if (!ticked.length) { // at least one must stay ticked
      box.checked = true;
      return;
    }
    setFilter({ [name]: ticked });
  });
  $('#c-pager').addEventListener('change', (event) => {
    if (event.target.id === 'c-page-size') setFilter({ pageSize: Number(event.target.value) });
  });
}

/** Accounting closes or reopens one line's service / booking / garbage & sludge, then the page reloads (and the
 *  vessel is fetched again, so its cards show the new state). */
async function toggleClosed(button) {
  const { kind, id, closed, vessel } = button.dataset;
  button.disabled = true;
  try {
    await mutate(() => api('/api/accounting/', 'POST', { kind, id: Number(id), closed: !closed }));
  } finally {
    button.disabled = false;
  }
  const [fresh] = await Promise.all([api(`/api/vessels/${vessel}/`).catch(() => null), load()]);
  if (fresh) rememberVessels([fresh]);
}

/** The list query without paging: what the Excel button exports (every row these filters show). */
function exportQuery() {
  const query = params();
  query.delete('page');
  query.delete('page_size');
  return query;
}

export const calculationsPage = {
  load,
  exportQuery,
  toggleClosed,
  step: (n) => setFilter({ page: Math.min(Math.max(1, filter.page + n), data.pages) }),
};
