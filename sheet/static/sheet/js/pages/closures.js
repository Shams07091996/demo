// The Port closures page: when each port was shut (weather, fog, strike...), filtered by a date range (closures that
// overlap it) and, for admins / read-only, by port. The server scopes port users to their own port.
import { api, mutate } from '../api.js';
import { portOptionEls } from '../components.js';
import { ME } from '../config.js';
import { h, icon, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { defaultRange } from '../state.js';
import { $, fmtStamp } from '../util.js';

const DATE_DELAY_MS = 400;
const typingYear = (iso) => iso && Number(iso.slice(0, 4)) < 1900;

const COLUMNS = [
  ME.seesAll ? { title: 'Port', cell: (c) => c.port_label } : null,
  { title: 'Closed from', cell: (c) => fmtStamp(c.start_at) },
  { title: 'Reopened', cell: (c) => (c.end_at ? fmtStamp(c.end_at) : 'Still closed') },
  { title: 'Hours', cell: (c) => (c.hours === null ? '—' : c.hours.toFixed(1)) },
  { title: 'Reason', cell: (c) => c.reason },
  { title: 'Notes', cell: (c) => c.notes || '—' },
].filter(Boolean);

const filter = { ...defaultRange(), port: 'ALL' };
let closures = [];
let ticket = 0;
let wired = false;

function params() {
  const values = { from: filter.from, to: filter.to, port: filter.port === 'ALL' ? '' : filter.port };
  return new URLSearchParams(Object.entries(values).filter(([, v]) => v));
}

const deleteButton = (c) =>
  h('button', { class: 'btn danger small', dataset: { act: 'closure-del', id: c.id }, attrs: { title: 'Delete this closure' } },
    icon('trash'), ' Delete');

function render() {
  setChildren($('#pc-head'), h('tr', null, COLUMNS.map((c) => h('th', null, c.title)), ME.canEdit ? h('th') : null));
  const row = (c) => h('tr', c.can_edit ? { class: 'clickable', dataset: { act: 'closure-open', id: c.id } } : null,
    COLUMNS.map((col) => h('td', null, col.cell(c))),
    ME.canEdit ? h('td', null, c.can_edit ? deleteButton(c) : null) : null);
  setChildren($('#pc-tbody'), closures.map(row));
  $('#pc-empty').hidden = closures.length > 0;
  const from = $('#pc-from');
  const to = $('#pc-to');
  if (document.activeElement !== from) from.value = filter.from;
  if (document.activeElement !== to) to.value = filter.to;
  from.max = filter.to;
  to.min = filter.from;
}

async function load() {
  wire();
  const mine = ++ticket;
  let data;
  try {
    data = await api(`/api/closures/?${params()}`);
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
    return;
  }
  if (mine !== ticket) return; // a newer request is on its way
  closures = data.closures;
  render();
}

function setFilter(patch) {
  Object.assign(filter, patch);
  return load();
}

/** Hook up the page's own controls once, the first time it is shown. */
function wire() {
  if (wired) return;
  wired = true;
  if (ME.seesAll) {
    const select = $('#pc-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => setFilter({ port: select.value }));
  }
  let dateTimer;
  const onDate = () => {
    clearTimeout(dateTimer);
    dateTimer = setTimeout(() => {
      const from = $('#pc-from').value;
      const to = $('#pc-to').value;
      if (typingYear(from) || typingYear(to)) return;
      if (from && to && from > to) {
        setStatus('error', 'From must be on or before To.');
        return;
      }
      if (from !== filter.from || to !== filter.to) setFilter({ from, to });
    }, DATE_DELAY_MS);
  };
  $('#pc-from').addEventListener('change', onDate);
  $('#pc-to').addEventListener('change', onDate);
  $('#pc-clear').addEventListener('click', () => setFilter({ from: '', to: '' }));
}

/** A closure from the list on screen (for the dialog). */
export const closureById = (id) => closures.find((c) => c.id === id) || null;

/** Delete a closure (its row's button or the dialog's), after asking. */
export async function deleteClosure(id) {
  const closure = closureById(id);
  if (!closure || !confirm(`Delete the ${closure.port_label} closure of ${fmtStamp(closure.start_at)}? This cannot be undone.`)) return false;
  await mutate(() => api(`/api/closures/${id}/`, 'DELETE'));
  await load();
  return true;
}

/** The list query without paging: what the Excel button exports (every row these filters show). */
function exportQuery() {
  const query = params();
  query.delete('page');
  query.delete('page_size');
  return query;
}

export const closuresPage = { load, exportQuery };
