// The Calculations page: every money line (services, hotel stays, transfers) of the vessels in a vessel-date range,
// OPR and port, with its working and one totals line. Everything is worked out by the server (/api/calculations/).
import { api } from '../api.js';
import { ME, PORTS } from '../config.js';
import { setStatus } from '../feedback.js';
import { pagerHtml } from '../render/pager.js';
import { PAGE_SIZES, defaultRange } from '../state.js';
import { $, dmy, esc, fmt } from '../util.js';

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
];

function savedSize() {
  try {
    const n = Number(localStorage.getItem(SIZE_KEY));
    return PAGE_SIZES.includes(n) ? n : 50;
  } catch {
    return 50;
  }
}

const filter = { ...defaultRange(), opr: '', port: 'ALL', sort: 'date', dir: 'desc', page: 1, pageSize: savedSize() };
let data = { rows: [], count: 0, pages: 1, page: 1, totals: null, oprs: [] };
let ticket = 0;
let wired = false;

// Exchange rates are stored with up to 4 decimals: show them in full so the working multiplies out.
const fmtRate = (rate) => Number(rate).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });

/** One side of a line with its working: "USD 80.00 × 2 × 50.00 = 8,000.00", "EGP 900.00", or "—". */
function sideCell(side) {
  if (!side) return '—';
  let text = `${esc(side.currency)} ${fmt(side.amount)}`;
  if (side.times > 1) text += ` × ${side.times}`;
  if (side.currency === 'USD') text += side.rate ? ` × ${fmtRate(side.rate)}` : ' × 1 (no rate)';
  if (side.currency === 'USD' || side.times > 1) text += ` = ${fmt(side.egp)}`;
  return text;
}

function itemCell(row) {
  const flag = row.rate_missing ? ' <span class="warn-text" title="No exchange rate: USD counted 1:1">⚠</span>' : '';
  const note = row.note ? `<div class="none calc-note">${esc(row.note)}</div>` : '';
  return `${esc(row.label)}${flag}${note}`;
}

function rowHtml(row) {
  return `<tr>
    <td>${dmy(row.vessel.date)}</td>
    <td><a href="#calculations" data-act="summary" data-id="${row.vessel.id}">${esc(row.vessel.name)}</a></td>
    <td>${esc(row.vessel.opr || '—')}</td>
    <td>${itemCell(row)}</td>
    <td class="num">${sideCell(row.cost)}</td>
    <td class="num">${sideCell(row.revenue)}</td>
    <td class="num ${row.profit_egp < 0 ? 'neg' : ''}">${fmt(row.profit_egp)}</td></tr>`;
}

function totalsHtml(t) {
  if (!t) return '';
  const lines = `${t.lines} line${t.lines === 1 ? '' : 's'}`;
  const warn = t.rate_missing_lines
    ? ` <span class="warn-text">⚠ ${t.rate_missing_lines} line${t.rate_missing_lines === 1 ? ' uses' : 's use'} USD without a rate (counted 1:1)</span>`
    : '';
  return `Revenue LE ${fmt(t.revenue_egp)} · Cost LE ${fmt(t.cost_egp)} · Profit LE ${fmt(t.profit_egp)} · ${lines}${warn}`;
}

function render() {
  $('#c-head').innerHTML = `<tr>${COLUMNS.map((c) => {
    const arrow = filter.sort === c.sort ? (filter.dir === 'asc' ? '↑' : '↓') : '↕';
    return `<th data-csort="${c.sort}">${esc(c.title)} <span class="arrow">${arrow}</span></th>`;
  }).join('')}</tr>`;
  $('#c-tbody').innerHTML = data.rows.map(rowHtml).join('');
  $('#c-empty').style.display = data.rows.length ? 'none' : 'block';
  $('#c-totals').innerHTML = totalsHtml(data.totals);
  const oprs = filter.opr && !data.oprs.includes(filter.opr) ? [...data.oprs, filter.opr] : data.oprs;
  $('#c-opr').innerHTML = `<option value="">All OPRs</option>${oprs.map((o) =>
    `<option value="${esc(o)}" ${o === filter.opr ? 'selected' : ''}>${esc(o)}</option>`).join('')}`;
  $('#c-pager').innerHTML = pagerHtml({
    count: data.count, pages: data.pages, page: data.page, size: filter.pageSize, noun: 'lines', sizeId: 'c-page-size',
    prev: 'data-act="calc-page" data-step="-1"', next: 'data-act="calc-page" data-step="1"',
  });
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
    select.innerHTML = `<option value="ALL">🌐 All ports</option>${PORTS.map((p) => `<option value="${p.key}">${esc(p.label)}</option>`).join('')}`;
    select.style.display = '';
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
  $('#c-pager').addEventListener('change', (event) => {
    if (event.target.id === 'c-page-size') setFilter({ pageSize: Number(event.target.value) });
  });
}

export const calculationsPage = {
  load,
  step: (n) => setFilter({ page: Math.min(Math.max(1, filter.page + n), data.pages) }),
};
