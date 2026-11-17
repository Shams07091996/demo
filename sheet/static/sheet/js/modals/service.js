// Adding / editing a service: the type picker, the per-type forms, the live profit preview and the crew editor.
import { calcLocal } from '../calc.js';
import { head } from '../components.js';
import { MULTI, SINGLE_EXTRA, TYPES } from '../config.js';
import { parseFlightText, parsePdfText, parsePersonal } from '../crewParsing.js';
import { openModalHtml } from '../modal.js';
import { extractPdfText } from '../pdfReader.js';
import { getVessel, state } from '../state.js';
import { $, $$, esc, fmt, formValues, sign, val } from '../util.js';

/* ---------- form field builders ---------- */

const currencyOptions = (selected) => ['EGP', 'USD'].map((c) => `<option ${c === selected ? 'selected' : ''}>${c}</option>`).join('');

const moneyField = (label, amountName, currencyName, data, defaultCurrency) => `
  <div class="field"><label>${label}</label><div class="row money">
    <input type="number" step="any" min="0" name="${amountName}" value="${val(data[amountName])}" placeholder="0.00">
    <select name="${currencyName}">${currencyOptions(data[currencyName] || defaultCurrency)}</select></div></div>`;

const rateField = (vessel, data) => `
  <div class="field"><label>Exchange rate override (USD → EGP)</label>
    <input type="number" step="any" min="0" name="exchangeRate" value="${val(data.exchangeRate)}" placeholder="Leave blank to use the monthly rate">
    <div class="hint" style="margin:6px 0 0">Monthly rate for ${vessel.date.slice(5, 7)}.${vessel.date.slice(0, 4)}: <b>${vessel.rate ?? 'not set'}</b></div></div>`;

const previewBox = '<div id="preview" class="preview"></div>';

export function entryRowHtml(type, entry = {}) {
  const isParcel = type === 'Delivery Parcels';
  return `<div class="entry">
    <div class="entry-head"><span class="entry-no"></span><button class="btn danger small" data-act="rm-entry">Remove</button></div>
    <div class="row ${isParcel ? 'two' : ''}">
      <div class="field"><label>AWB No.</label><input data-f="awb" value="${val(entry.awb)}" placeholder="e.g. 123-45678901"></div>
      ${isParcel ? `<div class="field"><label>Weight (kg)</label><input type="number" step="any" min="0" data-f="weight" value="${val(entry.weight)}"></div>` : ''}
    </div>
    <div class="row two">
      <div class="field"><label>Revenue</label><div class="row money">
        <input type="number" step="any" min="0" data-f="revenue" value="${val(entry.revenue)}">
        <select data-f="revenueCurrency">${currencyOptions(entry.revenueCurrency || 'USD')}</select></div></div>
      <div class="field"><label>Cost</label><div class="row money">
        <input type="number" step="any" min="0" data-f="cost" value="${val(entry.cost)}">
        <select data-f="costCurrency">${currencyOptions(entry.costCurrency || 'EGP')}</select></div></div>
    </div></div>`;
}

export const renumberEntries = () =>
  $$('#entries .entry').forEach((row, i) => { $('.entry-no', row).textContent = `Entry ${i + 1}`; });

/* ---------- crew editor ---------- */

export const newCrewMember = () => ({
  name: '', flightData: '', personalData: '', personalStructured: {}, flightStructured: { segments: [] }, _open: true,
});

const flightNote = (m) => {
  const count = ((m.flightStructured || {}).segments || []).length;
  return count ? `✓ ${count} flight${count > 1 ? 's' : ''} recognised` : '';
};

const personalNote = (m) => {
  const p = m.personalStructured || {};
  const parts = [p.rank && `Rank: ${esc(p.rank)}`, p.nationality && `Nationality: ${esc(p.nationality)}`].filter(Boolean);
  return parts.length ? `✓ ${parts.join(' · ')}` : '';
};

function crewGroupHtml(group, label, color) {
  const isOff = group === 'offSigners';
  const cards = state.crew[group].map((m, i) => `
    <div class="crew-card ${m._open ? 'open' : ''}" data-group="${group}" data-i="${i}">
      <div class="crew-head" data-act="toggle-crew"><span class="crew-name">${esc(m.name || `Crew member ${i + 1}`)}</span>
        <button class="btn danger small" data-act="rm-crew">Remove</button></div>
      <div class="crew-body">
        <div class="field"><label>Full name</label><input data-crew="name" value="${val(m.name)}"></div>
        <div class="field"><label>Flight details</label><textarea data-crew="flightData">${val(m.flightData)}</textarea>
          <div class="parsed" data-parsed="flight">${flightNote(m)}</div></div>
        <div class="field"><label>Personal data</label><textarea data-crew="personalData">${val(m.personalData)}</textarea>
          <div class="parsed" data-parsed="personal">${personalNote(m)}</div></div>
      </div></div>`);
  return `<div class="section-title" style="${isOff ? 'margin-top:16px;' : ''}color:${color}">
      <span>${label} (${state.crew[group].length})</span>
      <span>${isOff ? '<button class="btn ghost small" data-act="pdf-pick">📄 Import flight PDFs</button> ' : ''}
        <button class="btn ghost small" data-act="add-crew" data-group="${group}">+ Add</button></span></div>${cards.join('')}`;
}

export function renderCrewEditor() {
  $('#crew-editor').innerHTML =
    crewGroupHtml('onSigners', '↑ On-signers', 'var(--success)') +
    crewGroupHtml('offSigners', '↓ Off-signers', 'var(--gold)') +
    '<input type="file" id="pdf-input" accept="application/pdf" multiple style="display:none">';
}

