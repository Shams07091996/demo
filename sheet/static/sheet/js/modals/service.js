// Adding / editing a service: the type picker, the per-type forms, the live profit preview and the crew editor.
import { api } from '../api.js';
import { calcLocal } from '../calc.js';
import { closedNoteEl, headEl, optionChoicesEl } from '../components.js';
import { BILLING, MULTI, RATE_UNITS, SERVICE_STATUS, SINGLE_EXTRA, TYPES, can } from '../config.js';
import { parseFlightText, parsePersonal } from '../crewParsing.js';
import { h, optionEls, setChildren } from '../dom.js';
import { openModal } from '../modal.js';
import { stripMoney } from '../moneyKeys.js';
import { customerById, customerOptionEls, loadCustomers } from '../parties.js';
import { fillRevenue, rateFor } from '../rates.js';
import { getVessel, state } from '../state.js';
import { $, $$, fmt, formValues, sign, statusNeeds } from '../util.js';

/* ---------- form field builders ---------- */

// The money boxes (and the live preview, the agreed-rate fill, Cancelled -> 0) are there only with money.edit:
// without it the server sends no money and refuses any (sheet/moneyaccess.py).
const mayMoney = () => can('money.edit');

const currencySelect = (props, selected) => h('select', props, optionEls([['EGP', 'EGP'], ['USD', 'USD']], selected));
const numberInput = (props, value, extra = {}) =>
  h('input', { ...props, attrs: { type: 'number', step: 'any', min: 0, ...extra, ...(props.attrs || {}) }, value });
const field = (label, ...control) => h('div', { class: 'field' }, h('label', null, label), control);

const moneyField = (label, amountName, currencyName, data, defaultCurrency) =>
  field(label, h('div', { class: 'row money' },
    numberInput({ attrs: { name: amountName, placeholder: '0.00' } }, data[amountName]),
    currencySelect({ attrs: { name: currencyName } }, data[currencyName] || defaultCurrency)));

const rateField = (vessel, data) =>
  field('Exchange rate override (USD → EGP)',
    numberInput({ attrs: { name: 'exchangeRate', placeholder: 'Leave blank to use the monthly rate' } }, data.exchangeRate),
    h('div', { class: 'hint', style: { margin: '6px 0 0' } },
      `Monthly rate for ${vessel.date.slice(5, 7)}.${vessel.date.slice(0, 4)}: `, h('b', null, vessel.rate ?? 'not set')));

const previewBox = () => h('div', { id: 'preview', class: 'preview' });

// A status the person may not move to (services.cancel / services.complete) is offered but disabled.
function statusSelect(status) {
  const select = h('select', { attrs: { name: 'status' } }, optionEls(Object.entries(SERVICE_STATUS), status));
  [...select.options].forEach((option) => { option.disabled = !statusNeeds(status, option.value).every(can); });
  return select;
}

// Agent and operations status side by side; the reason only while Cancelled is chosen.
const agentStatusFields = (vessel, service) => {
  const status = service?.status || 'in_progress';
  return [
    h('div', { class: 'row two' },
      field('Agent', h('select', { attrs: { name: 'agent' } }, optionChoicesEl('agent', service?.agent || '', vessel.port))),
      field('Status', statusSelect(status))),
    h('div', { class: 'field', id: 'svc-reason', hidden: status !== 'cancelled' },
      h('label', null, 'Cancellation reason'),
      h('textarea', { attrs: { name: 'cancel_reason', maxlength: 500 }, value: service?.cancel_reason || '' })),
    h('div', { class: 'field', id: 'svc-bookings', hidden: true }),
  ];
};

// Who pays and how (a label only). A new service starts billed to its ship's customer.
const billingFields = (vessel, service) => {
  const ship = customerById(vessel.ship?.customer_id ?? null);
  const party = service ? service.billing_party?.id ?? null : (ship?.active ? ship.id : null);
  return [
    h('div', { class: 'row two' },
      field('Billing party', h('select', { attrs: { name: 'billing_party' } }, customerOptionEls(party))),
      field('Billing', h('select', { attrs: { name: 'billing' } }, optionEls(Object.entries(BILLING), service?.billing || 'account')))),
    h('div', { class: 'none rate-note', id: 'svc-rate' }),
  ];
};

const UNIT_TEXT = { service: '', unit: ' per unit', line: ' per line', percent: '%' };

