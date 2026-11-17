// Small building blocks shared by several screens. They return elements (built with h()), never HTML strings.
import { PORTS, PORT_LABEL, STATUS_LABEL, TIME_FIELDS } from './config.js';
import { h, optionEls } from './dom.js';
import { optionValues } from './state.js';
import { dmy, fmt, fmtDuration, fmtStamp, oprClass, sign } from './util.js';

export const profitClass = (n) => (n >= 0 ? 'good' : 'bad');

/** Label for a service tag; crew changes show how many people are on / off. */
export function tagLabel(service) {
  if (service.type !== 'Crew Change') return service.type;
  const data = service.data || {};
  return `Crew Change (${(data.onSigners || []).length} on / ${(data.offSigners || []).length} off)`;
}

export const statusChipEl = (status) =>
  h('span', { class: `status-chip st-${status}` }, STATUS_LABEL[status] || status);

/** <option>s for a Master-data list; with `port`, only values for that port (+ All ports). `current` is always kept. */
export function optionChoicesEl(kind, current = '', port = null) {
  const values = optionValues(kind, port);
  const all = current && !values.includes(current) ? [...values, current] : values;
  return [h('option', { value: '' }, '—'), ...all.map((v) => h('option', { value: v, selected: v === current }, v))];
}

/** Port <option>s; with `all`, a first "🌐 All ports" option (value ALL). */
export const portOptionEls = ({ all = false, selected = '' } = {}) =>
  optionEls([...(all ? [['ALL', '🌐 All ports']] : []), ...PORTS.map((p) => [p.key, p.label])], selected);

/** Dialog header: title, optional meta line (nodes or text), close button. */
export const headEl = (title, meta = null) =>
  h('div', { class: 'm-head' },
    h('div', null, h('h2', null, title), meta ? h('div', { class: 'm-meta' }, meta) : null),
    h('button', { class: 'x', dataset: { act: 'close' }, attrs: { 'aria-label': 'Close' } }, '✕'));

export const metaBadgesEl = (v) => [
  h('span', { class: `badge opr-${oprClass(v.opr)}` }, v.opr || '—'), ' ',
  h('span', { class: 'badge poc' }, v.poc || '—'), ' ',
  h('span', null, `📅 ${dmy(v.date)}`), ' ',
  h('span', null, `⚓ ${PORT_LABEL[v.port] || v.port}`),
];

/** A label / value pill; both are inserted as text (or nodes). */
export const pillEl = (label, value, cls = '') =>
  h('div', { class: `pill ${cls}`.trim() }, h('span', null, label), h('b', null, value));

export function moneyPillsEl(type, calc) {
  if (!calc.cost_egp && !calc.revenue_egp && type !== 'Cash to Master') return null; // no money entered
  const profit = pillEl('Profit', `LE ${sign(calc.profit_egp)}`, profitClass(calc.profit_egp));
  if (type === 'Cash to Master') {
    return h('div', { class: 'pills' },
      pillEl('Our revenue', `LE ${fmt(calc.revenue_egp)}`, 'good'), pillEl('Paid to master', `LE ${fmt(calc.to_master_egp)}`), profit);
  }
  return h('div', { class: 'pills' }, pillEl('Cost', `LE ${fmt(calc.cost_egp)}`), pillEl('Revenue', `LE ${fmt(calc.revenue_egp)}`), profit);
}

/** Agent, the five port-call times and how long each stage took. */
export function portCallBlockEl(vessel) {
  const card = (label, value) => h('div', { class: 'sum-card' }, h('span', null, label), h('b', null, value || '—'));
  const d = vessel.durations || {};
  const durations = [['Operations', d.ops_hours], ['At berth', d.berth_hours], ['Total in port', d.port_hours]]
    .filter(([, hours]) => hours !== null && hours !== undefined)
    .map(([label, hours]) => pillEl(label, fmtDuration(hours)));
  return [
    h('div', { class: 'sum-grid' }, card('Agent', vessel.agent), TIME_FIELDS.map(({ key, label }) => card(label, fmtStamp(vessel[key])))),
    durations.length ? h('div', { class: 'pills' }, durations) : null,
  ];
}

/** "Crew Change ×1 · Fresh Water ×2" as chips. */
export function serviceCountsEl(vessel) {
  const counts = {};
  vessel.services.forEach((s) => { counts[s.type] = (counts[s.type] || 0) + 1; });
  const chips = Object.entries(counts).map(([type, n]) => h('span', { class: 'svc-chip' }, `${type} ×${n}`));
  return chips.length ? chips : h('span', { class: 'none' }, h('i', null, 'No services'));
}
