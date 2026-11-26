// The dashboard tab, as the server totals it (state.dashboard, loaded by data.loadDashboard): its own filters, jobs
// per agent, services and money per month, then the OPR charts and cards. Charts are plain divs (no library).
import { CHART_COLORS, ME, NO_AGENT, PORT_LABEL, TYPES, can } from '../config.js';
import { state } from '../state.js';
import { h, optionEls, setChildren } from '../dom.js';
import { $, fmt, fmtShort } from '../util.js';
import { donutEl } from './svgChart.js';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = (ym) => `${MONTH_NAMES[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;
const typeColor = (type) => CHART_COLORS[Math.max(0, TYPES.indexOf(type)) % CHART_COLORS.length];
const agentLabel = (agent) => agent || '(no agent)';
const noData = () => h('div', { class: 'none' }, 'No data.');
// The money panels are in the page only with money.view (the template leaves them out, the server sends no money).
const seeMoney = () => can('money.view');

function renderBars(selector, labels, values, format) {
  const container = $(selector);
  if (!labels.length) {
    setChildren(container, noData());
    return;
  }
  const max = Math.max(...values.map(Math.abs), 1);
  const bars = labels.map((label, i) => {
    const height = Math.max(4, Math.round((Math.abs(values[i]) / max) * 170));
    const color = values[i] < 0 ? 'var(--danger)' : CHART_COLORS[i % CHART_COLORS.length];
    return h('div', { class: 'bar', dataset: { act: 'opr-summary', opr: label }, attrs: { title: label } },
      h('div', { class: 'v' }, format(values[i])),
      h('div', { class: 'fill', style: { height: `${height}px`, background: color } }),
      h('div', { class: 'l' }, label));
  });
  setChildren(container, h('div', { class: 'bars' }, bars));
}

function renderOprCards(oprs) {
  setChildren($('#opr-cards'), oprs.length
    ? oprs.map((t, i) => {
      const color = CHART_COLORS[i % CHART_COLORS.length];
      return h('div', { class: 'opr-card', dataset: { act: 'opr-summary', opr: t.opr }, style: { borderColor: `color-mix(in srgb, ${color} 35%, transparent)` } },
        h('div', { class: 'n', style: { color } }, t.opr),
        h('div', { class: 'big' }, t.vessels, ' ', h('small', null, 'vessels')),
        h('div', { class: 'none' }, `${t.services} services`),
        seeMoney() ? h('div', { class: 'num', style: { marginTop: '4px' } }, `${fmtShort(t.cost_egp)} LE cost`) : null);
    })
    : h('div', { class: 'none' }, 'No data for the selected filters.'));
}

/** A dropdown's options: "All …", the values present, and the chosen value even when it is no longer present. */
function fillSelect(selector, allLabel, values, current, extra = []) {
  const keep = current && !values.includes(current) && !extra.some(([v]) => v === current) ? [current] : [];
  setChildren($(selector), optionEls([['', allLabel], ...[...values, ...keep].map((v) => [v, v]), ...extra], current));
}

function renderFilters() {
  const { filters } = state.dashboard;
  const f = state.dashboardFilter;
  fillSelect('#d-opr', 'All OPRs', filters.oprs, f.opr);
  fillSelect('#d-agent', 'All agents', filters.agents, f.agent, [[NO_AGENT, '(no agent)']]);
  fillSelect('#d-service', 'All services', TYPES, f.service);
  $('#d-port').value = state.filter.port;
}

/** A figures table; `rows` are [cells, props] with the first cell the row label. The last row may be a total. */
function figTable(headers, rows) {
  return h('table', { class: 'fig-table' },
    h('thead', null, h('tr', null, headers.map((text) => h('th', null, text)))),
    h('tbody', null, rows.map(([cells, props]) => h('tr', props, cells.map((cell) => (cell instanceof Node ? cell : h('td', null, cell)))))));
}

const agentAct = (agent) => ({ act: 'agent-jobs', agent: agent || NO_AGENT });

function renderAgents({ agents, service_types: types, totals }) {
  if (!agents.length) {
    setChildren($('#chart-agents'), noData());
    setChildren($('#tbl-agents'), noData());
    return;
  }
  const max = Math.max(...agents.map((a) => a.total), 1);
  setChildren($('#chart-agents'), h('div', { class: 'hbars' }, agents.map((a) => h('div',
    { class: a.agent ? 'hbar' : 'hbar no-agent', dataset: agentAct(a.agent), attrs: { title: agentLabel(a.agent) } },
    h('span', { class: 'l' }, agentLabel(a.agent)),
    h('span', { class: 'track' }, h('span', { class: 'fill', style: { width: `${(a.total / max) * 100}%` } })),
    h('span', { class: 'v' }, a.total)))));

  const showPortCalls = !state.dashboardFilter.service; // arrivals and sailings are not services
  const callCols = (a) => (showPortCalls ? [a.arrivals, a.sailings] : []);
  const sum = (key) => agents.reduce((n, a) => n + a[key], 0);
  const rows = agents.map((a) => [
    [agentLabel(a.agent), ...callCols(a), ...types.map((t) => a.by_type[t] || 0), a.total],
    { class: a.agent ? 'clickable' : 'clickable no-agent', dataset: agentAct(a.agent) },
  ]);
  rows.push([['Total', ...(showPortCalls ? [sum('arrivals'), sum('sailings')] : []),
    ...types.map((t) => agents.reduce((n, a) => n + (a.by_type[t] || 0), 0)), totals.jobs], { class: 'total' }]);
  setChildren($('#tbl-agents'), figTable(['Agent', ...(showPortCalls ? ['Arrivals', 'Sailings'] : []), ...types, 'Total'], rows));
}

function renderMonths({ months, service_types: types, totals }) {
  if (!months.length) {
    for (const selector of ['#chart-months', '#tbl-months', ...(seeMoney() ? ['#tbl-money'] : [])]) setChildren($(selector), noData());
    return;
  }
  const max = Math.max(...months.map((m) => m.total), 1);
  const columns = months.map((m) => h('div', { class: 'stack-col', attrs: { title: `${monthLabel(m.month)}: ${m.total}` } },
    h('div', { class: 'v' }, m.total),
    h('div', { class: 'stack' }, types.filter((t) => m.by_type[t]).map((t) => h('div', {
      class: 'seg', style: { height: `${Math.round((m.by_type[t] / max) * 170)}px`, background: typeColor(t) },
    }))),
    h('div', { class: 'l' }, monthLabel(m.month))));
  const legend = h('div', { class: 'legend' }, types.map((t) => h('span', null,
    h('span', { class: 'swatch', style: { background: typeColor(t) } }), t)));
  setChildren($('#chart-months'), h('div', { class: 'stack-cols' }, columns), legend);

  const heads = ['', ...months.map((m) => monthLabel(m.month)), 'Total'];
  const typeRows = types.map((t) => [[t, ...months.map((m) => m.by_type[t] || 0), months.reduce((n, m) => n + (m.by_type[t] || 0), 0)]]);
  typeRows.push([['Total', ...months.map((m) => m.total), totals.services], { class: 'total' }]);
  setChildren($('#tbl-months'), figTable(heads, typeRows));
  if (!seeMoney()) return;

  const moneyCell = (value, negative) => h('td', { class: negative && value < 0 ? 'num neg' : 'num' }, fmt(value));
  const moneyRows = [['Cost', 'cost_egp'], ['Revenue', 'revenue_egp'], ['Profit', 'profit_egp']].map(([label, key]) => [
    [label, ...months.map((m) => moneyCell(m[key], key === 'profit_egp')), moneyCell(totals[key], key === 'profit_egp')],
    key === 'profit_egp' ? { class: 'total' } : null,
  ]);
  setChildren($('#tbl-money'), figTable(heads, moneyRows));
}

/** Services per operations status and Calculations lines per accounting state, per month (dashboard.status). */
function renderStatus({ months, totals }) {
  if (!months.length) {
    setChildren($('#tbl-status'), noData());
    return;
  }
  const heads = ['', ...months.map((m) => monthLabel(m.month)), 'Total'];
  const rows = [
    ['In progress', 'in_progress'], ['Completed', 'completed'], ['Cancelled', 'cancelled'],
    ['Open lines', 'open'], ['Closed lines', 'closed'],
  ].map(([label, key]) => [[label, ...months.map((m) => m[key]), totals[key]]]);
  setChildren($('#tbl-status'), figTable(heads, rows));
}

const VIEWS = ['agents', 'opr', 'customers', 'overview'];
const VIEW_KEY = 'sheet.dashboard.view';
// The filters a view does not use: hidden there while empty (one that is set stays visible, since it still applies).
const UNUSED = { opr: ['#d-opr'], customers: ['#d-agent'] };

function savedView() {
  try {
    const view = localStorage.getItem(VIEW_KEY);
    return VIEWS.includes(view) ? view : 'agents';
  } catch {
    return 'agents'; // no storage: the first view
  }
}

let view = savedView();

function applyView() {
  for (const el of document.querySelectorAll('[data-dash-view]')) el.hidden = el.dataset.dashView !== view;
  for (const tab of document.querySelectorAll('[data-act="dash-view"]')) tab.setAttribute('aria-pressed', String(tab.dataset.view === view));
  for (const selector of ['#d-opr', '#d-agent']) {
    const select = $(selector);
    if (select) select.hidden = (UNUSED[view] || []).includes(selector) && !select.value;
  }
}

/** Shows one view of the Dashboard (no reload: every view is drawn from the same figures). */
export function showDashboardView(next) {
  if (!VIEWS.includes(next)) return;
  view = next;
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    // no storage (private window): the view is kept until the page reloads
  }
  applyView();
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function headline(selector, parts) {
  setChildren($(selector), parts.filter(Boolean).join(' · '));
}

function renderHeadlines({ agents, oprs, totals, customers, count }) {
  const busiest = agents.find((a) => a.agent);
  headline('#hl-agents', [plural(totals.jobs, 'job', 'jobs'), plural(agents.filter((a) => a.agent).length, 'agent', 'agents'),
    busiest ? `busiest: ${busiest.agent}` : '']);
  headline('#hl-opr', [plural(count, 'vessel', 'vessels'), plural(oprs.reduce((n, o) => n + o.services, 0), 'service', 'services'),
    plural(oprs.length, 'OPR', 'OPRs')]);
  headline('#hl-customers', [plural(customers.reduce((n, c) => n + c.jobs, 0), 'job', 'jobs'),
    plural(customers.filter((c) => c.id !== null).length, 'customer', 'customers')]);
  headline('#hl-overview', [plural(totals.services, 'service', 'services'), plural(count, 'vessel', 'vessels')]);
}

function renderOpr(oprs) {
  const items = oprs.map((o) => ({ label: o.opr, value: o.vessels }));
  setChildren($('#chart-vessels'), items.some((i) => i.value)
    ? donutEl(items, { dataset: (item) => ({ act: 'opr-summary', opr: item.label }), total: 'Vessels per OPR' })
    : noData());
  setChildren($('#tbl-opr'), oprs.length
    ? figTable(['OPR', 'Vessels', 'Services'], [
      ...oprs.map((o) => [[o.opr, o.vessels, o.services], { class: 'clickable', dataset: { act: 'opr-summary', opr: o.opr } }]),
      [['Total', oprs.reduce((n, o) => n + o.vessels, 0), oprs.reduce((n, o) => n + o.services, 0)], { class: 'total' }],
    ])
    : noData());
}

const HEAT_STEPS = 5;
const heatClass = (n, max) => (n ? `heat heat-${Math.max(1, Math.ceil((n / max) * HEAT_STEPS))}` : 'heat');

function renderCustomers(customers) {
  if (!customers.length) {
    setChildren($('#tbl-customers'), noData());
    setChildren($('#heat-customers'), noData());
    return;
  }
  const total = customers.reduce((n, c) => n + c.jobs, 0);
  setChildren($('#tbl-customers'), figTable(['Customer', 'Jobs'], [
    ...customers.map((c) => [[c.name, c.jobs], c.id === null ? { class: 'no-agent' } : null]),
    [['Total', total], { class: 'total' }],
  ]));
  const ports = ME.multiPort ? [...new Set(customers.flatMap((c) => c.places.map((p) => p.port)))] : [];
  const max = Math.max(...customers.flatMap((c) => c.places.map((p) => p.jobs)), 1);
  const rows = [];
  for (const c of customers) {
    const pocs = [...new Set(c.places.map((p) => p.poc))];
    for (const poc of pocs) {
      const here = c.places.filter((p) => p.poc === poc);
      const cells = ME.multiPort
        ? ports.map((port) => {
          const n = here.find((p) => p.port === port)?.jobs || 0;
          return h('td', { class: heatClass(n, max) }, n || '');
        })
        : [h('td', { class: heatClass(here.reduce((n, p) => n + p.jobs, 0), max) }, here.reduce((n, p) => n + p.jobs, 0))];
      rows.push([[c.name, poc || '(no POC)', ...cells], c.id === null ? { class: 'no-agent' } : null]);
    }
  }
  setChildren($('#heat-customers'), figTable(['Customer', 'POC', ...(ME.multiPort ? ports.map((p) => PORT_LABEL[p] || p) : ['Jobs'])], rows));
}

export function renderDashboard() {
  const data = state.dashboard;
  const { count, oprs } = data;
  $('#dash-count').textContent = count;
  renderFilters();
  renderAgents(data);
  renderMonths(data);
  renderStatus(data.status);
  renderOpr(oprs);
  renderCustomers(data.customers);
  renderHeadlines(data);
  const labels = oprs.map((o) => o.opr);
  const column = (key) => oprs.map((o) => o[key]);
  renderBars('#chart-services', labels, column('services'), (n) => n);
  if (seeMoney()) {
    renderBars('#chart-cost', labels, column('cost_egp'), fmtShort);
    renderBars('#chart-profit', labels, column('profit_egp'), fmtShort);
  }
  renderOprCards(oprs);
  applyView();
}
