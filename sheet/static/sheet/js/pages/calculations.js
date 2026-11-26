// The Calculations page: every money line (services, hotel stays, transfers, garbage & sludge) of the vessels in a
// vessel-date range, OPR and port, as one card per vessel that opens to its line cards (like the Services page), with
// one totals line. Everything is worked out by the server (/api/calculations/, paged and sorted by vessel).
// Each line shows its service's operations status and its accounting state; accounting (read-only accounts) and
// admins switch a line Open / Closed. Two tick-box filters narrow by status and by accounting state.
import { api, mutate } from '../api.js';
import { portOptionEls, serviceStatusEl, sortIcon, tickFilterEl } from '../components.js';
import { BILLING, ME, NO_AGENT, PORT_LABEL, SERVICE_STATUS, can } from '../config.js';
import { h, icon, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { pagerEl } from '../render/pager.js';
import { PAGE_SIZES, defaultRange, rememberVessels } from '../state.js';
import { $, dmy, fmt } from '../util.js';

const SIZE_KEY = 'sheet.calculations.pageSize';
const DATE_DELAY_MS = 400;
const typingYear = (iso) => iso && Number(iso.slice(0, 4)) < 1900;

// The Excel's headings (one row per line; sheet/tests_page_excel.py keeps them equal to dataexport's).
export const COLUMNS = [
  { title: 'Date', sort: 'date' },
  { title: 'Vessel', sort: 'vessel' },
  { title: 'OPR', sort: 'opr' },
  { title: 'Port', sort: 'port', multiPort: true }, // a one-port User's rows are all in their port
  { title: 'Item', sort: 'kind' },
  { title: 'Cost', sort: 'cost' },
  { title: 'Revenue', sort: 'revenue' },
  { title: 'Profit LE', sort: 'profit' },
  { title: 'Status' },
  { title: 'Billing party' },
  { title: 'Billing' },
  { title: 'Accounting' },
];
const ACCOUNTING = { open: 'Open', closed: 'Closed' };
// The cards' sorts (the server sorts vessels; money by the vessel's sums).
const SORTS = [['date', 'Date'], ['vessel', 'Vessel'], ['opr', 'OPR'], ['port', 'Port', true], ['cost', 'Cost'],
  ['revenue', 'Revenue'], ['profit', 'Profit']];

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
  billing: Object.keys(BILLING), party: '',
};
let data = { rows: [], vessels: [], count: 0, pages: 1, page: 1, totals: null, oprs: [], parties: [] };
const opened = new Set(); // vessel ids whose cards are open, while on the page
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
  if (!can('accounting.close')) return h('span', { class: `acct-label ${row.closed ? 'closed' : ''}`.trim() }, label);
  return h('button', {
    class: `acct-switch ${row.closed ? 'closed' : ''}`.trim(),
    dataset: { act: 'acct-toggle', kind: row.ref.kind, id: row.ref.id, closed: row.closed ? '1' : '', vessel: row.vessel.id },
    attrs: { title: row.closed ? 'Reopen this line' : 'Close this line', 'aria-pressed': row.closed ? 'true' : 'false' },
  }, row.closed ? icon('lock') : icon('check'), ` ${label}`);
}

const money = (label, value) => h('div', { class: 'calc-money' }, h('span', { class: 'none' }, label), value);

/** One money line inside its vessel's card. */
function lineEl(row) {
  return h('div', { class: 'calc-line' },
    h('div', { class: 'sv-svc-top' }, h('strong', null, itemCell(row)), statusCell(row)),
    money('Cost ', sideCell(row.cost)),
    money('Revenue ', sideCell(row.revenue)),
    money('Profit LE ', h('span', { class: row.profit_egp < 0 ? 'neg' : null }, fmt(row.profit_egp),
      row.profit_usd != null ? ` · USD ${fmt(row.profit_usd)}` : '')),
    h('div', { class: 'sv-svc-top' },
      h('span', { class: 'none calc-note' }, [row.billing_party ? row.billing_party.name : 'No billing party',
        row.billing ? BILLING[row.billing] : ''].filter(Boolean).join(' · ')),
      accountingCell(row)));
}

