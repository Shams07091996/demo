// The dashboard tab: charts and OPR cards for the chosen date range and port, as the server totals them
// (state.dashboard, loaded by data.loadDashboard).
import { CHART_COLORS } from '../config.js';
import { state } from '../state.js';
import { h, setChildren } from '../dom.js';
import { $, fmtShort } from '../util.js';

function renderBars(selector, labels, values, format) {
  const container = $(selector);
  if (!labels.length) {
    setChildren(container, h('div', { class: 'none' }, 'No data.'));
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
      return h('div', { class: 'opr-card', dataset: { act: 'opr-summary', opr: t.opr }, style: { borderColor: `${color}55` } },
        h('div', { class: 'n', style: { color } }, t.opr),
        h('div', { class: 'big' }, t.vessels, ' ', h('small', null, 'vessels')),
        h('div', { class: 'none' }, `${t.services} services`),
        h('div', { class: 'num', style: { marginTop: '4px' } }, `${fmtShort(t.cost_egp)} LE cost`),
        h('div', { style: { fontSize: '11px', color, marginTop: '10px', opacity: '.7' } }, 'Click for details →'));
    })
    : h('div', { class: 'none' }, 'No data for the selected filters.'));
}

export function renderDashboard() {
  const { count, oprs } = state.dashboard;
  $('#dash-count').textContent = count;
  const labels = oprs.map((o) => o.opr);
  const column = (key) => oprs.map((o) => o[key]);
  renderBars('#chart-vessels', labels, column('vessels'), (n) => n);
  renderBars('#chart-services', labels, column('services'), (n) => n);
  renderBars('#chart-cost', labels, column('cost_egp'), fmtShort);
  renderBars('#chart-profit', labels, column('profit_egp'), fmtShort);
  renderOprCards(oprs);
}
