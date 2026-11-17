// The vessels tab: port banner, filter inputs, table and the quick-add dropdowns.
// Everything shown comes from the server (state.vessels = the current page). Clicking a row opens the vessel.
import { PORT_COLOR, PORT_LABEL, ME } from '../config.js';
import { optionChoicesEl, sortIcon, statusChipEl, tagLabel } from '../components.js';
import { h, icon, setChildren } from '../dom.js';
import { state } from '../state.js';
import { $, $$, dmy, oprClass } from '../util.js';

export function renderPortBanner() {
  const port = ME.port || (state.filter.port !== 'ALL' ? state.filter.port : null);
  const banner = $('#portBanner');
  banner.hidden = !port;
  if (!port) return;
  banner.style.color = PORT_COLOR[port];
  banner.style.borderTopColor = PORT_COLOR[port];
  banner.textContent = `${PORT_LABEL[port]} — showing vessels for this port only`;
}

/** Keep the From / To inputs (Vessels and Dashboard), chips and sort arrows in step with state.filter. */
export function renderFilterInputs() {
  const { from, to, bucket, sort, dir } = state.filter;
  for (const [fromSel, toSel] of [['#f-from', '#f-to'], ['#d-from', '#d-to']]) {
    const fromInput = $(fromSel);
    const toInput = $(toSel);
    // Never overwrite a field the person is typing in (a reply to an earlier request may arrive meanwhile).
    if (document.activeElement !== fromInput) fromInput.value = from;
    if (document.activeElement !== toInput) toInput.value = to;
    fromInput.max = to; // the browser can't pick From after To
    toInput.min = from;
  }
  $$('#filters .chip').forEach((c) => c.classList.toggle('active', c.dataset.filter === bucket));
  $$('th[data-sort]').forEach((th) => {
    const arrow = th.querySelector('.arrow');
    if (arrow) setChildren(arrow, sortIcon(th.dataset.sort === sort, dir));
  });
}

function rowEl(v) {
  const tags = v.services.length
    ? h('div', { class: 'tags' }, v.services.map((s) => h('span', { class: 'tag' }, tagLabel(s))))
    : h('span', { class: 'none' }, '—');
  return h('tr', { dataset: { id: v.id } },
    h('td', null, h('span', { class: 'vessel-name' }, v.name), v.status && v.status !== 'scheduled' ? statusChipEl(v.status) : null),
    h('td', null, h('span', { class: `badge opr-${oprClass(v.opr)}` }, v.opr || '—')),
    h('td', null, h('span', { class: 'badge poc' }, v.poc || '—')),
    h('td', null, v.arrival_agent || '—'),
    h('td', null, v.sailing_agent || '—'),
    h('td', { class: 'col-port' }, PORT_LABEL[v.port] || v.port),
    h('td', null, dmy(v.date)),
    h('td', null, tags),
    h('td', null, h('button', { class: 'btn ghost small btn-green', dataset: { act: 'summary', id: v.id } }, icon('file'), ' Summary')),
    h('td', null, ME.canEdit
      ? h('button', { class: 'btn danger small', dataset: { act: 'del-vessel-row', id: v.id }, attrs: { title: 'Delete this vessel and its services' } }, icon('trash'), ' Delete')
      : null),
  );
}

/** The current page exactly as the server sent it (already filtered, sorted and paged). */
export function renderTable() {
  $('#empty').hidden = state.vessels.length > 0;
  setChildren($('#tbody'), state.vessels.map(rowEl));
}

/** Refill every OPR / POC / Agent dropdown outside dialogs (the quick-add bar), for its port. */
export function fillQuickSelects() {
  const port = ME.isAdmin ? $('#qa-port')?.value || null : ME.port;
  for (const kind of ['opr', 'poc', 'agent']) {
    const select = $(`#qa-${kind}`);
    setChildren(select, optionChoicesEl(kind, select.value, port));
  }
}