/** Fill the revenue from the billing party's agreed rate (js/rates.js decides which boxes may be filled). */
export function applyRate({ fill = true } = {}) {
  if (state.ctx.view !== 'service-form' || !mayMoney()) return;
  const root = $('#svc-form');
  const partyId = Number($('[name=billing_party]', root).value) || null;
  const rate = rateFor(customerById(partyId), state.ctx.type, RATE_UNITS);
  $('#svc-rate').textContent = rate
    ? `Agreed rate: ${rate.unit === 'percent' ? '' : `${rate.currency} `}${rate.amount}${UNIT_TEXT[rate.unit]}` : '';
  if (!fill || $('[name=status]', root).value === 'cancelled') return;
  const previous = state.ctx.lastRate; // the rate this dialog filled from last (a new payer without one clears it)
  state.ctx.lastRate = rate;
  if (!rate && !previous) return;
  const touched = new Set(state.ctx.touched);
  $$('#entries .entry', root).forEach((row, i) => { if (row.dataset.touched) touched.add(`entry:${i}`); });
  const filled = fillRevenue({ rate, previous, data: readServiceForm(), isNew: state.ctx.isNew, touched });
  const set = (selector, value, el = root) => { const input = $(selector, el); if (input && value !== undefined) input.value = value; };
  set('[name=revenue]', filled.revenue);
  set('[name=revenueCurrency]', filled.revenueCurrency);
  set('[name=percentage]', filled.percentage);
  $$('#entries .entry', root).forEach((row, i) => {
    set('[data-f=revenue]', filled.entries?.[i]?.revenue, row);
    set('[data-f=revenueCurrency]', filled.entries?.[i]?.revenueCurrency, row);
  });
  updatePreview();
}

/** Typing in a revenue box: the agreed rate never overwrites it afterwards (in this dialog). */
function noteTouched(field) {
  if (['revenue', 'revenueCurrency', 'percentage'].includes(field.name)) {
    state.ctx.touched.add(field.name === 'percentage' ? 'percentage' : 'revenue');
  }
  if (field.matches('[data-f=revenue], [data-f=revenueCurrency]')) field.closest('.entry').dataset.touched = '1';
}

/** On choosing Cancelled for a saved Crew Change: its saved hotel stays and transfers, ticked to be cancelled too. */
async function showCrewBookings() {
  const mine = state.ctx;
  const box = () => (state.ctx === mine ? $('#svc-bookings') : null);
  let bookings;
  try {
    ({ bookings } = await api(`/api/services/${mine.serviceId}/bookings/`));
  } catch {
    return; // nothing listed: the crew change is still cancelled, its bookings stay as they are
  }
  if (!box() || $('#svc-form [name=status]').value !== 'cancelled' || !bookings.length) return;
  const item = (b) => h('label', { class: 'bkd-crew-item' },
    h('input', { attrs: { type: 'checkbox' }, dataset: { bk: b.kind, bkId: b.id }, checked: !b.cancelled && !b.closed,
      disabled: b.cancelled || b.closed }),
    ` ${b.label}${b.guests ? ` · ${b.guests}` : ''}`, b.cancelled ? ' · already cancelled' : '', b.closed ? [' ', closedNoteEl()] : null);
  setChildren(box(), h('label', null, 'Cancel these bookings too'), bookings.map(item));
  box().hidden = false;
}

/** The ticked bookings to cancel with the crew change: [{kind, id}]. */
export const cancelBookingRefs = () => $$('#svc-bookings input[data-bk]:checked:not(:disabled)')
  .map((input) => ({ kind: input.dataset.bk, id: Number(input.dataset.bkId) }));

// Choosing Cancelled sets the money to 0 (someone can still type an amount afterwards).
const MONEY_INPUTS = '[name=cost], [name=revenue], [name=amount], [name=fixedRevenue], [data-f=cost], [data-f=revenue]';

export function entryRowEl(type, entry = {}) {
  const isParcel = type === 'Delivery Parcels';
  return h('div', { class: 'entry', dataset: entry.uid ? { uid: entry.uid } : {} },
    h('div', { class: 'entry-head' }, h('span', { class: 'entry-no' }),
      h('button', { class: 'btn danger small', dataset: { act: 'rm-entry' } }, 'Remove')),
    h('div', { class: `row ${isParcel ? 'two' : ''}`.trim() },
      field('AWB No.', h('input', { dataset: { f: 'awb' }, attrs: { placeholder: 'e.g. 123-45678901' }, value: entry.awb })),
      isParcel ? field('Weight (kg)', numberInput({ dataset: { f: 'weight' } }, entry.weight)) : null),
    !mayMoney() ? null : h('div', { class: 'row two' },
      field('Revenue', h('div', { class: 'row money' },
        numberInput({ dataset: { f: 'revenue' } }, entry.revenue),
        currencySelect({ dataset: { f: 'revenueCurrency' } }, entry.revenueCurrency || 'USD'))),
      field('Cost', h('div', { class: 'row money' },
        numberInput({ dataset: { f: 'cost' } }, entry.cost),
        currencySelect({ dataset: { f: 'costCurrency' } }, entry.costCurrency || 'EGP')))));
}

