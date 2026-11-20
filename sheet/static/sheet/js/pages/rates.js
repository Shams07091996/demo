// Exchange rates page.
import { ME, PORTS } from '../config.js';
import { h, icon, optionEls, setChildren } from '../dom.js';
import { state } from '../state.js';
import { $, fmt, localISO } from '../util.js';

export function renderRatesPage() {
  const chips = state.rates.map((r) => h('span', { class: 'rate-chip' }, `${r.label} `, h('b', null, r.rate),
    ME.isAdmin ? h('button', { dataset: { act: 'del-rate', id: r.id }, attrs: { title: 'Delete', 'aria-label': 'Delete' } }, icon('trash')) : null));
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
  } else if (ME.canEdit) {
    form = h('p', { class: 'help' }, 'Exchange rates are shared by every port; ask an admin to add or change one.');
  }
  setChildren($('#rates-panel'), chips.length ? chips : h('div', { class: 'none' }, 'No rates set yet.'), form);
  renderPricesPanel();
}

const PRICE_COLUMNS = [
  ['garbage_cost', 'Garbage cost'], ['garbage_revenue', 'Garbage revenue'],
  ['sludge_cost', 'Sludge cost'], ['sludge_revenue', 'Sludge revenue'],
];

/** Garbage & Sludge prices (USD per m³) for each month and port. Admins change them; everyone else reads. */
export function renderPricesPanel() {
  const panel = $('#prices-panel');
  if (!panel) return;
  const table = state.prices.length
    ? h('div', { class: 'table-wrap' }, h('table', { id: 'prices-table' },
      h('thead', null, h('tr', null, h('th', null, 'Month'), h('th', null, 'Port'),
        PRICE_COLUMNS.map(([, label]) => h('th', { class: 'num' }, label)), ME.isAdmin ? h('th', null) : null)),
      h('tbody', null, state.prices.map((p) => h('tr', null, h('td', null, p.label), h('td', null, p.port_label),
        PRICE_COLUMNS.map(([key]) => h('td', { class: 'num' }, fmt(p[key]))),
        ME.isAdmin
          ? h('td', null, h('button', { class: 'btn ghost small', dataset: { act: 'del-price', id: p.id }, attrs: { title: 'Delete', 'aria-label': 'Delete' } }, icon('trash')))
          : null)))))
    : h('div', { class: 'none' }, 'No prices set yet.');
  let form = null;
  if (ME.isAdmin) {
    const field = (label, ...control) => h('div', { class: 'field' }, label ? h('label', null, label) : null, control);
    const amount = (name) => h('input', { attrs: { type: 'number', step: 'any', min: 0, name } });
    form = [
      h('div', { class: 'section-title', style: { marginTop: '18px' } }, h('span', null, 'Add or update prices')),
      h('div', { class: 'row three', id: 'price-form', style: { maxWidth: '900px', alignItems: 'end' } },
        field('Month', h('input', { attrs: { type: 'month', name: 'month' }, value: localISO().slice(0, 7) })),
        field('Port', h('select', { attrs: { name: 'port' } }, optionEls(PORTS.map((p) => [p.key, p.label])))),
        PRICE_COLUMNS.map(([key, label]) => field(label, amount(key))),
        field(null, h('button', { class: 'btn primary', dataset: { act: 'save-price' } }, 'Save prices'))),
    ];
  }
  setChildren(panel, table, form);
}
