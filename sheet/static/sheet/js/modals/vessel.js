// Vessel details (port call + services) and the add / edit vessel form.
import { head, metaBadges, moneyPills, optionChoices, pill, portCallBlock, profitClass, statusChip } from '../components.js';
import { ME, MULTI, PORTS, SINGLE_EXTRA, SUMMARY_FIELDS, TIME_FIELDS } from '../config.js';
import { openModal } from '../modal.js';
import { ensureVessel } from '../data.js';
import { state } from '../state.js';
import { $, $$, esc, fmt, formValues, sign, today, val } from '../util.js';

function serviceSummary(service) {
  const d = service.data || {};
  switch (service.type) {
    case 'Others / Remarks':
      return esc(d.note || '—');
    case 'Crew Change': {
      const names = (group) => (d[group] || []).map((m) => esc(m.name || 'Unnamed')).join(', ') || '—';
      return `<b>On-signers (${(d.onSigners || []).length}):</b> ${names('onSigners')}<br>
              <b>Off-signers (${(d.offSigners || []).length}):</b> ${names('offSigners')}`;
    }
    case 'Cash to Master': {
      const share = d.shareMode === 'fixed' ? `fixed ${val(d.amountCurrency)} ${fmt(d.fixedRevenue)}` : `${val(d.percentage ?? 0)}%`;
      return `${val(d.amountCurrency)} ${fmt(d.amount)} · our share ${share}`;
    }
    default:
      if (MULTI.includes(service.type)) {
        const entries = d.entries || [];
        return entries.length
          ? entries.map((e, i) => `#${i + 1} ${esc(e.awb || 'no AWB')}${e.weight ? ` · ${val(e.weight)} kg` : ''}`).join('<br>')
          : 'No entries yet';
      }
      const extra = SINGLE_EXTRA[service.type];
      return extra && d[extra.name] ? `${extra.label}: ${esc(d[extra.name])}` : '';
  }
}

function serviceCard(service) {
  const actions = ME.canEdit
    ? `<button class="btn ghost small" data-act="edit-service" data-id="${service.id}">✏ Edit</button>
       <button class="btn danger small" data-act="del-service" data-id="${service.id}">✕</button>`
    : '';
  return `<div class="svc-card">
    <div class="svc-top"><strong>${esc(service.type)}</strong><div class="svc-actions">${actions}</div></div>
    <div class="svc-detail">${serviceSummary(service)}</div>
    ${moneyPills(service.type, service.calc)}</div>`;
}

export async function openVessel(id) {
  const vessel = await ensureVessel(id);
  if (!vessel) return;
  state.ctx = { view: 'vessel', vesselId: id };
  const rateMissing = vessel.services.some((s) => s.calc.rate_missing);
  const month = `${vessel.date.slice(5, 7)}.${vessel.date.slice(0, 4)}`;
  const totals = vessel.services.length
    ? `<div class="totals">${pill('Total cost', `LE ${fmt(vessel.total_cost_egp)}`)}
       ${pill('Total profit', `LE ${sign(vessel.total_profit_egp)}`, profitClass(vessel.total_profit_egp))}</div>`
    : '';
  openModal(`${head(vessel.name, metaBadges(vessel) + statusChip(vessel.status))}
    <div class="m-body">
      ${rateMissing ? `<div class="warn">No exchange rate set for ${month}. USD amounts are counted 1:1 until you add one. <a href="#rates" data-act="goto" data-page="rates">Set rates</a></div>` : ''}
      <div class="section-title"><span>🕒 Port call</span>${ME.canEdit ? '<button class="btn ghost small" data-act="edit-vessel">✏ Edit times &amp; agent</button>' : ''}</div>
      ${portCallBlock(vessel)}
      <div class="section-title" style="margin-top:20px"><span>Services</span>
        <span><button class="btn ghost small btn-green" data-act="summary" data-id="${vessel.id}">📋 Summary of services</button>
        ${ME.canEdit ? '<button class="btn primary small" data-act="add-service">+ Add service</button>' : ''}</span></div>
      ${totals}
      ${vessel.services.map(serviceCard).join('') || '<div class="hint">No services recorded for this vessel yet.</div>'}
    </div>
    <div class="m-foot">
      ${ME.canEdit ? '<button class="btn danger" data-act="del-vessel">Delete vessel</button>' : '<span></span>'}
      <div class="right">
        ${ME.canEdit ? '<button class="btn ghost" data-act="edit-vessel">Edit vessel info</button>' : ''}
        <button class="btn ghost" data-act="close">Close</button>
      </div>
    </div>`);
}

