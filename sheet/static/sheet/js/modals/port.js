// The Ports page dialog: a new port (its name) or an existing one (rename, Turn off / Turn on). The key is made
// by the server from the first name and never changes.
import { api, mutate } from '../api.js';
import { headEl } from '../components.js';
import { h } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { state } from '../state.js';
import { $ } from '../util.js';

export function openPortDialog(port, onDone) {
  state.ctx = { view: 'port', portKey: port?.key ?? null, active: port?.active ?? true, onDone };
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(port ? port.name : 'Add port'),
    h('div', { class: 'm-body', id: 'port-form' },
      h('div', { class: 'field' }, h('label', null, 'Name'),
        h('input', { attrs: { name: 'name', maxlength: 40, autocomplete: 'off' }, value: port?.name ?? '' }))),
    h('div', { class: 'm-foot' },
      port ? btn('ghost', 'port-toggle', port.active ? 'Turn off' : 'Turn on') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', 'Cancel'), ' ', btn('primary', 'port-save', 'Save'))),
  );
}

let saving = false;

async function send(payload) {
  const { portKey, onDone } = state.ctx;
  if (saving) return;
  saving = true;
  try {
    await mutate(() => (portKey ? api(`/api/ports/${encodeURIComponent(portKey)}/`, 'PUT', payload)
      : api('/api/ports/', 'POST', payload)));
  } catch {
    return; // mutate showed the server's message
  } finally {
    saving = false;
  }
  closeModal();
  await onDone?.();
}

export function savePortDialog() {
  if (state.ctx.view !== 'port') return undefined;
  return send({ name: $('#port-form [name="name"]').value });
}

export function togglePort() {
  if (state.ctx.view !== 'port' || !state.ctx.portKey) return undefined;
  return send({ active: !state.ctx.active });
}
