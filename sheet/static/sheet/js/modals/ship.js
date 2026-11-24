// A ship's fields (name, IMO or No IMO, OPR, customer, active): in the Ships page's dialog, and as the small "New
// ship" panel under a vessel name box (the app has one dialog, which may already show the vessel form).
import { api, mutate } from '../api.js';
import { headEl, optionChoicesEl } from '../components.js';
import { ME } from '../config.js';
import { h } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { customerOptionEls, loadCustomers } from '../parties.js';
import { state } from '../state.js';
import { $ } from '../util.js';

const field = (label, control) => h('div', { class: 'field' }, h('label', null, label), control);

/** The fields, inside `root` (an element with an id); `port` narrows the OPR list (admins: null = every port). */
function shipFieldsEl(ship, { name = '', port = null, withActive = false } = {}) {
  const noImo = Boolean(ship && !ship.imo);
  const imo = h('input', { attrs: { name: 'imo', maxlength: 7, inputmode: 'numeric' }, value: ship?.imo, disabled: noImo });
  const tick = h('input', { attrs: { type: 'checkbox', name: 'no_imo' }, checked: noImo });
  tick.addEventListener('change', () => {
    imo.disabled = tick.checked;
    if (tick.checked) imo.value = '';
  });
  return [
    h('div', { class: 'row two' },
      field('Ship name', h('input', { attrs: { name: 'name', maxlength: 120 }, value: ship?.name ?? name })),
      h('div', { class: 'field' }, h('label', null, 'IMO'), imo,
        h('label', { class: 'tick' }, tick, ' No IMO'))),
    h('div', { class: 'row two' },
      field('OPR', h('select', { attrs: { name: 'opr' } }, optionChoicesEl('opr', ship?.opr || '', port))),
      field('Customer', h('select', { attrs: { name: 'customer' } }, customerOptionEls(ship?.customer?.id ?? null)))),
    withActive
      ? h('label', { class: 'tick' }, h('input', { attrs: { type: 'checkbox', name: 'active' }, checked: ship ? ship.active : true }), ' Active')
      : null,
  ];
}

/** What the fields inside `root` say, ready to send. */
function readShip(root) {
  const value = (name) => $(`[name="${name}"]`, root);
  const payload = {
    name: value('name').value.trim().toUpperCase(),
    imo: value('imo').value.trim(),
    no_imo: value('no_imo').checked,
    opr: value('opr').value,
    customer: value('customer').value ? Number(value('customer').value) : null,
  };
  if (value('active')) payload.active = value('active').checked;
  return payload;
}

/**
 * The inline "New ship" panel: newShipPanel({ name, port, onSaved(ship), onCancel() }) -> element. Its buttons work
 * on their own (no data-act), so it can sit inside the vessel form or under the quick-add bar.
 */
export async function newShipPanel({ name, port, onSaved, onCancel }) {
  await loadCustomers();
  const root = h('div', { class: 'new-ship panel' },
    h('div', { class: 'section-title' }, h('span', null, 'New ship')),
    shipFieldsEl(null, { name, port }));
  let saving = false;
  const save = h('button', { class: 'btn primary small', attrs: { type: 'button' } }, 'Save ship');
  const cancel = h('button', { class: 'btn ghost small', attrs: { type: 'button' } }, 'Cancel');
  save.addEventListener('click', async () => {
    if (saving) return;
    saving = true;
    try {
      const ship = await mutate(() => api('/api/ships/', 'POST', readShip(root)));
      onSaved(ship);
    } catch {
      // mutate showed the error
    } finally {
      saving = false;
    }
  });
  cancel.addEventListener('click', () => onCancel());
  root.append(h('div', { class: 'right' }, cancel, ' ', save));
  return root;
}

/** The Ships page dialog (edit roles; admins also delete). */
export async function openShipDialog(ship, onDone) {
  await loadCustomers();
  state.ctx = { view: 'ship', shipId: ship?.id ?? null, onDone };
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(ship ? 'Edit ship' : 'Add ship'),
    h('div', { class: 'm-body', id: 'ship-form' }, shipFieldsEl(ship, { port: ME.multiPort ? null : ME.homePort, withActive: true }),
      ship ? h('div', { class: 'none' }, `${ship.calls} port call${ship.calls === 1 ? '' : 's'}`) : null),
    h('div', { class: 'm-foot' },
      ship && ME.isAdmin ? btn('danger', 'ship-del', 'Delete') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', 'Cancel'), ' ', btn('primary', 'ship-save', 'Save'))),
  );
}

let saving = false;

export async function saveShipDialog() {
  if (saving || state.ctx.view !== 'ship') return;
  const { shipId, onDone } = state.ctx;
  saving = true;
  try {
    await mutate(() => (shipId ? api(`/api/ships/${shipId}/`, 'PUT', readShip($('#ship-form')))
      : api('/api/ships/', 'POST', readShip($('#ship-form')))));
  } catch {
    return;
  } finally {
    saving = false;
  }
  closeModal();
  await onDone?.();
}

export async function deleteShipDialog() {
  if (state.ctx.view !== 'ship' || !confirm('Delete this ship? This cannot be undone.')) return;
  const { shipId, onDone } = state.ctx;
  try {
    await mutate(() => api(`/api/ships/${shipId}/`, 'DELETE'));
  } catch {
    return;
  }
  closeModal();
  await onDone?.();
}