export const renumberEntries = () =>
  $$('#entries .entry').forEach((row, i) => { $('.entry-no', row).textContent = `Entry ${i + 1}`; });

/* ---------- crew editor ---------- */

export const newCrewMember = () => ({
  name: '', flightData: '', personalData: '', personalStructured: {}, flightStructured: { segments: [] }, _open: true,
});

const flightNote = (m) => {
  const count = ((m.flightStructured || {}).segments || []).length;
  return count ? `${count} flight${count > 1 ? 's' : ''} recognised` : '';
};

const personalNote = (m) => {
  const p = m.personalStructured || {};
  const parts = [p.rank && `Rank: ${p.rank}`, p.nationality && `Nationality: ${p.nationality}`].filter(Boolean);
  return parts.length ? parts.join(' · ') : '';
};

const visaField = (m, side, label, defaultCurrency) => {
  const visa = m.brokenVisa || {};
  return field(label, h('div', { class: 'row money' },
    numberInput({ dataset: { crew: `visa.${side}` } }, visa[side] ?? ''),
    currencySelect({ dataset: { crew: `visa.${side}Currency` } }, visa[`${side}Currency`] || defaultCurrency)));
};

// The LOG letter (PDF) of a saved on-signer: a plain link, the server sends it as a download.
const logLink = (m) => (can('documents') && state.ctx.serviceId && m.uid
  ? h('a', { class: 'btn ghost small', href: `/api/services/${state.ctx.serviceId}/log/${m.uid}/`, dataset: { act: 'crew-log' } }, 'LOG')
  : null);

function crewGroupEl(group, label, color) {
  const isOff = group === 'offSigners';
  const cards = state.crew[group].map((m, i) =>
    h('div', { class: `crew-card ${m._open ? 'open' : ''}`.trim(), dataset: { group, i } },
      h('div', { class: 'crew-head', dataset: { act: 'toggle-crew' } },
        h('span', { class: 'crew-name' }, m.name || `Crew member ${i + 1}`),
        h('span', { class: 'crew-actions' }, isOff ? null : logLink(m),
          h('button', { class: 'btn danger small', dataset: { act: 'rm-crew' } }, 'Remove'))),
      h('div', { class: 'crew-body' },
        field('Full name', h('input', { dataset: { crew: 'name' }, value: m.name })),
        field('Flight details', h('textarea', { dataset: { crew: 'flightData' }, value: m.flightData }),
          h('div', { class: 'parsed', dataset: { parsed: 'flight' } }, flightNote(m))),
        field('Personal data', h('textarea', { dataset: { crew: 'personalData' }, value: m.personalData }),
          h('div', { class: 'parsed', dataset: { parsed: 'personal' } }, personalNote(m))),
        h('label', { class: 'check' },
          h('input', { attrs: { type: 'checkbox' }, dataset: { crew: 'needsHotel' }, checked: Boolean(m.needsHotel) }), ' Needs hotel'),
        isOff || !mayMoney() ? null : h('div', { class: 'row two' },
          visaField(m, 'cost', 'Broken visa cost', 'USD'), visaField(m, 'revenue', 'Broken visa revenue', 'USD')))));
  return [
    h('div', { class: 'section-title', style: { ...(isOff ? { marginTop: '16px' } : {}), color } },
      h('span', null, `${label} (${state.crew[group].length})`),
      h('span', null,
        h('button', { class: 'btn ghost small', dataset: { act: 'add-crew', group } }, '+ Add'))),
    cards,
  ];
}

export function renderCrewEditor() {
  setChildren($('#crew-editor'),
    crewGroupEl('onSigners', 'On-signers', 'var(--success)'),
    crewGroupEl('offSigners', 'Off-signers', 'var(--warning)'));
}

/* ---------- screens ---------- */

const footer = (...right) => h('div', { class: 'm-foot' },
  h('button', { class: 'btn ghost', dataset: { act: 'back' } }, right.length ? 'Cancel' : '‹ Back'),
  right.length ? h('div', { class: 'right' }, right) : h('span'));

