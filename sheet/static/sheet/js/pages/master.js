// Master data page: the OPR, POC, Agent, Hotel, Airport and Port lists.
import { ME, OPTION_KINDS, PORTS, PORT_LABEL } from '../config.js';
import { h, optionEls, setChildren } from '../dom.js';
import { state } from '../state.js';
import { $ } from '../util.js';

// A port choice for admins: '' = All ports, else one port.
const portSelect = (props, current) =>
  h('select', { class: 'select port-pick', ...props }, optionEls([['', 'All ports'], ...PORTS.map((p) => [p.key, p.label])], current));

/** The port an admin last chose when adding to each list (kept while the page is open). */
export const newValuePort = {};

// Hotel / Airport / Port values are used by hotel stays and transfers, not by vessels.
const BOOKING_KINDS = ['hotel', 'airport', 'port'];
export const usageUnit = (kind, n) => `${kind === 'closure' ? 'closure' : BOOKING_KINDS.includes(kind) ? 'booking' : 'vessel'}${n === 1 ? '' : 's'}`;

function optionRow(option) {
  const canRemove = ME.canEdit && option.editable;
  let scope = null;
  if (ME.isAdmin) {
    scope = portSelect({ dataset: { optionPort: '', id: option.id }, attrs: { 'aria-label': `Port of ${option.value}` } }, option.port);
  } else if (option.port) {
    scope = h('span', { class: 'scope' }, PORT_LABEL[option.port] || option.port);
  }
  // The port, usage and Remove stay together: a long value takes its own line above them.
  return h('div', { class: 'opt-row' },
    h('span', { class: 'val' }, option.value), ' ',
    h('span', { class: 'opt-ctl' }, scope, ' ',
      h('small', null, `${option.used} ${usageUnit(option.kind, option.used)}`), ' ',
      canRemove
        ? h('button', {
          class: 'btn danger small',
          dataset: { act: 'del-option', id: option.id, used: option.used, kind: option.kind, value: option.value },
        }, 'Remove')
        : null));
}

function listPanel({ key, label }) {
  const rows = state.options.filter((o) => o.kind === key).map(optionRow);
  const adder = ME.canEdit
    ? h('div', { class: 'add-row' },
      h('input', { class: 'input', dataset: { new: key }, attrs: { maxlength: 100, placeholder: `New ${label}…` } }), ' ',
      ME.isAdmin
        ? portSelect({ dataset: { newPort: key }, attrs: { 'aria-label': `Port for a new ${label}` } }, newValuePort[key] || '')
        : null, ' ',
      h('button', { class: 'btn primary', dataset: { act: 'add-option', kind: key } }, 'Add'))
    : null;
  return h('section', { class: 'panel' }, h('h3', null, label), rows.length ? rows : h('div', { class: 'none' }, 'None yet.'), adder);
}

export function renderMasterPage() {
  const note = ME.port
    ? `Values you add are for ${PORT_LABEL[ME.port]} only; shared values are managed by an admin.`
    : 'Choose a port for each value, or All ports to offer it everywhere.';
  setChildren($('#master-grid'), OPTION_KINDS.map(listPanel),
    h('p', { class: 'help', style: { gridColumn: '1/-1', margin: '0' } }, note));
}
