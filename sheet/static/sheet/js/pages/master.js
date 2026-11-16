// Master data page: the OPR, POC, Agent, Hotel, Airport and Port lists.
import { ME, OPTION_KINDS, PORTS, PORT_LABEL } from '../config.js';
import { state } from '../state.js';
import { $, esc } from '../util.js';

// A port choice for admins: '' = All ports, else one port.
const portSelect = (attrs, current) => `<select class="select port-pick" ${attrs}>${[['', 'All ports'], ...PORTS.map((p) => [p.key, p.label])]
  .map(([key, label]) => `<option value="${key}" ${key === current ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>`;

/** The port an admin last chose when adding to each list (kept while the page is open). */
export const newValuePort = {};

// Hotel / Airport / Port values are used by hotel stays and transfers, not by vessels.
const BOOKING_KINDS = ['hotel', 'airport', 'port'];
export const usageUnit = (kind, n) => `${BOOKING_KINDS.includes(kind) ? 'booking' : 'vessel'}${n === 1 ? '' : 's'}`;

function optionRow(option) {
  const canRemove = ME.canEdit && option.editable;
  const used = `${option.used} ${usageUnit(option.kind, option.used)}`;
  return `<div class="opt-row">
    <span class="val">${esc(option.value)}</span>
    ${ME.isAdmin
    ? portSelect(`data-option-port data-id="${option.id}" aria-label="Port of ${esc(option.value)}"`, option.port)
    : option.port ? `<span class="scope">${esc(PORT_LABEL[option.port] || option.port)}</span>` : ''}
    <small>${used}</small>
    ${canRemove ? `<button class="btn danger small" data-act="del-option" data-id="${option.id}" data-used="${option.used}" data-kind="${option.kind}" data-value="${esc(option.value)}">Remove</button>` : ''}
  </div>`;
}

function listPanel({ key, label }) {
  const rows = state.options.filter((o) => o.kind === key).map(optionRow);
  const adder = ME.canEdit
    ? `<div class="add-row"><input class="input" data-new="${key}" maxlength="100" placeholder="New ${esc(label)}…">
       ${ME.isAdmin ? portSelect(`data-new-port="${key}" aria-label="Port for a new ${esc(label)}"`, newValuePort[key] || '') : ''}
       <button class="btn primary" data-act="add-option" data-kind="${key}">Add</button></div>`
    : '';
  return `<section class="panel"><h3>${esc(label)}</h3>${rows.join('') || '<div class="none">None yet.</div>'}${adder}</section>`;
}

export function renderMasterPage() {
  const note = ME.port
    ? `Values you add are for ${esc(PORT_LABEL[ME.port])} only; shared values are managed by an admin.`
    : 'Choose a port for each value, or All ports to offer it everywhere.';
  $('#master-grid').innerHTML = OPTION_KINDS.map(listPanel).join('') +
    `<p class="help" style="grid-column:1/-1;margin:0">${note}</p>`;
}
