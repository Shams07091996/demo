// Exchange rates page.
import { deleteBtn } from '../components.js';
import { ME, PORTS } from '../config.js';
import { h, icon, optionEls, setChildren } from '../dom.js';
import { state } from '../state.js';
import { setStatus } from '../feedback.js';
import { $, fmt, localISO } from '../util.js';

export function renderRatesPage() {
  const chips = state.rates.map((r) => h('span', { class: 'rate-chip' }, `${r.label} `, h('b', null, r.rate),
    ME.isAdmin ? deleteBtn('del-rate', { id: r.id }, 'ghost small') : null));
  // Rates are shared by every port, so only admins may change them (the server enforces this too).
  let form = null;
  if (ME.isAdmin) {
    const field = (label, ...control) => h('div', { class: 'field' }, label ? h('label', null, label) : null, control);
    form = [
      h('div', { class: 'section-title', style: { marginTop: '18px' } }, h('span', null, 'Add or update a rate')),
      h('div', { class: 'row three', id: 'rate-form', style: { maxWidth: '640px', alignItems: 'end' } },
        field('Month', h('input', { attrs: { type: 'month', name: 'month' }, value: localISO().slice(0, 7) })),
        field('Rate (EGP per USD)', h('input', { attrs: { type: 'number', step: 'any', min: 0, name: 'rate', placeholder: 'e.g. 50.25' } })),
        field(null, h('button', { class: 'btn primary', dataset: { act: 'save-rate' } }, 'Save rate'))),
    ];
  } else {
    form = h('p', { class: 'help' }, 'Exchange rates are shared by every port; ask an admin to add or change one.');
  }
  setChildren($('#rates-panel'), chips.length ? chips : h('div', { class: 'none' }, 'No rates set yet.'), form);
  renderPricesPanel();
}

const KINDS = [['garbage', 'Garbage', 'm³'], ['sludge', 'Sludge', 't']];
const SIDES = [['revenue', 'revenue', 'USD'], ['cost', 'cost', 'EGP']];
const BLOCKS = KINDS.flatMap(([kind, label, unit]) => SIDES.map(([side, sideLabel, currency]) =>
  ({ kind, side, unit, currency, title: `${label} ${sideLabel}` })));

/** "3 m³ min · USD 250.00 + 60.00 / m³" */
const blockText = (b, unit) => `${b.min_qty} ${unit} min · ${b.currency} ${fmt(b.min)} + ${fmt(b.extra)} / ${unit}`;

function blockFields(b) {
  const key = (name) => `${b.kind}.${b.side}.${name}`;
  const input = (name, label) => h('div', { class: 'field' }, h('label', null, label),
    h('input', { attrs: { type: 'number', step: 'any', min: 0, name: key(name) } }));
  return h('div', { class: 'price-block' }, h('div', { class: 'section-title' }, h('span', null, b.title)),
    h('div', { class: 'row two' },
      input('min_qty', `Minimum (${b.unit})`),
      input('min', 'Minimum amount'),
      h('div', { class: 'field' }, h('label', null, 'Currency'),
        h('select', { attrs: { name: key('currency') } }, optionEls([['EGP', 'EGP'], ['USD', 'USD']], b.currency))),
      input('extra', `Extra per ${b.unit} above`)));
}

/** The price form as the server expects it: {month, port, garbage: {revenue: {...}, cost: {...}}, sludge: {...}}. */
export function readPriceForm() {
  const form = $('#price-form');
  const out = { month: form.querySelector('[name=month]').value, port: form.querySelector('[name=port]').value };
  BLOCKS.forEach(({ kind, side }) => {
    out[kind] = out[kind] || {};
    out[kind][side] = Object.fromEntries(['min_qty', 'min', 'currency', 'extra']
      .map((name) => [name, form.querySelector(`[name="${kind}.${side}.${name}"]`).value]));
  });
  return out;
}

/** Fill the form with the chosen port's most recent prices before the chosen month. */
export function copyLastMonth() {
  const form = $('#price-form');
  const month = form.querySelector('[name=month]').value;
  const port = form.querySelector('[name=port]').value;
  const last = state.prices.filter((p) => p.port === port && p.month < month).sort((a, b) => (a.month < b.month ? 1 : -1))[0];
  if (!last) {
    setStatus('error', 'No earlier prices for this port.');
    return;
  }
  BLOCKS.forEach(({ kind, side }) => ['min_qty', 'min', 'currency', 'extra'].forEach((name) => {
    form.querySelector(`[name="${kind}.${side}.${name}"]`).value = String(last[kind][side][name]);
  }));
  setStatus('ok', `Copied from ${last.label}`);
}

/** Garbage & Sludge prices for each month and port. Admins change them; everyone else reads. */
export function renderPricesPanel() {
  const panel = $('#prices-panel');
  if (!panel) return;
  // Saving draws the panel again: keep the month and port chosen, so the next month can be copied straight away.
  const kept = { month: panel.querySelector('#price-form [name=month]')?.value, port: panel.querySelector('#price-form [name=port]')?.value };
  const table = state.prices.length
    ? h('div', { class: 'table-wrap' }, h('table', { id: 'prices-table' },
      h('thead', null, h('tr', null, h('th', null, 'Month'), h('th', null, 'Port'),
        BLOCKS.map((b) => h('th', null, b.title)), ME.isAdmin ? h('th', null) : null)),
      h('tbody', null, state.prices.map((p) => h('tr', null, h('td', null, p.label), h('td', null, p.port_label),
        BLOCKS.map((b) => h('td', null, blockText(p[b.kind][b.side], b.unit))),
        ME.isAdmin
          ? h('td', null, h('button', { class: 'btn ghost small', dataset: { act: 'del-price', id: p.id }, attrs: { title: 'Delete', 'aria-label': 'Delete' } }, icon('trash')))
          : null)))))
    : h('div', { class: 'none' }, 'No prices set yet.');
  let form = null;
  if (ME.isAdmin) {
    const field = (label, ...control) => h('div', { class: 'field' }, label ? h('label', null, label) : null, control);
    form = h('div', { id: 'price-form', class: 'price-form' },
      h('div', { class: 'section-title', style: { marginTop: '18px' } }, h('span', null, 'Add or update prices')),
      h('div', { class: 'row three', style: { alignItems: 'end' } },
        field('Month', h('input', { attrs: { type: 'month', name: 'month' }, value: kept.month || localISO().slice(0, 7) })),
        field('Port', h('select', { attrs: { name: 'port' } }, optionEls(PORTS.map((p) => [p.key, p.label]), kept.port))),
        field(null, h('button', { class: 'btn ghost', dataset: { act: 'copy-price' } }, 'Copy from last month'))),
      h('div', { class: 'price-blocks' }, BLOCKS.map(blockFields)),
      h('button', { class: 'btn primary', dataset: { act: 'save-price' } }, 'Save prices'));
  }
  setChildren(panel, table, form);
}
