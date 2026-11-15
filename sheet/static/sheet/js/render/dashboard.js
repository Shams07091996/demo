// The dashboard tab: charts and OPR cards for the chosen date range and port, as the server totals them
// (state.dashboard, loaded by data.loadDashboard).
import { CHART_COLORS } from '../config.js';
import { state } from '../state.js';
import { $, esc, fmtShort } from '../util.js';

function renderBars(selector, labels, values, format) {
  const container = $(selector);
  if (!labels.length) {
    container.innerHTML = '<div class="none">No data.</div>';
    return;
  }
  const max = Math.max(...values.map(Math.abs), 1);
  const bars = labels.map((label, i) => {
    const height = Math.max(4, Math.round((Math.abs(values[i]) / max) * 170));
    const color = values[i] < 0 ? 'var(--danger)' : CHART_COLORS[i % CHART_COLORS.length];
    return `<div class="bar" data-act="opr-summary" data-opr="${esc(label)}" title="${esc(label)}">
      <div class="v">${esc(format(values[i]))}</div>
      <div class="fill" style="height:${height}px;background:${color}"></div>
      <div class="l">${esc(label)}</div></div>`;
  });
  container.innerHTML = `<div class="bars">${bars.join('')}</div>`;
}

function renderOprCards(oprs) {
  $('#opr-cards').innerHTML = oprs.length
    ? oprs.map((t, i) => {
        const color = CHART_COLORS[i % CHART_COLORS.length];
        return `<div class="opr-card" data-act="opr-summary" data-opr="${esc(t.opr)}" style="border-color:${color}55">
          <div class="n" style="color:${color}">${esc(t.opr)}</div>
          <div class="big">${t.vessels} <small>vessels</small></div>
          <div class="none">${t.services} services</div>
          <div class="num" style="margin-top:4px">${esc(fmtShort(t.cost_egp))} LE cost</div>
          <div style="font-size:11px;color:${color};margin-top:10px;opacity:.7">Click for details →</div></div>`;
      }).join('')
    : '<div class="none">No data for the selected filters.</div>';
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
