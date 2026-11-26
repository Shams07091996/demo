// The Vessel Data dialog: one visit. The terminal comes first; the berth lists follow it (a saved berth no longer
// on the list is kept). The figures are the server's, shown read-only. Without "Add / edit vessel data" it only shows.
import { api, mutate } from '../api.js';
import { showConflict } from '../conflict.js';
import { deleteBtn, headEl } from '../components.js';
import { can } from '../config.js';
import { h, setChildren } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import {
  DAYS, figure, loadListed, loadTerminals, statusEl, terminalById, terminalLines, terminalOptionEls,
} from '../operation/shared.js';
import { opVesselsPage, visitById } from '../pages/opVessels.js';
import { optionValues, state } from '../state.js';
import { $ } from '../util.js';

// Estimates on the first row, actual times on the second.
const TIMES = [['eta', 'ETA'], ['etb', 'ETB'], ['etc', 'ETC'], ['ata', 'ATA'], ['atb', 'ATB'], ['atd', 'ATD']];
const NUMBERS = [['loa', 'LOA (m)', '0.1'], ['cranes', 'Cranes', '1'], ['discharge', 'Discharge (moves)', '1'],
  ['loading', 'Loading (moves)', '1']];

const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);

function berthOptions(terminal, current) {
  const berths = terminal ? [...terminal.berths] : [];
  if (current && !berths.includes(current)) berths.push(current);
  return [h('option', { value: '' }, '—'), ...berths.map((b) => h('option', { value: b, selected: b === current }, b))];
}

/** The shipping lines on offer: the terminal's own (or its port's list), keeping the one chosen. */
function lineOptions(terminal, current) {
  const values = terminalLines(terminal, optionValues('line', terminal?.port ?? null));
  const all = current && !values.includes(current) ? [...values, current] : values;
  return [h('option', { value: '' }, '—'), ...all.map((v) => h('option', { value: v, selected: v === current }, v))];
}

let listed = [];

const figuresEl = (v) => h('div', { class: 'op-figures' },
  statusEl(v.status),
  ...[['Waiting', v.waiting, 'h'], ['Operation', v.operation, 'h'], ['Port stay', v.port_stay, 'h'],
    ['Total moves', v.total_moves, ''], ['Moves/hr', v.productivity, '']]
    .map(([label, value, unit]) => h('span', null, `${label}: `, h('strong', null, figure(value)), value !== null && unit ? ` ${unit}` : '')));

export async function openVisitDialog(id = null) {
  const visit = id ? visitById(id) : null;
  if (id && !visit) return;
  const terminals = (await loadTerminals()).filter((t) => t.active || t.id === visit?.terminal);
  listed = await loadListed().catch(() => []); // suggestions only: the dialog works without them
  const editable = can('operation.edit');
  state.ctx = { view: 'visit', visitId: id, version: visit?.version };
  const terminal = terminalById(visit?.terminal) || terminals[0] || null;
  const input = (name, extra = {}) => h('input', { attrs: { name, ...extra }, value: visit?.[name] ?? '', disabled: !editable });
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(visit ? `${visit.vessel_name} · Visit ${visit.id}` : 'Add visit'),
    h('div', { class: 'm-body', id: 'visit-form' },
      visit ? figuresEl(visit) : null,
      h('div', { class: 'row two' },
        field('Terminal', h('select', { attrs: { name: 'terminal' }, disabled: !editable },
          terminalOptionEls(terminals, terminal?.id, null))),
        field('Vessel name', [input('vessel_name', { maxlength: 100, autocomplete: 'off', list: 'op-listed' }),
          h('datalist', { id: 'op-listed' }, listed.map((v) => h('option', { value: v.name })))])),
      h('div', { class: 'row two' },
        field('Shipping line', h('select', { attrs: { name: 'shipping_line' }, disabled: !editable },
          lineOptions(terminal, visit?.shipping_line || ''))),
        field('LOA (m)', input('loa', { type: 'number', min: 0, max: 500, step: '0.1' }))),
      h('div', { class: 'visit-window', id: 'visit-window', hidden: true }),
      h('div', { class: 'row two' },
        field('Planned berth', h('select', { attrs: { name: 'planned_berth' }, disabled: !editable },
          berthOptions(terminal, visit?.planned_berth))),
        field('Actual berth', h('select', { attrs: { name: 'actual_berth' }, disabled: !editable },
          berthOptions(terminal, visit?.actual_berth)))),
      h('div', { class: 'row three' }, TIMES.map(([name, label]) => field(label, input(name, { type: 'datetime-local' })))),
      h('div', { class: 'row four' }, NUMBERS.filter(([name]) => name !== 'loa').map(([name, label, step]) =>
        field(label, input(name, { type: 'number', min: name === 'cranes' ? 1 : 0, step }))))),
    h('div', { class: 'm-foot' },
      visit && can('operation.delete') ? deleteBtn('opv-del') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', editable ? 'Cancel' : 'Close'),
        editable ? [' ', btn('primary', 'opv-save', 'Save')] : null)),
  );
  showWindow();
}

