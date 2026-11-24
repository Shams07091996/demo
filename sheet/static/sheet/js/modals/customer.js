// The customer dialog: name, notes, active, contacts, agreed rates (one per service type; what a rate means is
// RATE_UNITS) and the linked ships. Admins edit; everyone else sees it read-only.
import { api, mutate } from '../api.js';
import { headEl } from '../components.js';
import { ME, RATE_UNITS, can } from '../config.js';
import { h, optionEls } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { loadCustomers } from '../parties.js';
import { state } from '../state.js';
import { $, $$ } from '../util.js';

const UNIT_LABEL = { service: 'per service', unit: 'per unit', line: 'per line', percent: '%' };
const CURRENCIES = [['USD', 'USD'], ['EGP', 'EGP']];
const MAX_CONTACTS = 20;

// customers.edit: names, notes, contacts; the agreed rates are money and also need money.edit.
const mayEdit = () => can('customers.edit');
const mayRate = () => mayEdit() && can('money.edit');
const input = (name, value, attrs = {}, editable = mayEdit()) =>
  h('input', { attrs: { name, ...attrs }, value, disabled: !editable });

function contactRowEl(c = {}) {
  return h('div', { class: 'contact-row row four' },
    input('c_name', c.name, { maxlength: 100, 'aria-label': 'Name' }),
    input('c_role', c.role, { maxlength: 60, 'aria-label': 'Role' }),
    input('c_email', c.email, { maxlength: 254, type: 'email', 'aria-label': 'Email' }),
    h('div', { class: 'with-btn' }, input('c_phone', c.phone, { maxlength: 40, type: 'tel', 'aria-label': 'Phone' }),
      mayEdit() ? h('button', { class: 'btn ghost small', attrs: { type: 'button', title: 'Remove' }, dataset: { act: 'contact-remove' } }, 'Remove') : null));
}

function rateRowEl(type, rate) {
  const unit = RATE_UNITS[type];
  return h('div', { class: 'rate-row', dataset: { type } },
    h('span', { class: 'rate-type' }, type),
    input('r_amount', rate?.amount ?? '', { type: 'number', min: 0, step: '0.01', 'aria-label': `${type} rate` }, mayRate()),
    unit === 'percent' ? h('span') : h('select', { attrs: { name: 'r_currency' }, disabled: !mayRate() },
      optionEls(CURRENCIES, rate?.currency || 'USD')),
    h('span', { class: 'none' }, UNIT_LABEL[unit]));
}

export function openCustomerDialog(customer, onDone) {
  state.ctx = { view: 'customer', customerId: customer?.id ?? null, onDone };
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  const title = customer ? (mayEdit() ? 'Edit customer' : customer.name) : 'Add customer';
  openModal(
    headEl(title),
    h('div', { class: 'm-body', id: 'customer-form' },
      h('div', { class: 'row two' },
        h('div', { class: 'field' }, h('label', null, 'Name'), input('name', customer?.name, { maxlength: 120 })),
        h('div', { class: 'field' }, h('label', null, 'Notes'), input('notes', customer?.notes, { maxlength: 500 }))),
      h('label', { class: 'tick' }, h('input', { attrs: { type: 'checkbox', name: 'active' }, checked: customer ? customer.active : true, disabled: !mayEdit() }), ' Active'),
      h('div', { class: 'section-title' }, h('span', null, 'Contacts'),
        mayEdit() ? h('button', { class: 'btn ghost small', attrs: { type: 'button' }, dataset: { act: 'contact-add' } }, '+ Contact') : null),
      h('div', { class: 'contact-row row four contact-head' }, ['Name', 'Role', 'Email', 'Phone'].map((t) => h('span', { class: 'none' }, t))),
      h('div', { id: 'cu-contacts' }, (customer?.contacts || []).map(contactRowEl)),
      h('div', { class: 'section-title' }, h('span', null, 'Agreed rates')),
      Object.keys(RATE_UNITS).map((type) => rateRowEl(type, customer?.rates?.[type])),
      customer ? h('div', { class: 'section-title' }, h('span', null, 'Ships')) : null,
      customer
        ? h('div', { class: 'linked-ships' }, customer.ships.length
          ? customer.ships.map((s) => h('button', { class: 'btn ghost small', attrs: { type: 'button' }, dataset: { act: 'customer-ship', id: s.id } },
            `${s.name} · ${s.imo || 'No IMO'}`))
          : h('span', { class: 'none' }, 'None'))
        : null),
    h('div', { class: 'm-foot' },
      customer && ME.isAdmin ? btn('danger', 'customer-del', 'Delete') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', mayEdit() ? 'Cancel' : 'Close'),
        mayEdit() ? ' ' : null, mayEdit() ? btn('primary', 'customer-save', 'Save') : null)),
  );
}

export function addContactRow() {
  const box = $('#cu-contacts');
  if (box && box.children.length < MAX_CONTACTS) box.append(contactRowEl());
}

function readCustomer() {
  const root = $('#customer-form');
  const value = (name, el = root) => $(`[name="${name}"]`, el).value.trim();
  const rates = {};
  $$('.rate-row', root).forEach((row) => {
    const amount = value('r_amount', row);
    if (amount === '') return; // no agreed rate for this type
    const currency = $('[name="r_currency"]', row);
    rates[row.dataset.type] = { amount, ...(currency ? { currency: currency.value } : {}) };
  });
  return {
    name: value('name'),
    notes: value('notes'),
    active: $('[name="active"]', root).checked,
    contacts: $$('#cu-contacts .contact-row', root).map((row) => ({
      name: value('c_name', row), role: value('c_role', row), email: value('c_email', row), phone: value('c_phone', row),
    })),
    rates,
  };
}

let saving = false;

export async function saveCustomerDialog() {
  if (saving || state.ctx.view !== 'customer') return;
  const { customerId, onDone } = state.ctx;
  saving = true;
  try {
    const payload = readCustomer();
    await mutate(() => (customerId ? api(`/api/customers/${customerId}/`, 'PUT', payload) : api('/api/customers/', 'POST', payload)));
  } catch {
    return;
  } finally {
    saving = false;
  }
  await loadCustomers(true);
  closeModal();
  await onDone?.();
}

export async function deleteCustomerDialog() {
  if (state.ctx.view !== 'customer' || !confirm('Delete this customer? This cannot be undone.')) return;
  const { customerId, onDone } = state.ctx;
  try {
    await mutate(() => api(`/api/customers/${customerId}/`, 'DELETE'));
  } catch {
    return;
  }
  await loadCustomers(true);
  closeModal();
  await onDone?.();
}
