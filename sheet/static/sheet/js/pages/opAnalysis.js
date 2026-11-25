// Analysis reports and Report charts (Operation): one filter and one server response for both pages, so their
// figures always agree. Analysis shows the headline figures and two tables; Charts draws two bar charts.
import { api } from '../api.js';
import { portOptionEls } from '../components.js';
import { CHART_COLORS, ME } from '../config.js';
import { h, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { figure, loadTerminals, opFilter, opQuery, terminalOptionEls } from '../operation/shared.js';
import { $, $$ } from '../util.js';

const BAR_HEIGHT = 170;
let data = null;
let ticket = 0;
const wiredPages = new Set();

const HEADS = [['calls', 'Vessel calls'], ['waiting', 'Avg waiting (hrs)'], ['operation', 'Avg operation (hrs)'],
  ['port_stay', 'Avg port stay (hrs)'], ['loa', 'Avg LOA (m)'], ['cranes', 'Avg cranes'],
  ['productivity', 'Avg moves/hr'], ['total_moves', 'Total moves'], ['berthed', 'Berthed calls']];

function figuresTable(first, rows) {
  return h('table', null,
    h('thead', null, h('tr', null, h('th', null, first), HEADS.map(([, title]) => h('th', null, title)))),
    h('tbody', null, rows.length
      ? rows.map((r) => h('tr', null, h('td', null, r.name), HEADS.map(([key]) => h('td', null, figure(r[key])))))
      : h('tr', null, h('td', { class: 'none', attrs: { colspan: HEADS.length + 1 } }, 'None'))));
}

function tiles() {
  const head = data.headline;
  const list = [['Vessel calls', head.calls], ['Avg waiting (hrs)', head.waiting], ['Avg operation (hrs)', head.operation],
    ['Avg port stay (hrs)', head.port_stay], ['Avg moves/hr', head.productivity]];
  if (head.per_week !== null) {
    list.push(['Calls per week', head.per_week], ['Calls per month', head.per_month], ['Calls per year', head.per_year]);
  }
  return list.map(([label, value]) => h('div', { class: 'stat' }, h('b', null, figure(value)), h('span', null, label)));
}

function bars(rows, series) {
  if (!rows.length) return h('div', { class: 'none' }, 'No data.');
  const max = Math.max(1, ...rows.flatMap((r) => series.map(([key]) => r[key] || 0)));
  return h('div', null,
    series.length > 1 ? h('div', { class: 'op-legend' }, series.map(([, label], i) =>
      h('span', null, h('i', { style: { background: CHART_COLORS[i] } }), label))) : null,
    h('div', { class: 'bars' }, rows.map((r) => h('div', { class: 'bar op-bar', attrs: { title: r.name } },
      h('div', { class: 'op-pair' }, series.map(([key], i) => h('div', { class: 'op-col' },
        h('div', { class: 'v' }, figure(r[key])),
        h('div', { class: 'fill', style: { height: `${Math.max(2, Math.round(((r[key] || 0) / max) * BAR_HEIGHT))}px`,
          background: CHART_COLORS[i % CHART_COLORS.length] } })))),
      h('div', { class: 'l' }, r.name)))));
}

function render() {
  if (!data) return;
  for (const prefix of wiredPages) { // only the pages this person has (and has opened)
    const berth = $(`#${prefix}-berth`);
    setChildren(berth, h('option', { value: '' }, 'All berths'), optionEls(data.berth_choices.map((b) => [b, b]), opFilter.berth));
    const line = $(`#${prefix}-line`);
    setChildren(line, h('option', { value: '' }, 'All lines'), optionEls(data.line_choices.map((l) => [l, l]), opFilter.line));
    for (const key of ['port', 'terminal', 'from', 'to']) {
      const input = $(`#${prefix}-${key}`);
      if (input && document.activeElement !== input) input.value = key === 'port' ? opFilter.port || 'ALL' : opFilter[key];
    }
  }
  if ($('#oa-tiles')) {
    setChildren($('#oa-tiles'), tiles());
    setChildren($('#oa-terminals'), figuresTable('Terminal', data.terminals));
    setChildren($('#oa-lines'), figuresTable('Shipping line', data.lines));
  }
  if ($('#oc-calls')) {
    setChildren($('#oc-calls'), bars(data.terminals, [['calls', 'Vessel calls']]));
    setChildren($('#oc-hours'), bars(data.terminals, [['waiting', 'Avg waiting (hrs)'], ['operation', 'Avg operation (hrs)']]));
  }
}

async function load() {
  const mine = ++ticket;
  try {
    const fresh = await api(`/api/operation/analysis/?${opQuery()}`);
    if (mine !== ticket) return;
    data = fresh;
    render();
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
  }
}

function setFilter(patch) {
  Object.assign(opFilter, patch);
  return load();
}

async function wire(prefix) {
  if (wiredPages.has(prefix)) return;
  wiredPages.add(prefix);
  const terminals = await loadTerminals();
  if (ME.multiPort) {
    const port = $(`#${prefix}-port`);
    setChildren(port, portOptionEls({ all: true }));
    port.hidden = false;
    port.addEventListener('change', () => setFilter({ port: port.value === 'ALL' ? '' : port.value, terminal: '', berth: '' }));
  }
  const terminal = $(`#${prefix}-terminal`);
  setChildren(terminal, terminalOptionEls(terminals, opFilter.terminal));
  terminal.addEventListener('change', () => setFilter({ terminal: terminal.value, berth: '' }));
  $(`#${prefix}-berth`).addEventListener('change', (event) => setFilter({ berth: event.target.value }));
  $(`#${prefix}-line`).addEventListener('change', (event) => setFilter({ line: event.target.value }));
  for (const key of ['from', 'to']) {
    $(`#${prefix}-${key}`).addEventListener('change', (event) => setFilter({ [key]: event.target.value }));
  }
  $(`#${prefix}-clear`).addEventListener('click', () => {
    $$(`#${prefix}-from, #${prefix}-to`).forEach((input) => { input.value = ''; });
    setFilter({ from: '', to: '' });
  });
}

export const opAnalysisPage = {
  async load() {
    await wire('oa');
    await load();
  },
};

export const opChartsPage = {
  async load() {
    await wire('oc');
    await load();
  },
};