let windowTicket = 0;

/** "Fri 27.11 22:00" from the server's local "2026-11-27T22:00" and the window's day. */
const when = (day, local) => `${DAYS[day]} ${local.slice(8, 10)}.${local.slice(5, 7)} ${local.slice(11, 16)}`;

/** The line's berthing window nearest the ETA at this terminal (the server works it out); nothing without one. */
async function showWindow() {
  const box = $('#visit-window');
  if (!box) return;
  const value = (name) => $(`#visit-form [name="${name}"]`).value;
  const [terminal, line, eta] = [value('terminal'), value('shipping_line'), value('eta')];
  const mine = ++windowTicket;
  let found = null;
  if (terminal && line && eta) {
    const query = new URLSearchParams({ terminal, line, eta });
    found = await api(`/api/operation/windows/nearest/?${query}`).then((r) => r.nearest, () => null);
  }
  if (mine !== windowTicket || state.ctx.view !== 'visit') return;
  box.hidden = !found;
  if (!found) return setChildren(box);
  const w = found.window;
  const where = found.position === 'inside' ? 'ETA inside the window'
    : `ETA ${found.hours} h ${found.position === 'before' ? 'before' : 'after the start'}`;
  setChildren(box, h('strong', null, 'Window: '), `${when(w.start_day, found.start)} → ${when(w.end_day, found.end)}`,
    h('span', { class: 'none' }, ` · ${where}`));
}

/** The terminal was changed: offer its berths and its port's shipping lines (keeping what is chosen). */
export function onVisitFormChange(event) {
  if (state.ctx.view !== 'visit') return;
  if (event.target.name === 'vessel_name') { // a name from the vessel list brings its LOA
    const match = listed.find((v) => v.name === event.target.value.trim().toUpperCase());
    if (match) {
      $('#visit-form [name="loa"]').value = match.loa;
      const line = $('#visit-form [name="shipping_line"]');
      if (match.line && [...line.options].some((o) => o.value === match.line)) line.value = match.line;
      showWindow();
    }
    return;
  }
  if (['shipping_line', 'eta'].includes(event.target.name)) return void showWindow();
  if (event.target.name !== 'terminal') return;
  const terminal = terminalById(event.target.value);
  for (const name of ['planned_berth', 'actual_berth']) {
    const select = $(`#visit-form [name="${name}"]`);
    setChildren(select, berthOptions(terminal, ''));
  }
  const line = $('#visit-form [name="shipping_line"]');
  setChildren(line, lineOptions(terminal, line.value));
  showWindow();
}

function payload() {
  const form = $('#visit-form');
  const value = (name) => form.querySelector(`[name="${name}"]`).value;
  const names = ['terminal', 'vessel_name', 'shipping_line', 'planned_berth', 'actual_berth',
    ...TIMES.map(([name]) => name), ...NUMBERS.map(([name]) => name)];
  return Object.fromEntries(names.map((name) => [name, value(name)]));
}

let saving = false;

/** Save the dialog; an edit sends the version it opened with (`version`: the one from a conflict). */
export async function saveVisit(version) {
  if (saving || state.ctx.view !== 'visit') return;
  const { visitId } = state.ctx;
  const body = payload();
  if (visitId) body.version = version ?? state.ctx.version;
  saving = true;
  try {
    await mutate(() => (visitId ? api(`/api/operation/visits/${visitId}/`, 'PUT', body)
      : api('/api/operation/visits/', 'POST', body)),
    (conflict) => showConflict(conflict, 'visit', {
      reload: async () => { await opVesselsPage.load(); openVisitDialog(visitId); },
      force: (current) => saveVisit(current),
    }));
  } catch {
    return; // mutate showed the error in the dialog
  } finally {
    saving = false;
  }
  closeModal();
  await opVesselsPage.load();
}

export async function deleteVisit() {
  const { visitId } = state.ctx;
  const visit = visitById(visitId);
  if (!visit || !confirm(`Delete visit ${visit.id} (${visit.vessel_name})? This cannot be undone.`)) return;
  try {
    await mutate(() => api(`/api/operation/visits/${visitId}/`, 'DELETE'));
  } catch {
    return;
  }
  closeModal();
  await opVesselsPage.load();
}
