// The Services page: services (not vessels) as a work list. It opens with In progress ticked (the operators' to-do
// list); "Missing details only" is the managers' view; ticking only Completed with a range shows what got done.
// Everything is worked out by the server (/api/services/). The filters are remembered in this browser only.
import { api } from '../api.js';
import { portOptionEls, serviceStatusEl, tickFilterEl } from '../components.js';
import { ME, NO_AGENT, SERVICE_STATUS, TYPES, can } from '../config.js';
import { h, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openServiceForm } from '../modals/service.js';
import { openVessel } from '../modals/vessel.js';
import { pagerEl } from '../render/pager.js';
import { PAGE_SIZES, rememberVessels, state } from '../state.js';
import { $, dmy, fmtStamp } from '../util.js';

const STORE_KEY = 'sheet.services.filter';
const SEARCH_DELAY_MS = 300;
const DEFAULTS = { status: ['in_progress'], missing: false, from: '', to: '', type: '', agent: '', q: '', port: '', page: 1,
  pageSize: 50 };

function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
    const status = Array.isArray(saved.status) ? saved.status.filter((s) => s in SERVICE_STATUS) : [];
    return {
      ...DEFAULTS,
      status: status.length ? status : DEFAULTS.status,
      missing: saved.missing === true,
      type: TYPES.includes(saved.type) ? saved.type : '',
      pageSize: PAGE_SIZES.includes(saved.pageSize) ? saved.pageSize : DEFAULTS.pageSize,
      from: typeof saved.from === 'string' ? saved.from : '',
      to: typeof saved.to === 'string' ? saved.to : '',
    };
  } catch {
    return { ...DEFAULTS };
  }
}

const filter = restore();
let data = { services: [], count: 0, pages: 1, page: 1, agents: [] };
const byId = new Map();
let ticket = 0;
let wired = false;

function remember() {
  try {
    const { status, missing, type, pageSize, from, to } = filter;
    localStorage.setItem(STORE_KEY, JSON.stringify({ status, missing, type, pageSize, from, to }));
  } catch {
    // no storage (private window): the page starts from the defaults next time
  }
}

const onlyCompleted = () => filter.status.length === 1 && filter.status[0] === 'completed';

function query({ paged }) {
  const q = new URLSearchParams({ status: filter.status.join(',') });
  if (filter.missing) q.set('missing', '1');
  for (const key of ['from', 'to', 'type', 'agent', 'q', 'port']) if (filter[key]) q.set(key, filter[key]);
  if (paged) {
    q.set('page', String(filter.page));
    q.set('page_size', String(filter.pageSize));
  }
  return q;
}

function completedCell(row) {
  if (row.completed_at) return fmtStamp(row.completed_at);
  return row.completed_guess ? `≈ ${dmy(row.vessel.date)}` : '—';
}

function rowEl(row) {
  return h('tr', { class: 'clickable', dataset: { act: 'service-row', id: row.id } },
    h('td', null, row.vessel.name),
    h('td', null, dmy(row.vessel.date)),
    h('td', null, row.type),
    h('td', null, row.agent || '—'),
    h('td', null, serviceStatusEl(row.status), row.sailed ? h('span', { class: 'svc-status st-progress sailed' }, 'Sailed') : null),
    onlyCompleted() || filter.status.includes('completed') ? h('td', null, completedCell(row)) : null,
    h('td', null, row.missing.length
      ? row.missing.map((label) => h('span', { class: 'missing-tag' }, label))
      : h('span', { class: 'none' }, '—')));
}

