// Small HTML building blocks shared by several screens. Every dynamic value is escaped.
import { PORTS, PORT_LABEL, STATUS_LABEL, TIME_FIELDS } from './config.js';
import { h, optionEls } from './dom.js';
import { optionValues } from './state.js';
import { dmy, esc, fmt, fmtDuration, fmtStamp, oprClass, sign } from './util.js';

export const head = (title, meta = '') => `
  <div class="m-head">
    <div><h2>${esc(title)}</h2>${meta ? `<div class="m-meta">${meta}</div>` : ''}</div>
    <button class="x" data-act="close" aria-label="Close">✕</button>
  </div>`;

export const metaBadges = (v) => `
  <span class="badge opr-${oprClass(v.opr)}">${esc(v.opr || '—')}</span>
  <span class="badge poc">${esc(v.poc || '—')}</span>
  <span>📅 ${dmy(v.date)}</span>
  <span>⚓ ${esc(PORT_LABEL[v.port] || v.port)}</span>`;

/** `label` and `value` must already be safe HTML (escape user data before passing it in). */
export const pill = (label, value, cls = '') =>
  `<div class="pill ${cls}"><span>${label}</span><b>${value}</b></div>`;

export const profitClass = (n) => (n >= 0 ? 'good' : 'bad');

export function moneyPills(type, calc) {
  if (!calc.cost_egp && !calc.revenue_egp && type !== 'Cash to Master') return ''; // no money entered
  if (type === 'Cash to Master') {
    return `<div class="pills">
      ${pill('Our revenue', `LE ${fmt(calc.revenue_egp)}`, 'good')}
      ${pill('Paid to master', `LE ${fmt(calc.to_master_egp)}`)}
      ${pill('Profit', `LE ${sign(calc.profit_egp)}`, profitClass(calc.profit_egp))}</div>`;
  }
  return `<div class="pills">
    ${pill('Cost', `LE ${fmt(calc.cost_egp)}`)}
    ${pill('Revenue', `LE ${fmt(calc.revenue_egp)}`)}
    ${pill('Profit', `LE ${sign(calc.profit_egp)}`, profitClass(calc.profit_egp))}</div>`;
}

/** Label for a service tag; crew changes show how many people are on / off. */
export function tagLabel(service) {
  if (service.type !== 'Crew Change') return service.type;
  const data = service.data || {};
  return `Crew Change (${(data.onSigners || []).length} on / ${(data.offSigners || []).length} off)`;
}

export const statusChip = (status) =>
  `<span class="status-chip st-${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;

/** <option> list for an OPR / POC / Agent dropdown; keeps a value that is no longer in the master list. */
/** <option>s for a Master-data list; with `port`, only values for that port (+ All ports). `current` is always kept. */
export function optionChoices(kind, current = '', port = null) {
  const values = optionValues(kind, port);
  const all = current && !values.includes(current) ? [...values, current] : values;
  return `<option value="">—</option>${all.map((v) => `<option ${v === current ? 'selected' : ''}>${esc(v)}</option>`).join('')}`;
}

/** Agent, the five port-call times and how long each stage took. */
export function portCallBlock(vessel) {
  const card = (label, value) => `<div class="sum-card"><span>${esc(label)}</span><b>${value ? esc(value) : '—'}</b></div>`;
  const cells = TIME_FIELDS.map(({ key, label }) => card(label, fmtStamp(vessel[key])));
  const d = vessel.durations || {};
  const durations = [['Operations', d.ops_hours], ['At berth', d.berth_hours], ['Total in port', d.port_hours]]
    .filter(([, hours]) => hours !== null && hours !== undefined)
    .map(([label, hours]) => pill(label, esc(fmtDuration(hours))));
  return `<div class="sum-grid">${card('Agent', vessel.agent)}${cells.join('')}</div>
    ${durations.length ? `<div class="pills">${durations.join('')}</div>` : ''}`;
}

/** "Crew Change ×1 · Fresh Water ×2" as chips. */
export function serviceCounts(vessel) {
  const counts = {};
  vessel.services.forEach((s) => { counts[s.type] = (counts[s.type] || 0) + 1; });
  const chips = Object.entries(counts).map(([type, n]) => `<span class="svc-chip">${esc(type)} ×${n}</span>`);
  return chips.join('') || '<span class="none"><i>No services</i></span>';
}

/* ---- element builders (no HTML strings) ---- */

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