export function openTypePicker() {
  state.ctx.view = 'type-picker';
  openModal(
    headEl('Add service', getVessel(state.ctx.vesselId).name),
    h('div', { class: 'm-body' }, h('div', { class: 'type-grid' },
      TYPES.map((t) => h('button', { class: 'type-btn', dataset: { act: 'pick-type', type: t } }, t)))),
    footer(),
  );
}

function cashToMasterFields(vessel, d) {
  const fixed = d.shareMode === 'fixed';
  return [
    moneyField('Amount given to the master', 'amount', 'amountCurrency', d, 'USD'),
    h('div', { class: 'row two' },
      field('Our share is', h('select', { attrs: { name: 'shareMode' } },
        optionEls([['percent', 'a percentage of the amount'], ['fixed', 'a fixed figure']], fixed ? 'fixed' : 'percent'))),
      h('div', { class: 'field', id: 'pct-wrap', hidden: fixed }, h('label', null, 'Percentage (%)'),
        numberInput({ attrs: { name: 'percentage' } }, d.percentage, { max: 100 })),
      h('div', { class: 'field', id: 'fixed-wrap', hidden: !fixed }, h('label', null, 'Revenue (same currency)'),
        numberInput({ attrs: { name: 'fixedRevenue' } }, d.fixedRevenue))),
    h('div', { class: 'hint' }, 'Our revenue is a part of the amount, not on top of it. It updates as you type; the rest goes to the master.'),
    rateField(vessel, d), previewBox(),
  ];
}

function formFields(type, vessel, d) {
  // Every service has a cost and a revenue (Crew Change and Others / Remarks too).
  const money = () => (!mayMoney() ? [] : [
    moneyField('Revenue', 'revenue', 'revenueCurrency', d, 'USD'), moneyField('Cost', 'cost', 'costCurrency', d, 'EGP'),
    rateField(vessel, d), previewBox(),
  ]);
  if (type === 'Others / Remarks') {
    return [field('Notes', h('textarea', { attrs: { name: 'note', maxlength: 1000 }, value: d.note })), money()];
  }
  if (type === 'Crew Change') return [h('div', { id: 'crew-editor' }), money()];
  if (MULTI.includes(type)) {
    return [
      h('div', { id: 'entries' }, (d.entries || []).map((e) => entryRowEl(type, e))),
      h('button', { class: 'btn ghost wide', dataset: { act: 'add-entry' }, style: { margin: '0 0 12px' } }, '+ Add entry'),
      mayMoney() ? [rateField(vessel, d), previewBox()] : null,
    ];
  }
  if (type === 'Cash to Master') return mayMoney() ? cashToMasterFields(vessel, d) : [];
  const extra = SINGLE_EXTRA[type];
  const extraField = extra
    ? field(extra.label, extra.type === 'number'
      ? numberInput({ attrs: { name: extra.name } }, d[extra.name])
      : h('input', { attrs: { type: extra.type, name: extra.name }, value: d[extra.name] }))
    : null;
  return [extraField, money()];
}

export async function openServiceForm(type, service, { from = '' } = {}) {
  const vessel = getVessel(state.ctx.vesselId);
  const data = service ? service.data || {} : {};
  try {
    await loadCustomers();
  } catch {
    // no customers: the billing party list is empty and nothing is filled in
  }
  state.ctx = {
    view: 'service-form', vesselId: vessel.id, type, serviceId: service ? service.id : null, version: service?.version,
    isNew: !service, touched: new Set(), lastRate: null, from, // from 'services': saving goes back to that page
  };
  if (type === 'Crew Change') {
    state.crew = JSON.parse(JSON.stringify({ onSigners: data.onSigners || [], offSigners: data.offSigners || [] }));
  }
  openModal(
    headEl(type, vessel.name),
    h('div', { class: 'm-body', id: 'svc-form' },
      service?.closed ? h('div', { class: 'svc-reason' }, closedNoteEl()) : null,
      agentStatusFields(vessel, service),
      billingFields(vessel, service),
      formFields(type, vessel, data)),
    footer(h('button', { class: 'btn primary', dataset: { act: 'save-service' } }, 'Save')),
  );
  if (type === 'Crew Change') renderCrewEditor();
  renumberEntries();
  updatePreview();
  applyRate({ fill: state.ctx.isNew }); // a new service gets the agreed rate; opening a saved one only shows it
}

/** The service data typed into the form, ready to send to the server (no money keys without money.edit). */
export function readServiceForm() {
  const data = typedServiceData();
  return mayMoney() ? data : stripMoney(state.ctx.type, data);
}

