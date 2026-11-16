// The vessels tab: port banner, filter inputs, table and the quick-add dropdowns.
// Everything shown comes from the server (state.vessels = the current page). Clicking a row opens the vessel.
import { PORT_COLOR, PORT_LABEL, ME } from '../config.js';
import { optionChoices, statusChip, tagLabel } from '../components.js';
import { state } from '../state.js';
import { $, $$, dmy, esc, oprClass } from '../util.js';

export function renderPortBanner() {
  const port = ME.port || (state.filter.port !== 'ALL' ? state.filter.port : null);
  const banner = $('#portBanner');
  banner.style.display = port ? 'block' : 'none';
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
    if (arrow) arrow.textContent = th.dataset.sort === sort ? (dir === 'asc' ? '↑' : '↓') : '↕';
  });
}

function rowHtml(v) {
  const tags = v.services.length
    ? `<div class="tags">${v.services.map((s) => `<span class="tag">${esc(tagLabel(s))}</span>`).join('')}</div>`
    : '<span class="none">—</span>';
  return `<tr data-id="${v.id}">
    <td><span class="vessel-name">${esc(v.name)}</span>${v.status && v.status !== 'scheduled' ? statusChip(v.status) : ''}</td>
    <td><span class="badge opr-${oprClass(v.opr)}">${esc(v.opr || '—')}</span></td>
    <td><span class="badge poc">${esc(v.poc || '—')}</span></td>
    <td>${esc(v.agent || '—')}</td>
    <td class="col-port">${esc(PORT_LABEL[v.port] || v.port)}</td>
    <td>${dmy(v.date)}</td>
    <td>${tags}</td>
    <td><button class="btn ghost small btn-green" data-act="summary" data-id="${v.id}">📋 Summary</button></td>
    <td>${ME.canEdit ? `<button class="btn danger small" data-act="del-vessel-row" data-id="${v.id}" title="Delete this vessel and its services">🗑 Delete</button>` : ''}</td>
  </tr>`;
}

/** The current page exactly as the server sent it (already filtered, sorted and paged). */
export function renderTable() {
  $('#empty').style.display = state.vessels.length ? 'none' : 'block';
  $('#tbody').innerHTML = state.vessels.map(rowHtml).join('');
}

/** Refill every OPR / POC / Agent dropdown outside dialogs (quick-add bar and bulk-add defaults), each for its port. */
export function fillQuickSelects() {
  const portOf = (selector) => (ME.isAdmin ? $(selector)?.value || null : ME.port);
  for (const [prefix, port] of [['#qa', portOf('#qa-port')], ['#bk', portOf('#bk-port')]]) {
    for (const kind of ['opr', 'poc', 'agent']) {
      const select = $(`${prefix}-${kind}`);
      select.innerHTML = optionChoices(kind, select.value, port);
    }
  }
}
