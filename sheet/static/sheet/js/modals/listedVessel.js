// One entry of the vessel list: name, operator and LOA. Read-only without "Edit terminals and vessel list"; Delete for Admins.
import { api, mutate } from '../api.js';
import { deleteBtn, headEl } from '../components.js';
import { ME, can } from '../config.js';
import { h, optionEls } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { optionValues, state } from '../state.js';
import { $ } from '../util.js';

const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);

/** Every port's Shipping line values (the list is shared by all ports), keeping the saved one. */
function operatorChoices(saved) {
  const values = [...new Set([...optionValues('line'), ...(saved ? [saved] : [])])].sort((a, b) => a.localeCompare(b));
  return [['', saved === '' ? '—' : 'Choose…'], ...values.map((v) => [v, v])];
}

export function openListedDialog(vessel, onDone) {
  const editable = can('operation.master');
  state.ctx = { view: 'listed', listedId: vessel?.id ?? null, onDone };
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(vessel ? vessel.name : 'Add vessel'),
    h('div', { class: 'm-body', id: 'listed-form' },
      h('div', { class: 'row three' },
        field('Vessel name', h('input', { attrs: { name: 'name', maxlength: 100, autocomplete: 'off' }, value: vessel?.name ?? '', disabled: !editable })),
        field('Operator', h('select', { class: 'select', attrs: { name: 'line' }, disabled: !editable },
          optionEls(operatorChoices(vessel?.line ?? ''), vessel?.line ?? ''))),
        field('LOA (m)', h('input', { attrs: { name: 'loa', type: 'number', min: 0, max: 500, step: '0.1' }, value: vessel?.loa ?? '', disabled: !editable })))),
    h('div', { class: 'm-foot' },
      vessel && ME.isAdmin ? deleteBtn('vl-del') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', editable ? 'Cancel' : 'Close'),
        editable ? [' ', btn('primary', 'vl-save', 'Save')] : null)),
  );
}

let saving = false;

export async function saveListedDialog() {
  if (saving || state.ctx.view !== 'listed') return;
  const form = $('#listed-form');
  const payload = { name: form.querySelector('[name="name"]').value, loa: form.querySelector('[name="loa"]').value,
    line: form.querySelector('[name="line"]').value };
  const { listedId, onDone } = state.ctx;
  saving = true;
  try {
    await mutate(() => (listedId ? api(`/api/operation/vessels/${listedId}/`, 'PUT', payload)
      : api('/api/operation/vessels/', 'POST', payload)));
  } catch {
    return; // mutate showed the server's message
  } finally {
    saving = false;
  }
  closeModal();
  await onDone?.();
}

export async function deleteListedDialog() {
  const { listedId, onDone } = state.ctx;
  if (state.ctx.view !== 'listed' || !listedId) return;
  const name = $('#listed-form [name="name"]').value;
  if (!confirm(`Delete ${name} from the vessel list? Visits keep their name and LOA.`)) return;
  try {
    await mutate(() => api(`/api/operation/vessels/${listedId}/`, 'DELETE'));
  } catch {
    return;
  }
  closeModal();
  await onDone?.();
}
