// Vessel details (port call + services) and the add / edit vessel form.
import {
  headEl, metaBadgesEl, moneyPillsEl, optionChoicesEl, pillEl, portCallBlockEl, portOptionEls, profitClass, statusChipEl,
} from '../components.js';
import { ME, MULTI, SINGLE_EXTRA, SUMMARY_FIELDS, TIME_FIELDS } from '../config.js';
import { h, setChildren } from '../dom.js';
import { openModal } from '../modal.js';
import { ensureVessel } from '../data.js';
import { state } from '../state.js';
import { $, $$, fmt, formValues, sign, today } from '../util.js';

const lines = (parts) => parts.flatMap((part, i) => [i ? h('br') : null, part]);
const txt = (x) => (x === null || x === undefined ? '' : String(x));
const btn = (cls, act, label, extra = {}) => h('button', { class: `btn ${cls}`, dataset: { act, ...extra } }, label);

function serviceSummary(service) {
  const d = service.data || {};
  switch (service.type) {
    case 'Others / Remarks':
      return d.note || '—';
    case 'Crew Change': {
      const names = (group) => (d[group] || []).map((m) => m.name || 'Unnamed').join(', ') || '—';
      return [
        h('b', null, `On-signers (${(d.onSigners || []).length}):`), ` ${names('onSigners')}`, h('br'),
        h('b', null, `Off-signers (${(d.offSigners || []).length}):`), ` ${names('offSigners')}`,
      ];
    }
    case 'Cash to Master': {
      const share = d.shareMode === 'fixed' ? `fixed ${txt(d.amountCurrency)} ${fmt(d.fixedRevenue)}` : `${txt(d.percentage ?? 0)}%`;
      return `${txt(d.amountCurrency)} ${fmt(d.amount)} · our share ${share}`;
    }
    default: {
      if (MULTI.includes(service.type)) {
        const entries = d.entries || [];
        return entries.length
          ? lines(entries.map((e, i) => `#${i + 1} ${e.awb || 'no AWB'}${e.weight ? ` · ${txt(e.weight)} kg` : ''}`))
          : 'No entries yet';
      }
      const extra = SINGLE_EXTRA[service.type];
      return extra && d[extra.name] ? `${extra.label}: ${d[extra.name]}` : '';
    }
  }
}

function serviceCard(service) {
  const actions = ME.canEdit
    ? [btn('ghost small', 'edit-service', '✏ Edit', { id: service.id }), ' ', btn('danger small', 'del-service', '✕', { id: service.id })]
    : null;
  return h('div', { class: 'svc-card' },
    h('div', { class: 'svc-top' }, h('strong', null, service.type), h('div', { class: 'svc-actions' }, actions)),
    h('div', { class: 'svc-detail' }, serviceSummary(service)),
    moneyPillsEl(service.type, service.calc));
}

export async function openVessel(id) {
  const vessel = await ensureVessel(id);
  if (!vessel) return;
  state.ctx = { view: 'vessel', vesselId: id };
  const rateMissing = vessel.services.some((s) => s.calc.rate_missing);
  const month = `${vessel.date.slice(5, 7)}.${vessel.date.slice(0, 4)}`;
  const totals = vessel.services.length
    ? h('div', { class: 'totals' },
      pillEl('Total cost', `LE ${fmt(vessel.total_cost_egp)}`), ' ',
      pillEl('Total profit', `LE ${sign(vessel.total_profit_egp)}`, profitClass(vessel.total_profit_egp)))
    : null;
  openModal(
    headEl(vessel.name, [...metaBadgesEl(vessel), statusChipEl(vessel.status)]),
    h('div', { class: 'm-body' },
      rateMissing
        ? h('div', { class: 'warn' }, `No exchange rate set for ${month}. USD amounts are counted 1:1 until you add one. `,
          h('a', { href: '#rates', dataset: { act: 'goto', page: 'rates' } }, 'Set rates'))
        : null,
      h('div', { class: 'section-title' }, h('span', null, '🕒 Port call'),
        ME.canEdit ? btn('ghost small', 'edit-vessel', '✏ Edit times & agent') : null),
      portCallBlockEl(vessel),
      h('div', { class: 'section-title', style: { marginTop: '20px' } }, h('span', null, 'Services'),
        h('span', null, btn('ghost small btn-green', 'summary', '📋 Summary of services', { id: vessel.id }), ' ',
          ME.canEdit ? btn('primary small', 'add-service', '+ Add service') : null)),
      totals,
      vessel.services.length ? vessel.services.map(serviceCard) : h('div', { class: 'hint' }, 'No services recorded for this vessel yet.')),
    h('div', { class: 'm-foot' },
      ME.canEdit ? btn('danger', 'del-vessel', 'Delete vessel') : h('span'),
      h('div', { class: 'right' },
        ME.canEdit ? btn('ghost', 'edit-vessel', 'Edit vessel info') : null, ' ',
        btn('ghost', 'close', 'Close'))),
  );
}