function render() {
  byId.clear();
  data.services.forEach((row) => byId.set(row.id, row));
  const withCompleted = filter.status.includes('completed');
  const heads = ['Vessel', 'Date', 'Service', 'Agent', 'Status', ...(withCompleted ? ['Completed'] : []), 'Missing'];
  setChildren($('#sv-head'), h('tr', null, heads.map((t) => h('th', null, t))));
  setChildren($('#sv-tbody'), data.services.map(rowEl));
  $('#sv-empty').hidden = data.services.length > 0;
  const fresh = tickFilterEl({ id: 'sv-status-filter', group: 'svstatus', title: 'Status', labels: SERVICE_STATUS,
    ticked: filter.status });
  const old = $('#sv-status-filter');
  fresh.open = Boolean(old?.open);
  if (old) old.replaceWith(fresh);
  else $('#sv-ticks').append(fresh);
  $('#sv-missing').checked = filter.missing;
  const agents = data.agents.map((a) => [a, a]);
  if (filter.agent && filter.agent !== NO_AGENT && !data.agents.includes(filter.agent)) agents.push([filter.agent, filter.agent]);
  setChildren($('#sv-agent'), optionEls([['', 'All agents'], [NO_AGENT, 'No agent'], ...agents], filter.agent));
  setChildren($('#sv-pager'), pagerEl({
    count: data.count, pages: data.pages, page: data.page, size: filter.pageSize, noun: 'services',
    sizeId: 'sv-page-size', prev: { act: 'services-page', step: -1 }, next: { act: 'services-page', step: 1 },
  }));
  for (const key of ['from', 'to']) if (document.activeElement !== $(`#sv-${key}`)) $(`#sv-${key}`).value = filter[key];
}

function setFilter(changes) {
  Object.assign(filter, changes, 'page' in changes ? {} : { page: 1 });
  remember();
  return servicesPage.load();
}

function wire() {
  if (wired) return;
  wired = true;
  setChildren($('#sv-type'), optionEls([['', 'All services'], ...TYPES.map((t) => [t, t])], filter.type));
  if (ME.multiPort) {
    const select = $('#sv-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => setFilter({ port: select.value }));
  }
  $('#sv-ticks').addEventListener('change', (event) => {
    const box = event.target.closest('[data-tick]');
    if (!box) return;
    const ticked = [...$('#sv-ticks').querySelectorAll('[data-tick=svstatus]')].filter((b) => b.checked).map((b) => b.value);
    if (!ticked.length) { // at least one must stay ticked
      box.checked = true;
      return;
    }
    setFilter({ status: ticked });
  });
  $('#sv-missing').addEventListener('change', (event) => setFilter({ missing: event.target.checked }));
  $('#sv-type').addEventListener('change', (event) => setFilter({ type: event.target.value }));
  $('#sv-agent').addEventListener('change', (event) => setFilter({ agent: event.target.value }));
  let searchTimer;
  $('#sv-q').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setFilter({ q: event.target.value.trim() }), SEARCH_DELAY_MS);
  });
  for (const key of ['from', 'to']) {
    $(`#sv-${key}`).addEventListener('change', (event) => {
      const value = event.target.value;
      if (value && Number(value.slice(0, 4)) < 1900) return; // still typing the year
      setFilter({ [key]: value });
    });
  }
  $('#sv-clear').addEventListener('click', () => setFilter({ from: '', to: '' }));
  $('#sv-pager').addEventListener('change', (event) => {
    if (event.target.id === 'sv-page-size') setFilter({ pageSize: Number(event.target.value) });
  });
}

export const servicesPage = {
  async load() {
    wire();
    const mine = ++ticket;
    try {
      const fresh = await api(`/api/services/?${query({ paged: true })}`);
      if (mine !== ticket) return; // an older answer: a newer one is on its way
      data = fresh;
      if (data.page > data.pages) {
        filter.page = data.pages;
        await servicesPage.load();
        return;
      }
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  exportQuery: () => query({ paged: false }).toString(),
  step(n) {
    return setFilter({ page: Math.min(Math.max(1, filter.page + n), data.pages) });
  },
  /** A row: edit roles get its service dialog (saving brings them back here), read-only roles the vessel. */
  async open(id) {
    const row = byId.get(id);
    if (!row) return;
    let vessel;
    try {
      vessel = await api(`/api/vessels/${row.vessel.id}/`); // fresh: the list may be older than the vessel
    } catch (error) {
      setStatus('error', error.message);
      return;
    }
    rememberVessels([vessel]);
    const service = vessel.services.find((s) => s.id === id);
    if (!can('services.edit') || !service) {
      openVessel(vessel.id);
      return;
    }
    state.ctx = { vesselId: vessel.id };
    openServiceForm(service.type, service, { from: 'services' });
  },
};