const selectField = (kind, label, current, port) =>
  `<div class="field"><label>${label}</label><select name="${kind}">${optionChoices(kind, current, port)}</select></div>`;

/** Admin changed the vessel's port in the form: offer that port's OPR / POC / Agent values (keeping the chosen ones). */
export function onVesselFormChange(event) {
  if (state.ctx.view !== 'vessel-form' || event.target.name !== 'port') return;
  for (const kind of ['opr', 'poc', 'agent']) {
    const select = $(`#vessel-form [name="${kind}"]`);
    if (select) select.innerHTML = optionChoices(kind, select.value, event.target.value);
  }
}

const timeField = ({ key, label }, vessel) => `
  <div class="time-row"><div class="field"><label>${esc(label)}</label>
    <input type="datetime-local" name="${key}" value="${val(vessel?.[key])}"></div>
    <button type="button" class="btn ghost small" data-act="time-now" data-target="${key}">Now</button></div>`;

export function openVesselForm(vessel) {
  state.ctx = { view: 'vessel-form', vesselId: vessel ? vessel.id : null };
  const selectedPort = vessel ? vessel.port : ME.port || (state.filter.port !== 'ALL' ? state.filter.port : 'alexandria');
  const summary = (vessel && vessel.summary) || {};
  const portField = ME.isAdmin
    ? `<div class="field"><label>Port</label><select name="port">${PORTS.map(
        (p) => `<option value="${p.key}" ${selectedPort === p.key ? 'selected' : ''}>${p.label}</option>`).join('')}</select></div>`
    : '';

  openModal(`${head(vessel ? 'Edit vessel' : 'Add vessel')}
    <div class="m-body" id="vessel-form">
      <div class="field"><label>Vessel name</label><input name="name" value="${val(vessel?.name)}" maxlength="120" autofocus></div>
      <div class="row three">
        ${selectField('opr', 'OPR', vessel?.opr, selectedPort)}${selectField('poc', 'POC', vessel?.poc, selectedPort)}${selectField('agent', 'Agent', vessel?.agent, selectedPort)}
      </div>
      <div class="hint">Missing an OPR, POC or agent? Add it under <a href="#master" data-act="goto" data-page="master" style="color:var(--teal)">Master data</a>.</div>
      <div class="row two">
        <div class="field"><label>Date</label><input type="date" name="date" value="${vessel ? vessel.date : today()}"></div>
        ${portField}
      </div>
      <div class="section-title" style="margin-top:6px"><span>🕒 Port call times <small class="none" style="text-transform:none;letter-spacing:0">(Cairo time, all optional)</small></span></div>
      <div class="row two">${TIME_FIELDS.map((f) => timeField(f, vessel)).join('')}</div>
      <details class="fold" ${Object.keys(summary).length ? 'open' : ''}>
        <summary>💰 Financial summary (optional)</summary>
        <div class="row two">${SUMMARY_FIELDS.map((key) => `<div class="field"><label>${esc(key)}</label>
          <input data-sum="${esc(key)}" value="${val(summary[key])}" maxlength="80"></div>`).join('')}</div>
        <div class="hint">Total Cost LE is worked out automatically from the services.</div>
      </details>
    </div>
    <div class="m-foot">
      <button class="btn ghost" data-act="${vessel ? 'back' : 'close'}">Cancel</button>
      <div class="right">
        ${vessel ? '' : '<button class="btn ghost" data-act="save-vessel-more">Save &amp; add another</button>'}
        <button class="btn primary" data-act="save-vessel">Save</button>
      </div>
    </div>`);
}

/** The values typed into the vessel form, ready to send to the server. */
export function vesselPayload() {
  const root = $('#vessel-form');
  const payload = formValues(root);
  payload.summary = {};
  $$('[data-sum]', root).forEach((input) => {
    if (input.value.trim()) payload.summary[input.dataset.sum] = input.value.trim();
  });
  return payload;
}
