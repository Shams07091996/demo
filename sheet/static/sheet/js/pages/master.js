// Master data page: the OPR, POC, Agent, Hotel, Airport and Port lists.
import { ME, OPTION_KINDS, PORT_LABEL } from '../config.js';
import { state } from '../state.js';
import { $, esc } from '../util.js';

// Hotel / Airport / Port values are used by hotel stays and transfers, not by vessels.
const BOOKING_KINDS = ['hotel', 'airport', 'port'];
export const usageUnit = (kind, n) => `${BOOKING_KINDS.includes(kind) ? 'booking' : 'vessel'}${n === 1 ? '' : 's'}`;

function optionRow(option) {
  const canRemove = ME.canEdit && option.editable;
  const used = `${option.used} ${usageUnit(option.kind, option.used)}`;
  return `<div class="opt-row">
    <span class="val">${esc(option.value)}</span>
    ${option.port ? `<span class="scope">${esc(PORT_LABEL[option.port] || option.port)}</span>` : ''}
    <small>${used}</small>
    ${canRemove ? `<button class="btn danger small" data-act="del-option" data-id="${option.id}" data-used="${option.used}" data-kind="${option.kind}" data-value="${esc(option.value)}">Remove</button>` : ''}
  </div>`;
}

function listPanel({ key, label }) {
  const rows = state.options.filter((o) => o.kind === key).map(optionRow);
  const adder = ME.canEdit
    ? `<div class="add-row"><input class="input" data-new="${key}" maxlength="100" placeholder="New ${esc(label)}…">
       <button class="btn primary" data-act="add-option" data-kind="${key}">Add</button></div>`
    : '';
  return `<section class="panel"><h3>${esc(label)}</h3>${rows.join('') || '<div class="none">None yet.</div>'}${adder}</section>`;
}

export function renderMasterPage() {
  const note = ME.port
    ? `Values you add are for ${esc(PORT_LABEL[ME.port])} only; shared values are managed by an admin.`
    : 'Values you add here are shared with every port.';
  $('#master-grid').innerHTML = OPTION_KINDS.map(listPanel).join('') +
    `<p class="help" style="grid-column:1/-1;margin:0">${note}</p>`;
}
