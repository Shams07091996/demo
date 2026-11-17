// Adding / editing a service: the type picker, the per-type forms, the live profit preview and the crew editor.
import { calcLocal } from '../calc.js';
import { headEl, optionChoicesEl } from '../components.js';
import { MULTI, SINGLE_EXTRA, TYPES } from '../config.js';
import { parseFlightText, parsePersonal } from '../crewParsing.js';
import { h, optionEls, setChildren } from '../dom.js';
import { openModal } from '../modal.js';
import { getVessel, state } from '../state.js';
import { $, $$, fmt, formValues, sign } from '../util.js';

/* ---------- form field builders ---------- */

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

export function entryRowEl(type, entry = {}) {
  const isParcel = type === 'Delivery Parcels';
  return h('div', { class: 'entry' },
    h('div', { class: 'entry-head' }, h('span', { class: 'entry-no' }),
      h('button', { class: 'btn danger small', dataset: { act: 'rm-entry' } }, 'Remove')),
    h('div', { class: `row ${isParcel ? 'two' : ''}`.trim() },
      field('AWB No.', h('input', { dataset: { f: 'awb' }, attrs: { placeholder: 'e.g. 123-45678901' }, value: entry.awb })),
      isParcel ? field('Weight (kg)', numberInput({ dataset: { f: 'weight' } }, entry.weight)) : null),
    h('div', { class: 'row two' },
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

function crewGroupEl(group, label, color) {
  const isOff = group === 'offSigners';
  const cards = state.crew[group].map((m, i) =>
    h('div', { class: `crew-card ${m._open ? 'open' : ''}`.trim(), dataset: { group, i } },
      h('div', { class: 'crew-head', dataset: { act: 'toggle-crew' } },
        h('span', { class: 'crew-name' }, m.name || `Crew member ${i + 1}`),
        h('button', { class: 'btn danger small', dataset: { act: 'rm-crew' } }, 'Remove')),
      h('div', { class: 'crew-body' },
        field('Full name', h('input', { dataset: { crew: 'name' }, value: m.name })),
        field('Flight details', h('textarea', { dataset: { crew: 'flightData' }, value: m.flightData }),
          h('div', { class: 'parsed', dataset: { parsed: 'flight' } }, flightNote(m))),
        field('Personal data', h('textarea', { dataset: { crew: 'personalData' }, value: m.personalData }),
          h('div', { class: 'parsed', dataset: { parsed: 'personal' } }, personalNote(m))))));
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
      h('div', { class: 'field', id: 'pct-wrap', style: { display: fixed ? 'none' : '' } }, h('label', null, 'Percentage (%)'),
        numberInput({ attrs: { name: 'percentage' } }, d.percentage, { max: 100 })),
      h('div', { class: 'field', id: 'fixed-wrap', style: { display: fixed ? '' : 'none' } }, h('label', null, 'Revenue (same currency)'),
        numberInput({ attrs: { name: 'fixedRevenue' } }, d.fixedRevenue))),
    h('div', { class: 'hint' }, 'Our revenue is a part of the amount, not on top of it. It updates as you type; the rest goes to the master.'),
    rateField(vessel, d), previewBox(),
  ];
}

function formFields(type, vessel, d) {
  // Every service has a cost and a revenue (Crew Change and Others / Remarks too).
  const money = () => [
    moneyField('Revenue', 'revenue', 'revenueCurrency', d, 'USD'), moneyField('Cost', 'cost', 'costCurrency', d, 'EGP'),
    rateField(vessel, d), previewBox(),
  ];
  if (type === 'Others / Remarks') {
    return [field('Notes', h('textarea', { attrs: { name: 'note', maxlength: 1000 }, value: d.note })), money()];
  }
  if (type === 'Crew Change') return [h('div', { id: 'crew-editor' }), money()];
  if (MULTI.includes(type)) {
    return [
      h('div', { id: 'entries' }, (d.entries || []).map((e) => entryRowEl(type, e))),
      h('button', { class: 'btn ghost wide', dataset: { act: 'add-entry' }, style: { margin: '0 0 12px' } }, '+ Add entry'),
      rateField(vessel, d), previewBox(),
    ];
  }
  if (type === 'Cash to Master') return cashToMasterFields(vessel, d);
  const extra = SINGLE_EXTRA[type];
  const extraField = extra
    ? field(extra.label, extra.type === 'number'
      ? numberInput({ attrs: { name: extra.name } }, d[extra.name])
      : h('input', { attrs: { type: extra.type, name: extra.name }, value: d[extra.name] }))
    : null;
  return [extraField, money()];
}

export function openServiceForm(type, service) {
  const vessel = getVessel(state.ctx.vesselId);
  const data = service ? service.data || {} : {};
  state.ctx = { view: 'service-form', vesselId: vessel.id, type, serviceId: service ? service.id : null };
  if (type === 'Crew Change') {
    state.crew = JSON.parse(JSON.stringify({ onSigners: data.onSigners || [], offSigners: data.offSigners || [] }));
  }
  openModal(
    headEl(type, vessel.name),
    h('div', { class: 'm-body', id: 'svc-form' },
      field('Agent', h('select', { attrs: { name: 'agent' } }, optionChoicesEl('agent', service?.agent || '', vessel.port))),
      formFields(type, vessel, data)),
    footer(h('button', { class: 'btn primary', dataset: { act: 'save-service' } }, 'Save')),
  );
  if (type === 'Crew Change') renderCrewEditor();
  renumberEntries();
  updatePreview();
}

/** The service data typed into the form, ready to send to the server. */
export function readServiceForm() {
  const root = $('#svc-form');
  const { type } = state.ctx;
  const { agent: _agent, ...values } = formValues(root); // the agent is sent beside the data, not in it
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
      const entry = {};
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
    if (state.ctx.view === 'service-form') updatePreview();
    return;
  }
  const card = field.closest('.crew-card');
  const member = state.crew[card.dataset.group][Number(card.dataset.i)];
  const kind = field.dataset.crew;
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
  if (target.name === 'shareMode') {
    const fixed = target.value === 'fixed';
    $('#pct-wrap').style.display = fixed ? 'none' : '';
    $('#fixed-wrap').style.display = fixed ? '' : 'none';
  }
  if (state.ctx.view === 'service-form') updatePreview();
}