function typedServiceData() {
  const root = $('#svc-form');
  const { type } = state.ctx;
  // the agent and the status are sent beside the data, not in it
  const { agent: _agent, status: _status, cancel_reason: _reason, billing: _billing, billing_party: _party, ...values } =
    formValues(root);
  const money = {
    cost: values.cost, costCurrency: values.costCurrency, revenue: values.revenue,
    revenueCurrency: values.revenueCurrency, exchangeRate: values.exchangeRate,
  };
  if (type === 'Others / Remarks') return { note: values.note, ...money };
  if (type === 'Crew Change') {
    const withoutUiState = ({ _open, ...member }) => member;
    return {
      onSigners: state.crew.onSigners.map(withoutUiState), offSigners: state.crew.offSigners.map(withoutUiState), ...money,
    };
  }
  if (MULTI.includes(type)) {
    const entries = $$('.entry', root).map((row) => {
      const entry = row.dataset.uid ? { uid: row.dataset.uid } : {}; // keeps its money on the server
      $$('[data-f]', row).forEach((field) => { entry[field.dataset.f] = field.value; });
      return entry;
    });
    return { entries, exchangeRate: values.exchangeRate };
  }
  return values;
}

export function updatePreview() {
  const box = $('#preview');
  if (!box || state.ctx.view !== 'service-form') return;
  const calc = calcLocal(state.ctx.type, readServiceForm(), getVessel(state.ctx.vesselId).rate);
  const profitClass = calc.profit_egp >= 0 ? 'good' : 'bad';
  const profit = ['Profit ', h('b', { class: profitClass }, `LE ${sign(calc.profit_egp)}`)];
  setChildren(box,
    state.ctx.type === 'Cash to Master'
      ? ['Our revenue ', h('b', { class: 'good' }, `LE ${fmt(calc.revenue_egp)}`), ' · Paid to master ', h('b', null, `LE ${fmt(calc.to_master_egp)}`), ' · ', profit]
      : ['Cost ', h('b', null, `LE ${fmt(calc.cost_egp)}`), ' · Revenue ', h('b', null, `LE ${fmt(calc.revenue_egp)}`), ' · ', profit],
    calc.rate_missing ? h('div', { class: 'warn-text' }, 'No exchange rate for this month — USD is counted 1:1.') : null);
}

/* ---------- live updates (bound once on the modal) ---------- */

export function onModalInput(event) {
  const field = event.target;
  if (!field.matches('[data-crew]')) {
    if (state.ctx.view !== 'service-form') return;
    noteTouched(field);
    if (field.name === 'quantity') applyRate();
    updatePreview();
    return;
  }
  const card = field.closest('.crew-card');
  const member = state.crew[card.dataset.group][Number(card.dataset.i)];
  const kind = field.dataset.crew;
  if (kind === 'needsHotel') {
    member.needsHotel = field.checked;
    return;
  }
  if (kind.startsWith('visa.')) {
    member.brokenVisa = { ...member.brokenVisa, [kind.slice(5)]: field.value };
    updatePreview();
    return;
  }
  member[kind] = field.value;

  if (kind === 'name') {
    $('.crew-name', card).textContent = field.value || `Crew member ${Number(card.dataset.i) + 1}`;
  } else if (kind === 'flightData') {
    member.flightStructured = { segments: parseFlightText(field.value) };
    $('[data-parsed=flight]', card).textContent = flightNote(member);
  } else if (kind === 'personalData') {
    const parsed = parsePersonal(field.value);
    member.personalStructured = { ...member.personalStructured, ...parsed };
    if (parsed.name && !member.name) {
      member.name = parsed.name;
      $('[data-crew=name]', card).value = parsed.name;
      $('.crew-name', card).textContent = parsed.name;
    }
    $('[data-parsed=personal]', card).textContent = personalNote(member);
  }
}

export function onModalChange(event) {
  const target = event.target;
  if (target.name === 'status') {
    const cancelled = target.value === 'cancelled';
    $('#svc-reason').hidden = !cancelled;
    if (cancelled) $$(MONEY_INPUTS, $('#svc-form')).forEach((input) => { input.value = '0'; });
    setChildren($('#svc-bookings'));
    $('#svc-bookings').hidden = true;
    if (cancelled && state.ctx.type === 'Crew Change' && state.ctx.serviceId) showCrewBookings();
  }
  if (state.ctx.view === 'service-form') noteTouched(target);
  if (target.name === 'billing_party') applyRate();
  if (target.name === 'shareMode') {
    const fixed = target.value === 'fixed';
    $('#pct-wrap').hidden = fixed;
    $('#fixed-wrap').hidden = !fixed;
  }
  if (state.ctx.view === 'service-form') updatePreview();
}
