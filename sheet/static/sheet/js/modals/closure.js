// The add / edit dialog for a port closure. The server checks everything again (port, times, reason from Master data).
import { api, mutate } from '../api.js';
import { showConflict } from '../conflict.js';
import { headEl, optionChoicesEl, portOptionEls } from '../components.js';
import { ME } from '../config.js';
import { h, setChildren } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { closureById, closuresPage, deleteClosure } from '../pages/closures.js';
import { state } from '../state.js';
import { $, formValues, nowLocalInput } from '../util.js';

const btn = (cls, act, label, extra = {}) => h('button', { class: `btn ${cls}`, dataset: { act, ...extra } }, label);

const timeField = (name, label, value) =>
  h('div', { class: 'time-row' },
    h('div', { class: 'field' }, h('label', null, label), h('input', { attrs: { type: 'datetime-local', name }, value })),
    h('button', { class: 'btn ghost small', attrs: { type: 'button' }, dataset: { act: 'closure-now', target: name } }, 'Now'));

export function openClosureDialog(id = null) {
  const closure = id ? closureById(id) : null;
  if (id && !closure) return;
  state.ctx = { view: 'closure', closureId: id, version: closure?.version };
  const port = closure ? closure.port : ME.port || 'alexandria';
  openModal(
    headEl(closure ? 'Edit port closure' : 'Add port closure'),
    h('div', { class: 'm-body', id: 'closure-form' },
      ME.isAdmin
        ? h('div', { class: 'field' }, h('label', null, 'Port'), h('select', { attrs: { name: 'port' } }, portOptionEls({ selected: port })))
        : null,
      h('div', { class: 'row two' },
        timeField('start_at', 'Closed from', closure?.start_at), timeField('end_at', 'Reopened', closure?.end_at)),
      h('div', { class: 'field' }, h('label', null, 'Reason'),
        h('select', { attrs: { name: 'reason' } }, optionChoicesEl('closure', closure?.reason || '', port))),
      h('div', { class: 'field' }, h('label', null, 'Notes'),
        h('input', { attrs: { name: 'notes', maxlength: 500 }, value: closure?.notes }))),
    h('div', { class: 'm-foot' },
      closure ? btn('danger', 'closure-del', 'Delete', { id: closure.id }) : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', 'Cancel'), ' ', btn('primary', 'closure-save', 'Save'))),
  );
}

/** Admin changed the port: offer that port's closure reasons (keeping the chosen one). */
export function onClosureFormChange(event) {
  if (state.ctx.view !== 'closure' || event.target.name !== 'port') return;
  const select = $('#closure-form [name="reason"]');
  setChildren(select, optionChoicesEl('closure', select.value, event.target.value));
}

export function closureNow(button) {
  $(`#closure-form [name="${button.dataset.target}"]`).value = nowLocalInput();
}

let saving = false; // one save at a time: a double click must not add the closure twice

/** Save the dialog; an edit sends the version it opened with (`version`: the one from a conflict). */
export async function saveClosure(version) {
  if (saving || state.ctx.view !== 'closure') return;
  const { closureId } = state.ctx;
  const payload = formValues($('#closure-form'));
  if (closureId) payload.version = version ?? state.ctx.version;
  saving = true;
  try {
    await mutate(() => (closureId ? api(`/api/closures/${closureId}/`, 'PUT', payload) : api('/api/closures/', 'POST', payload)),
      (conflict) => showConflict(conflict, 'port closure', {
        reload: async () => { await closuresPage.load(); openClosureDialog(closureId); },
        force: (current) => saveClosure(current),
      }));
  } catch {
    return; // mutate already showed the error in the dialog
  } finally {
    saving = false;
  }
  closeModal();
  await closuresPage.load();
}

/** The Delete button of a row or of the dialog. */
export async function removeClosure(button) {
  const fromDialog = state.ctx.view === 'closure';
  try {
    if ((await deleteClosure(Number(button.dataset.id))) && fromDialog) closeModal();
  } catch {
    // mutate already showed the error
  }
}
