// Entry point: wires the page together and loads the first data.
import { initTheme } from './theme.js';
import { actions, moveOption } from './actions.js';
import { portOptionEls } from './components.js';
import { ME, el } from './config.js';
import { loadAlerts, loadOptions, loadVessels, setDashboardFilter, setFilter } from './data.js';
import { setChildren } from './dom.js';
import { setStatus } from './feedback.js';
import { closeModal, isModalOpen } from './modal.js';
import { onBookingInput } from './modals/booking.js';
import { onClosureFormChange } from './modals/closure.js';
import { onModalChange, onModalInput } from './modals/service.js';
import { onVesselFormChange, openVessel, openVesselForm } from './modals/vessel.js';
import { setupQuickAdd } from './quickAdd.js';
import { fillQuickSelects, renderFilterInputs } from './render/list.js';
import { closePanel, togglePanel } from './render/notifications.js';
import { startRouter } from './router.js';
import { state } from './state.js';
import { $, $$ } from './util.js';

/* ---- one click handler for every [data-act] button, plus table-row clicks ---- */
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-act]');
  if (button && actions[button.dataset.act]) {
    event.preventDefault();
    event.stopPropagation();
    // Failed saves already show their error (see api.mutate), so a rejection needs no further handling.
    Promise.resolve(actions[button.dataset.act](button)).catch(() => {});
    return;
  }
  const row = event.target.closest('#tbody tr[data-id]');
  if (row) {
    openVessel(Number(row.dataset.id));
    return;
  }
  if (!event.target.closest('.bell-wrap')) closePanel();
});

el.overlay.addEventListener('mousedown', (event) => { if (event.target === el.overlay) closeModal(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closePanel();
    if (isModalOpen()) closeModal();
  }
  // Enter inside an "add to list" box presses its Add button.
  if (event.key === 'Enter' && event.target.matches('[data-new]')) {
    event.preventDefault();
    event.target.parentElement.querySelector('[data-act="add-option"]').click();
  }
});
el.modal.addEventListener('input', onModalInput);
el.modal.addEventListener('change', onModalChange);
el.modal.addEventListener('change', onVesselFormChange); // admin switches a vessel's port, times change
el.modal.addEventListener('input', onVesselFormChange);  // times typed: show / hide the delay reason
el.modal.addEventListener('input', onBookingInput);  // hotel stay / transfer dialog
el.modal.addEventListener('change', onBookingInput);
el.modal.addEventListener('change', onClosureFormChange); // admin switches a closure's port

/* ---- top bar and sidebar ---- */
$('#bell').addEventListener('click', (event) => { event.stopPropagation(); togglePanel(); });
// The menu button: on a small screen the sidebar slides in over the page; on a wide screen it hides / shows (remembered).
const NAV_KEY = 'sheet.navCollapsed';
const isNarrow = () => window.matchMedia?.('(max-width: 900px)').matches;
try {
  if (localStorage.getItem(NAV_KEY) === '1') document.body.classList.add('nav-collapsed');
} catch {
  // storage blocked: the sidebar simply starts shown
}
$('#menuBtn').addEventListener('click', () => {
  if (isNarrow()) {
    document.body.classList.toggle('nav-open');
    return;
  }
  const collapsed = document.body.classList.toggle('nav-collapsed');
  try {
    localStorage.setItem(NAV_KEY, collapsed ? '1' : '0');
  } catch {
    // not remembered
  }
});
$('#scrim').addEventListener('click', () => document.body.classList.remove('nav-open'));
$('#roleLabel').textContent = ME.port ? `${ME.role} port` : ME.role;

/* ---- vessels page: date range, chips, search, sorting, paging, add (the server does the filtering) ---- */
$('#filters').addEventListener('click', (event) => {
  const chip = event.target.closest('.chip');
  if (chip) setFilter({ bucket: chip.dataset.filter });
});

const SEARCH_DELAY_MS = 300; // ask the server only once typing pauses
let searchTimer;
$('#search').addEventListener('input', (event) => {
  clearTimeout(searchTimer);
  const q = event.target.value;
  searchTimer = setTimeout(() => setFilter({ q }), SEARCH_DELAY_MS);
});

$$('th[data-sort]').forEach((th) => th.addEventListener('click', () => {
  const sort = th.dataset.sort;
  const { sort: current, dir } = state.filter;
  const nextDir = sort === current ? (dir === 'asc' ? 'desc' : 'asc') : 'asc';
  setFilter({ sort, dir: nextDir });
}));

// The same From / To pair lives on the Vessels page and the Dashboard; both edit state.filter.
// Browsers report every keystroke in a date field (typing 2027 passes through 0002, 0020, 0202), so wait for a
// pause, ignore half-typed years, and never reset a field while someone is typing in it.
const DATE_DELAY_MS = 400;
const typingYear = (iso) => iso && Number(iso.slice(0, 4)) < 1900;
let dateTimer;
for (const [fromSel, toSel, clearSel] of [['#f-from', '#f-to', '#f-clear'], ['#d-from', '#d-to', '#d-clear']]) {
  const apply = () => {
    const from = $(fromSel).value;
    const to = $(toSel).value;
    if (typingYear(from) || typingYear(to)) return; // still typing the year
    if (from && to && from > to) {
      setStatus('error', 'From must be on or before To.');
      return;
    }
    if (from === state.filter.from && to === state.filter.to) return;
    setFilter({ from, to });
  };
  const onChange = () => {
    clearTimeout(dateTimer);
    dateTimer = setTimeout(apply, DATE_DELAY_MS);
  };
  $(fromSel).addEventListener('change', onChange);
  $(toSel).addEventListener('change', onChange);
  $(clearSel).addEventListener('click', () => {
    clearTimeout(dateTimer);
    setFilter({ from: '', to: '' });
  });
}

$('#pager').addEventListener('change', (event) => {
  if (event.target.id === 'page-size') setFilter({ pageSize: Number(event.target.value) });
});

$('#qa-port').addEventListener('change', fillQuickSelects); // quick-add lists follow the chosen port
$('#master-grid').addEventListener('change', (event) => {
  if (event.target.matches('select[data-option-port]')) moveOption(event.target);
});

if (ME.canEdit) $('#addVesselBtn').addEventListener('click', () => openVesselForm(null));
else $('#addVesselBtn').hidden = true;
setupQuickAdd();

/* ---- port selector (admin and read-only users see every port) ---- */
if (ME.seesAll) {
  document.body.classList.add('show-port');
  const select = $('#portSelect');
  setChildren(select, portOptionEls({ all: true }));
  select.hidden = false;
  select.addEventListener('change', () => {
    if (ME.isAdmin && select.value !== 'ALL') {
      $('#qa-port').value = select.value;
      fillQuickSelects();
    }
    setFilter({ port: select.value });
  });
  // The Dashboard's own port selector drives the same shared port (and the same side effects) as the one above.
  const dashPort = $('#d-port');
  setChildren(dashPort, portOptionEls({ all: true }));
  dashPort.hidden = false;
  dashPort.addEventListener('change', () => {
    select.value = dashPort.value;
    select.dispatchEvent(new Event('change'));
  });
}

/* ---- the Dashboard's own filters ---- */
for (const [selector, key] of [['#d-opr', 'opr'], ['#d-agent', 'agent'], ['#d-service', 'service']]) {
  $(selector).addEventListener('change', (event) => setDashboardFilter({ [key]: event.target.value }));
}

initTheme();
renderFilterInputs();
loadOptions();
loadVessels();
loadAlerts();
startRouter();
