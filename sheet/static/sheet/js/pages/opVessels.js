// Vessel Data (Operation): every vessel visit at the person's terminals, with the server's figures. Filters are kept
// per computer; a row opens the visit dialog (read-only without "Add / edit vessel data").
import { api } from '../api.js';
import { portOptionEls, sortIcon, tickFilterEl } from '../components.js';
import { ME, can } from '../config.js';
import { h, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { figure, loadTerminals, stamp, statusEl, terminalOptionEls } from '../operation/shared.js';
import { pagerEl } from '../render/pager.js';
import { PAGE_SIZES } from '../state.js';
import { $, $$, tickSummary } from '../util.js';

const KEY = 'sheet.opVessels.filter';
const STATUSES = { Planned: 'Planned', Working: 'Working', Completed: 'Completed' };
const COLUMNS = [
  ['id', 'ID', (v) => String(v.id)],
  ['vessel_name', 'Vessel', (v) => v.vessel_name],
  ['shipping_line', 'Line', (v) => v.shipping_line],
  ['terminal', 'Terminal', (v) => v.terminal_name],
  [null, 'LOA', (v) => figure(v.loa)],
  ['eta', 'ETA', (v) => stamp(v.eta)],
  ['ata', 'ATA', (v) => stamp(v.ata)],
  [null, 'Planned berth', (v) => v.planned_berth || '—'],
  [null, 'ETB', (v) => stamp(v.etb)],
  [null, 'ETC', (v) => stamp(v.etc)],
  ['atb', 'ATB', (v) => stamp(v.atb)],
  [null, 'Actual berth', (v) => v.actual_berth || '—'],
  [null, 'Cranes', (v) => figure(v.cranes)],
  ['atd', 'ATD', (v) => stamp(v.atd)],
  ['status', 'Status', (v) => statusEl(v.status)],
  ['waiting', 'Waiting', (v) => figure(v.waiting)],
  ['operation', 'Operation', (v) => figure(v.operation)],
  [null, 'Discharge', (v) => figure(v.discharge)],
  [null, 'Loading', (v) => figure(v.loading)],
  ['total_moves', 'Total moves', (v) => figure(v.total_moves)],
  ['productivity', 'Moves/hr', (v) => figure(v.productivity)],
  ['port_stay', 'Port stay', (v) => figure(v.port_stay)],
];

const DEFAULTS = { port: '', terminal: '', status: [], line: '', q: '', from: '', to: '', sort: 'eta', dir: 'desc',
  page: 1, page_size: 50 };
const filter = { ...DEFAULTS, ...readSaved() };
let data = { visits: [], total: 0, page: 1, pages: 1, lines: [] };
let ticket = 0;
let wired = false;

function readSaved() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    return saved && typeof saved === 'object' ? saved : {};
  } catch {
    return {};
  }
}

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...filter, page: 1 }));
  } catch { /* private window: not remembered */ }
}

function params(paged = true) {
  const values = { ...filter, status: filter.status.join(',') };
  if (!paged) {
    delete values.page;
    delete values.page_size;
  }
  return new URLSearchParams(Object.entries(values).filter(([, v]) => v !== '' && v !== null));
}

function render() {
  setChildren($('#ov-head'), h('tr', null, COLUMNS.map(([key, title]) => (key
    ? h('th', { class: 'clickable', dataset: { act: 'opv-sort', key } }, title, ' ', h('span', { class: 'arrow' }, sortIcon(filter.sort === key, filter.dir)))
    : h('th', null, title)))));
  setChildren($('#ov-tbody'), data.visits.map((v) => h('tr', { class: 'clickable', dataset: { act: 'opv-open', id: v.id } },
    COLUMNS.map(([, , cell]) => h('td', null, cell(v))))));
  $('#ov-empty').hidden = data.visits.length > 0;
  setChildren($('#ov-pager'), pagerEl({ count: data.total, pages: data.pages, page: data.page, size: filter.page_size,
    noun: 'visits', sizeId: 'ov-size', prev: { act: 'opv-prev' }, next: { act: 'opv-next' } }));
  $('#ov-size').addEventListener('change', (event) => setFilter({ page_size: Number(event.target.value) }));
  const line = $('#ov-line');
  setChildren(line, h('option', { value: '' }, 'All lines'), optionEls(data.lines.map((l) => [l, l]), filter.line));
}

async function load() {
  await wire();
  const mine = ++ticket;
  try {
    const fresh = await api(`/api/operation/visits/?${params()}`);
    if (mine !== ticket) return;
    data = fresh;
    filter.page = data.page;
    render();
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
  }
}

function setFilter(patch) {
  Object.assign(filter, { page: 1 }, patch);
  save();
  return load();
}

async function wire() {
  if (wired) return;
  wired = true;
  if (!PAGE_SIZES.includes(filter.page_size)) filter.page_size = DEFAULTS.page_size;
  const terminals = await loadTerminals();
  if (ME.multiPort) {
    const port = $('#ov-port');
    setChildren(port, portOptionEls({ all: true, selected: filter.port }));
    port.hidden = false;
    port.addEventListener('change', () => setFilter({ port: port.value === 'ALL' ? '' : port.value }));
  }
  const terminal = $('#ov-terminal');
  setChildren(terminal, terminalOptionEls(terminals, filter.terminal));
  terminal.addEventListener('change', () => setFilter({ terminal: terminal.value }));
  setChildren($('#ov-status'), tickFilterEl({ id: 'ov-status-filter', group: 'opv-status', title: 'Status',
    labels: STATUSES, ticked: filter.status }));
  $('#ov-status').addEventListener('change', () => {
    const ticked = $$('#ov-status [data-tick="opv-status"]:checked').map((box) => box.value);
    $('#ov-status summary').textContent = tickSummary('Status', STATUSES, ticked);
    setFilter({ status: ticked });
  });
  $('#ov-line').addEventListener('change', (event) => setFilter({ line: event.target.value }));
  const search = $('#ov-q');
  search.value = filter.q;
  let timer;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => setFilter({ q: search.value.trim() }), 300);
  });
  for (const key of ['from', 'to']) {
    const input = $(`#ov-${key}`);
    input.value = filter[key];
    input.addEventListener('change', () => setFilter({ [key]: input.value }));
  }
  $('#ov-clear').addEventListener('click', () => {
    $('#ov-from').value = '';
    $('#ov-to').value = '';
    setFilter({ from: '', to: '' });
  });
}

export const visitById = (id) => data.visits.find((v) => v.id === Number(id)) || null;

export const opVesselsPage = {
  load,
  sort(key) {
    const dir = filter.sort === key && filter.dir === 'asc' ? 'desc' : 'asc';
    return setFilter({ sort: key, dir });
  },
  prev: () => setFilter({ page: Math.max(1, filter.page - 1) }),
  next: () => setFilter({ page: filter.page + 1 }),
  exportQuery: () => params(false),
  canAdd: () => can('operation.edit'),
};