const selectField = (kind, label, current, port) =>
  h('div', { class: 'field' }, h('label', null, label), h('select', { attrs: { name: kind } }, optionChoicesEl(kind, current, port)));

/** Admin changed the vessel's port in the form: offer that port's OPR / POC / Agent values (keeping the chosen ones). */
export function onVesselFormChange(event) {
  if (state.ctx.view !== 'vessel-form' || event.target.name !== 'port') return;
  for (const kind of ['opr', 'poc', 'agent']) {
    const select = $(`#vessel-form [name="${kind}"]`);
    if (select) setChildren(select, optionChoicesEl(kind, select.value, event.target.value));
  }
}

const timeField = ({ key, label }, vessel) =>
  h('div', { class: 'time-row' },
    h('div', { class: 'field' }, h('label', null, label),
      h('input', { attrs: { type: 'datetime-local', name: key }, value: vessel?.[key] })),
    h('button', { class: 'btn ghost small', attrs: { type: 'button' }, dataset: { act: 'time-now', target: key } }, 'Now'));

export function openVesselForm(vessel) {
  state.ctx = { view: 'vessel-form', vesselId: vessel ? vessel.id : null };
  const selectedPort = vessel ? vessel.port : ME.port || (state.filter.port !== 'ALL' ? state.filter.port : 'alexandria');
  const summary = (vessel && vessel.summary) || {};
  const portField = ME.isAdmin
    ? h('div', { class: 'field' }, h('label', null, 'Port'), h('select', { attrs: { name: 'port' } }, portOptionEls({ selected: selectedPort })))
    : null;

  openModal(
    headEl(vessel ? 'Edit vessel' : 'Add vessel'),
    h('div', { class: 'm-body', id: 'vessel-form' },
      h('div', { class: 'field' }, h('label', null, 'Vessel name'),
        h('input', { attrs: { name: 'name', maxlength: 120, autofocus: true }, value: vessel?.name })),
      h('div', { class: 'row three' },
        selectField('opr', 'OPR', vessel?.opr, selectedPort), selectField('poc', 'POC', vessel?.poc, selectedPort),
        selectField('agent', 'Agent', vessel?.agent, selectedPort)),
      h('div', { class: 'hint' }, 'Missing an OPR, POC or agent? Add it under ',
        h('a', { href: '#master', dataset: { act: 'goto', page: 'master' }, style: { color: 'var(--teal)' } }, 'Master data'), '.'),
      h('div', { class: 'row two' },
        h('div', { class: 'field' }, h('label', null, 'Date'), h('input', { attrs: { type: 'date', name: 'date' }, value: vessel ? vessel.date : today() })),
        portField),
      h('div', { class: 'section-title', style: { marginTop: '6px' } },
        h('span', null, '🕒 Port call times ',
          h('small', { class: 'none', style: { textTransform: 'none', letterSpacing: '0' } }, '(Cairo time, all optional)'))),
      h('div', { class: 'row two' }, TIME_FIELDS.map((f) => timeField(f, vessel))),
      h('details', { class: 'fold', open: Object.keys(summary).length > 0 },
        h('summary', null, '💰 Financial summary (optional)'),
        h('div', { class: 'row two' }, SUMMARY_FIELDS.map((key) => h('div', { class: 'field' }, h('label', null, key),
          h('input', { dataset: { sum: key }, attrs: { maxlength: 80 }, value: summary[key] })))),
        h('div', { class: 'hint' }, 'Total Cost LE is worked out automatically from the services.'))),
    h('div', { class: 'm-foot' },
      btn('ghost', vessel ? 'back' : 'close', 'Cancel'),
      h('div', { class: 'right' },
        vessel ? null : btn('ghost', 'save-vessel-more', 'Save & add another'), ' ',
        btn('primary', 'save-vessel', 'Save'))),
  );
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
