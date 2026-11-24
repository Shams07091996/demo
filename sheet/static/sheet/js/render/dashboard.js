// The dashboard tab, as the server totals it (state.dashboard, loaded by data.loadDashboard): its own filters, jobs
// per agent, services and money per month, then the OPR charts and cards. Charts are plain divs (no library).
import { CHART_COLORS, NO_AGENT, TYPES } from '../config.js';
import { state } from '../state.js';
import { h, optionEls, setChildren } from '../dom.js';
import { $, fmt, fmtShort } from '../util.js';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = (ym) => `${MONTH_NAMES[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;
const typeColor = (type) => CHART_COLORS[Math.max(0, TYPES.indexOf(type)) % CHART_COLORS.length];
const agentLabel = (agent) => agent || '(no agent)';
const noData = () => h('div', { class: 'none' }, 'No data.');

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
        h('div', { class: 'num', style: { marginTop: '4px' } }, `${fmtShort(t.cost_egp)} LE cost`));
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
    for (const selector of ['#chart-months', '#tbl-months', '#tbl-money']) setChildren($(selector), noData());
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

export function renderDashboard() {
  const data = state.dashboard;
  const { count, oprs } = data;
  $('#dash-count').textContent = count;
  renderFilters();
  renderAgents(data);
  renderMonths(data);
  renderStatus(data.status);
  const labels = oprs.map((o) => o.opr);
  const column = (key) => oprs.map((o) => o[key]);
  renderBars('#chart-vessels', labels, column('vessels'), (n) => n);
  renderBars('#chart-services', labels, column('services'), (n) => n);
  renderBars('#chart-cost', labels, column('cost_egp'), fmtShort);
  renderBars('#chart-profit', labels, column('profit_egp'), fmtShort);
  renderOprCards(oprs);
}
