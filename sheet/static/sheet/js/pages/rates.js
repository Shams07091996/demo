// Exchange rates page.
import { ME } from '../config.js';
import { h, icon, setChildren } from '../dom.js';
import { state } from '../state.js';
import { $, localISO } from '../util.js';

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
}
