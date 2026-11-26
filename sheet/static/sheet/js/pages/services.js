// The Services page: services (not vessels) as a work list. It opens with In progress ticked (the operators' to-do
// list); "Missing details only" is the managers' view; ticking only Completed with a range shows what got done.
// Everything is worked out by the server (/api/services/). The filters are remembered in this browser only.
import { api } from '../api.js';
import { portOptionEls, serviceStatusEl, tickFilterEl } from '../components.js';
import { ME, NO_AGENT, PORT_LABEL, SERVICE_STATUS, TYPES, can } from '../config.js';
import { h, icon, optionEls, setChildren } from '../dom.js';
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
let data = { vessels: [], count: 0, pages: 1, page: 1, agents: [] };
const opened = new Set(); // vessel ids whose cards are open, while on the page
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

// The Excel export's headings (one row a service; sheet/tests_page_excel.py keeps them equal to dataexport's).
export const heads = ['Vessel', 'Date', 'Service', 'Agent', 'Status', 'Completed', 'Missing'];

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

/** One service inside its vessel's card: opens the service (edit roles) or the vessel (read-only). */
function serviceCardEl(row) {
  return h('button', { class: 'sv-svc', dataset: { act: 'service-row', id: row.id }, attrs: { type: 'button' } },
    h('div', { class: 'sv-svc-top' },
      h('strong', null, row.type),
      h('span', null, serviceStatusEl(row.status),
        row.sailed ? h('span', { class: 'svc-status st-progress sailed' }, 'Sailed') : null)),
    h('div', { class: 'sv-svc-meta' },
      h('span', null, 'Agent: ', row.agent || '—'),
      filter.status.includes('completed') ? h('span', null, 'Completed: ', completedCell(row)) : null),
    row.missing.length
      ? h('div', null, row.missing.map((label) => h('span', { class: 'missing-tag' }, label)))
      : null);
}

function vesselCardEl({ vessel, services }) {
  const open = opened.has(vessel.id);
  const place = [ME.multiPort ? PORT_LABEL[vessel.port] || vessel.port : '', vessel.terminal, vessel.berth]
    .filter(Boolean).join(' · ');
  return h('article', { class: open ? 'sv-vessel open' : 'sv-vessel' },
    h('button', { class: 'sv-vessel-head', dataset: { act: 'sv-toggle', id: vessel.id },
      attrs: { type: 'button', 'aria-expanded': String(open) } },
    h('span', { class: 'sv-vessel-name' }, vessel.name),
    h('span', { class: 'sv-vessel-meta' }, [dmy(vessel.date), vessel.opr, place].filter(Boolean).join(' · ')),
    h('span', { class: 'sv-vessel-right' },
      services.some((s) => s.missing.length) ? h('span', { class: 'missing-tag' }, 'Missing') : null,
      h('span', { class: 'sv-count' }, services.length === 1 ? '1 service' : `${services.length} services`),
      icon('chevron-down'))),
    h('div', { class: 'sv-vessel-body', hidden: !open }, services.map(serviceCardEl)));
}

function render() {
  byId.clear();
  data.vessels.forEach((group) => group.services.forEach((row) => byId.set(row.id, row)));
  const listed = new Set(data.vessels.map((group) => group.vessel.id));
  for (const id of [...opened]) if (!listed.has(id)) opened.delete(id);
  setChildren($('#sv-cards'), data.vessels.map(vesselCardEl));
  $('#sv-empty').hidden = data.vessels.length > 0;
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
    count: data.count, pages: data.pages, page: data.page, size: filter.pageSize, noun: 'vessels',
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
  /** Opens or closes one vessel's card. */
  toggle(id) {
    if (opened.has(id)) opened.delete(id);
    else opened.add(id);
    render();
  },
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