function vesselCardEl(card, rows) {
  const { vessel } = card;
  const open = opened.has(vessel.id);
  const place = ME.multiPort ? PORT_LABEL[vessel.port] || vessel.port_label : '';
  return h('article', { class: open ? 'sv-vessel open' : 'sv-vessel' },
    h('button', { class: 'sv-vessel-head', dataset: { act: 'calc-toggle', id: vessel.id },
      attrs: { type: 'button', 'aria-expanded': String(open) } },
    h('span', { class: 'sv-vessel-name' }, vessel.name),
    h('span', { class: 'sv-vessel-meta' }, [dmy(vessel.date), vessel.opr, place].filter(Boolean).join(' · ')),
    h('span', { class: 'sv-vessel-right' },
      card.rate_missing || card.price_missing
        ? h('span', { class: 'warn-text', attrs: { title: 'A line has no exchange rate or price' } }, icon('alert')) : null,
      h('span', { class: 'calc-sums' }, `Revenue ${fmt(card.revenue_egp)} · Cost ${fmt(card.cost_egp)} · `,
        h('span', { class: card.profit_egp < 0 ? 'neg' : null }, `Profit ${fmt(card.profit_egp)}`)),
      h('span', { class: 'sv-count' }, card.lines === 1 ? '1 line' : `${card.lines} lines`),
      icon('chevron-down'))),
    h('div', { class: 'sv-vessel-body', hidden: !open },
      h('a', { class: 'calc-summary', href: '#calculations', dataset: { act: 'summary', id: vessel.id } }, 'Vessel summary'),
      rows.map(lineEl)));
}


function renderTicks() {
  for (const [name, title, labels] of [['status', 'Status', SERVICE_STATUS], ['accounting', 'Accounting', ACCOUNTING],
    ['billing', 'Billing', BILLING]]) {
    const old = $(`#c-${name}-filter`);
    const fresh = tickFilterEl({ id: `c-${name}-filter`, group: name, title, labels, ticked: filter[name] });
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
  setChildren($('#c-sort'), optionEls(SORTS.filter(([, , multi]) => !multi || ME.multiPort)
    .map(([key, label]) => [key, label]), filter.sort));
  setChildren($('#c-dir'), sortIcon(true, filter.dir));
  $('#c-dir').setAttribute('aria-label', filter.dir === 'desc' ? 'Highest / newest first' : 'Lowest / oldest first');
  renderTicks();
  const listed = new Set(data.vessels.map((v) => v.vessel.id));
  for (const id of [...opened]) if (!listed.has(id)) opened.delete(id);
  setChildren($('#c-cards'), data.vessels.map((card) => vesselCardEl(card, data.rows.filter((r) => r.vessel.id === card.vessel.id))));
  $('#c-empty').hidden = data.vessels.length > 0;
  setChildren($('#c-totals'), totalsEls(data.totals));
  const oprs = filter.opr && !data.oprs.includes(filter.opr) ? [...data.oprs, filter.opr] : data.oprs;
  setChildren($('#c-opr'), optionEls([['', 'All OPRs'], ...oprs.map((o) => [o, o])], filter.opr));
  const parties = data.parties.map((c) => [String(c.id), c.name]);
  if (filter.party && filter.party !== NO_AGENT && !parties.some(([id]) => id === filter.party)) parties.push([filter.party, 'Chosen party']);
  setChildren($('#c-party'), optionEls([['', 'All billing parties'], [NO_AGENT, 'No billing party'], ...parties], filter.party));
  setChildren($('#c-pager'), pagerEl({
    count: data.count, pages: data.pages, page: data.page, size: filter.pageSize, noun: 'vessels', sizeId: 'c-page-size',
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
    billing: filter.billing.length < Object.keys(BILLING).length ? filter.billing.join(',') : '',
    party: filter.party,
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
  if (!answer.vessels.length && filter.page > answer.pages) {
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
  if (ME.multiPort) {
    const select = $('#c-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => setFilter({ port: select.value }));
  }
  $('#c-opr').addEventListener('change', (event) => setFilter({ opr: event.target.value }));
  $('#c-party').addEventListener('change', (event) => setFilter({ party: event.target.value }));
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
  $('#c-sort').addEventListener('change', (event) => setFilter({ sort: event.target.value, dir: 'desc' }));
  $('#c-dir').addEventListener('click', () => setFilter({ dir: filter.dir === 'desc' ? 'asc' : 'desc' }));
  $('#c-ticks').addEventListener('change', (event) => {
    const box = event.target.closest('[data-tick]');
    if (!box) return;
    const name = box.dataset.tick;
    const ticked = [...$('#c-ticks').querySelectorAll(`[data-tick=${name}]`)].filter((b) => b.checked).map((b) => b.value);
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

/** Open or close one vessel's card (no reload). */
function toggle(id) {
  if (opened.has(id)) opened.delete(id);
  else opened.add(id);
  render();
}

export const calculationsPage = {
  load,
  exportQuery,
  toggleClosed,
  toggle,
  step: (n) => setFilter({ page: Math.min(Math.max(1, filter.page + n), data.pages) }),
};
