// The Berthing windows dialog: terminal (turned-on ones of the person's ports), one of its shipping lines, and the
// weekly start / end (day + time, Cairo). Delete removes the window. The server checks everything again (overlaps too).
import { api, mutate } from '../api.js';
import { deleteBtn, headEl } from '../components.js';
import { h, optionEls, setChildren } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { DAYS, terminalLines } from '../operation/shared.js';
import { optionValues, state } from '../state.js';
import { $ } from '../util.js';

const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);
const dayEls = (selected) => optionEls(DAYS.map((d, i) => [String(i), d]), String(selected));

function lineEls(terminal, current) {
  const values = terminalLines(terminal, optionValues('line', terminal?.port ?? null));
  const all = current && !values.includes(current) ? [...values, current] : values;
  return optionEls([['', 'Choose…'], ...all.map((v) => [v, v])], current);
}

export function openWindowDialog(found, terminals, onDone) {
  const offered = terminals.filter((t) => t.active || t.id === found?.terminal);
  const terminal = offered.find((t) => t.id === found?.terminal) || offered[0] || null;
  state.ctx = { view: 'window', windowId: found?.id ?? null, terminals: offered, onDone };
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(found ? `${found.line} · ${found.terminal_name}` : 'Add window'),
    h('div', { class: 'm-body', id: 'window-form' },
      h('div', { class: 'row two' },
        field('Terminal', h('select', { class: 'select', attrs: { name: 'terminal' } },
          offered.map((t) => h('option', { value: t.id, selected: t.id === terminal?.id }, t.name)))),
        field('Line', h('select', { class: 'select', attrs: { name: 'line' } }, lineEls(terminal, found?.line ?? '')))),
      h('div', { class: 'row four' },
        field('From', h('select', { class: 'select', attrs: { name: 'start_day' } }, dayEls(found?.start_day ?? 0))),
        field('Time', h('input', { attrs: { name: 'start_time', type: 'time' }, value: found?.start_time ?? '' })),
        field('To', h('select', { class: 'select', attrs: { name: 'end_day' } }, dayEls(found?.end_day ?? 0))),
        field('Time', h('input', { attrs: { name: 'end_time', type: 'time' }, value: found?.end_time ?? '' })))),
    h('div', { class: 'm-foot' },
      found ? deleteBtn('window-delete') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', 'Cancel'), ' ', btn('primary', 'window-save', 'Save'))),
  );
}

/** The terminal changed: offer its lines (keeping the chosen one when it is still offered). */
export function onWindowFormChange(event) {
  if (state.ctx.view !== 'window' || event.target.name !== 'terminal') return;
  const terminal = state.ctx.terminals.find((t) => t.id === Number(event.target.value)) || null;
  const line = $('#window-form [name="line"]');
  const keep = terminalLines(terminal, optionValues('line', terminal?.port ?? null)).includes(line.value) ? line.value : '';
  setChildren(line, lineEls(terminal, keep));
}

let saving = false;

export async function saveWindowDialog() {
  if (saving || state.ctx.view !== 'window') return;
  const form = $('#window-form');
  const value = (name) => form.querySelector(`[name="${name}"]`).value;
  const payload = { terminal: value('terminal'), line: value('line'), start_day: value('start_day'),
    start_time: value('start_time'), end_day: value('end_day'), end_time: value('end_time') };
  const { windowId, onDone } = state.ctx;
  saving = true;
  try {
    await mutate(() => (windowId ? api(`/api/operation/windows/${windowId}/`, 'PUT', payload)
      : api('/api/operation/windows/', 'POST', payload)));
  } catch {
    return; // mutate showed the server's message
  } finally {
    saving = false;
  }
  closeModal();
  await onDone?.();
}

export async function deleteWindowDialog() {
  const { windowId, onDone } = state.ctx;
  if (state.ctx.view !== 'window' || !windowId) return;
  if (!confirm('Delete this berthing window?')) return;
  try {
    await mutate(() => api(`/api/operation/windows/${windowId}/`, 'DELETE'));
  } catch {
    return;
  }
  closeModal();
  await onDone?.();
}
