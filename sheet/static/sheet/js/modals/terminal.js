// The Terminals page dialog (Admins): name, code, port, quay length, cranes, its berths (one box each, + / remove)
// and On / Off. The server checks everything again.
import { api, mutate } from '../api.js';
import { formPorts, headEl, portOptionEls } from '../components.js';
import { openPorts } from '../config.js';
import { h, icon } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { state } from '../state.js';
import { $, $$ } from '../util.js';

const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);

const berthRow = (value = '') => h('div', { class: 'berth-row' },
  h('input', { attrs: { maxlength: 10, autocomplete: 'off', 'aria-label': 'Berth' }, dataset: { berth: '1' }, value }),
  h('button', { class: 'btn ghost small', attrs: { type: 'button', title: 'Remove this berth' }, dataset: { act: 'terminal-berth-del' } },
    icon('x')));

export function openTerminalDialog(terminal, onDone) {
  state.ctx = { view: 'terminal', terminalId: terminal?.id ?? null, onDone };
  const open = openPorts();
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(terminal ? terminal.name : 'Add terminal'),
    h('div', { class: 'm-body', id: 'terminal-form' },
      h('div', { class: 'row two' },
        field('Name', h('input', { attrs: { name: 'name', maxlength: 40, autocomplete: 'off' }, value: terminal?.name ?? '' })),
        field('Code', h('input', { attrs: { name: 'code', maxlength: 10, autocomplete: 'off' }, value: terminal?.code ?? '' }))),
      field('Port', h('select', { attrs: { name: 'port' } },
        portOptionEls({ ports: formPorts(open, terminal?.port), selected: terminal?.port ?? open[0]?.key ?? '' }))),
      h('div', { class: 'row two' },
        field('Quay length (m)', h('input', { attrs: { name: 'quay_length', type: 'number', min: 1, max: 10000 }, value: terminal?.quay_length ?? '' })),
        field('Gantry cranes', h('input', { attrs: { name: 'cranes', type: 'number', min: 0, max: 50 }, value: terminal?.cranes ?? '' }))),
      h('div', { class: 'field' }, h('label', null, 'Berths'),
        h('div', { id: 'terminal-berths' }, (terminal?.berths?.length ? terminal.berths : ['']).map(berthRow)),
        h('button', { class: 'btn ghost small', attrs: { type: 'button' }, dataset: { act: 'terminal-berth-add' } }, '+ Berth')),
      h('label', { class: 'check' },
        h('input', { attrs: { type: 'checkbox', name: 'active' }, checked: terminal ? terminal.active : true }), ' On')),
    h('div', { class: 'm-foot' }, h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', 'Cancel'), ' ', btn('primary', 'terminal-save', 'Save'))),
  );
}

export function addBerth() {
  const row = berthRow();
  $('#terminal-berths').append(row);
  row.querySelector('input').focus();
}

export function removeBerth(button) {
  button.closest('.berth-row').remove();
}

let saving = false;

export async function saveTerminalDialog() {
  if (saving || state.ctx.view !== 'terminal') return;
  const form = $('#terminal-form');
  const value = (name) => form.querySelector(`[name="${name}"]`);
  const payload = {
    name: value('name').value,
    code: value('code').value,
    port: value('port').value,
    quay_length: value('quay_length').value,
    cranes: value('cranes').value,
    berths: $$('[data-berth]', form).map((input) => input.value.trim()).filter(Boolean),
    active: value('active').checked,
  };
  const { terminalId, onDone } = state.ctx;
  saving = true;
  try {
    await mutate(() => (terminalId ? api(`/api/operation/terminals/${terminalId}/`, 'PUT', payload)
      : api('/api/operation/terminals/', 'POST', payload)));
  } catch {
    return; // mutate showed the server's message
  } finally {
    saving = false;
  }
  closeModal();
  await onDone?.();
}