export async function importPdfs(input) {
  const files = [...input.files];
  if (!files.length) return;
  let added = 0;
  try {
    for (const file of files) {
      for (const member of parsePdfText(await extractPdfText(file))) {
        state.crew.offSigners.push({ ...member, _open: true });
        added += 1;
      }
    }
    renderCrewEditor();
    alert(`✅ ${added} off-signer${added !== 1 ? 's' : ''} added from ${files.length} PDF${files.length !== 1 ? 's' : ''}.`);
  } catch (error) {
    alert(`❌ Failed to read PDF: ${error.message}`);
  }
  input.value = '';
}

/* ---------- screens ---------- */

export function openTypePicker() {
  state.ctx.view = 'type-picker';
  const buttons = TYPES.map((t) => `<button class="type-btn" data-act="pick-type" data-type="${esc(t)}">${esc(t)}</button>`);
  openModalHtml(`${head('Add service', esc(getVessel(state.ctx.vesselId).name))}
    <div class="m-body"><div class="type-grid">${buttons.join('')}</div></div>
    <div class="m-foot"><button class="btn ghost" data-act="back">‹ Back</button><span></span></div>`);
}

function cashToMasterFields(vessel, d) {
  const fixed = d.shareMode === 'fixed';
  return `${moneyField('Amount given to the master', 'amount', 'amountCurrency', d, 'USD')}
    <div class="row two">
      <div class="field"><label>Our share is</label><select name="shareMode">
        <option value="percent" ${fixed ? '' : 'selected'}>a percentage of the amount</option>
        <option value="fixed" ${fixed ? 'selected' : ''}>a fixed figure</option></select></div>
      <div class="field" id="pct-wrap" style="${fixed ? 'display:none' : ''}"><label>Percentage (%)</label>
        <input type="number" step="any" min="0" max="100" name="percentage" value="${val(d.percentage)}"></div>
      <div class="field" id="fixed-wrap" style="${fixed ? '' : 'display:none'}"><label>Revenue (same currency)</label>
        <input type="number" step="any" min="0" name="fixedRevenue" value="${val(d.fixedRevenue)}"></div>
    </div>
    <div class="hint">Our revenue is a part of the amount, not on top of it. It updates as you type; the rest goes to the master.</div>
    ${rateField(vessel, d)}${previewBox}`;
}

function formFields(type, vessel, d) {
  // Every service has a cost and a revenue (Crew Change and Others / Remarks too).
  const money = () => moneyField('Revenue', 'revenue', 'revenueCurrency', d, 'USD') +
    moneyField('Cost', 'cost', 'costCurrency', d, 'EGP') + rateField(vessel, d) + previewBox;
  if (type === 'Others / Remarks') {
    return `<div class="field"><label>Notes</label><textarea name="note" maxlength="1000">${val(d.note)}</textarea></div>${money()}`;
  }
  if (type === 'Crew Change') return `<div id="crew-editor"></div>${money()}`;
  if (MULTI.includes(type)) {
    return `<div id="entries">${(d.entries || []).map((e) => entryRowHtml(type, e)).join('')}</div>
      <button class="btn ghost wide" data-act="add-entry" style="margin:0 0 12px">+ Add entry</button>${rateField(vessel, d)}${previewBox}`;
  }
  if (type === 'Cash to Master') return cashToMasterFields(vessel, d);
  const extra = SINGLE_EXTRA[type];
  const extraField = extra
    ? `<div class="field"><label>${extra.label}</label><input type="${extra.type}" ${extra.type === 'number' ? 'step="any" min="0"' : ''} name="${extra.name}" value="${val(d[extra.name])}"></div>`
    : '';
  return extraField + moneyField('Revenue', 'revenue', 'revenueCurrency', d, 'USD') +
    moneyField('Cost', 'cost', 'costCurrency', d, 'EGP') + rateField(vessel, d) + previewBox;
}

export function openServiceForm(type, service) {
  const vessel = getVessel(state.ctx.vesselId);
  const data = service ? service.data || {} : {};
  state.ctx = { view: 'service-form', vesselId: vessel.id, type, serviceId: service ? service.id : null };
  if (type === 'Crew Change') {
    state.crew = JSON.parse(JSON.stringify({ onSigners: data.onSigners || [], offSigners: data.offSigners || [] }));
  }
  openModalHtml(`${head(type, esc(vessel.name))}
    <div class="m-body" id="svc-form">${formFields(type, vessel, data)}</div>
    <div class="m-foot"><button class="btn ghost" data-act="back">Cancel</button>
      <div class="right"><button class="btn primary" data-act="save-service">Save</button></div></div>`);
  if (type === 'Crew Change') renderCrewEditor();
  renumberEntries();
  updatePreview();
}

/** The service data typed into the form, ready to send to the server. */
export function readServiceForm() {
  const root = $('#svc-form');
  const { type } = state.ctx;
  const values = formValues(root);
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
  const profit = `Profit <b class="${profitClass}">LE ${sign(calc.profit_egp)}</b>`;
  box.innerHTML = (state.ctx.type === 'Cash to Master'
    ? `Our revenue <b class="good">LE ${fmt(calc.revenue_egp)}</b> · Paid to master <b>LE ${fmt(calc.to_master_egp)}</b> · ${profit}`
    : `Cost <b>LE ${fmt(calc.cost_egp)}</b> · Revenue <b>LE ${fmt(calc.revenue_egp)}</b> · ${profit}`) +
    (calc.rate_missing ? '<div class="warn-text">No exchange rate for this month — USD is counted 1:1.</div>' : '');
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
  if (target.id === 'pdf-input') importPdfs(target);
  if (state.ctx.view === 'service-form') updatePreview();
}
