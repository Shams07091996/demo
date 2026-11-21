// Every button in the app has a data-act="name"; this file maps each name to what it does.
import { api, download, mutate } from './api.js';
import { afterVesselSaved, refreshAfterChange, setFilter, widenRangeTo } from './data.js';
import { conflictAction, showConflict } from './conflict.js';
import { setStatus } from './feedback.js';
import { closeModal } from './modal.js';
import { openAgentJobs } from './modals/agentJobs.js';
import { closureNow, openClosureDialog, removeClosure, saveClosure } from './modals/closure.js';
import { toggleTheme } from './theme.js';
import { openOprSummary, openSummary } from './modals/summary.js';
import { downloadReceipt, openReceipt } from './modals/receipt.js';
import {
  entryRowEl, newCrewMember, openServiceForm, openTypePicker, readServiceForm, renderCrewEditor,
  renumberEntries, updatePreview,
} from './modals/service.js';
import {
  addGuest, changeVessel, deleteBooking, openBookingDialog, pickVessel, removeGuest, saveBooking,
} from './modals/booking.js';
import { openVessel, openVesselForm, syncSailingDate, updateDelayRow, vesselPayload } from './modals/vessel.js';
import { bookingsPage } from './pages/bookings.js';
import { calculationsPage } from './pages/calculations.js';
import { disposalPage } from './pages/disposal.js';
import { historyPage } from './pages/history.js';
import { newValuePort, renderMasterPage, usageUnit } from './pages/master.js';
import { copyLastMonth, readPriceForm, renderRatesPage } from './pages/rates.js';
import { fillQuickSelects } from './render/list.js';
import { closePanel, openPanel, toggleAlerts } from './render/notifications.js';
import { hideRangeNotice } from './render/rangeNotice.js';
import { navigate } from './router.js';
import { getVessel, rememberVessels, state } from './state.js';
import { $, formValues, nowLocalInput } from './util.js';

const vesselId = () => state.ctx.vesselId;

/** Reopen the vessel form / a service form with the record as saved on the server now (after a conflict). */
async function reloadVesselForm(id) {
  const vessel = await api(`/api/vessels/${id}/`);
  rememberVessels([vessel]);
  openVesselForm(vessel);
}

async function reloadServiceForm(id) {
  const vessel = await api(`/api/vessels/${vesselId()}/`);
  rememberVessels([vessel]);
  const service = vessel.services.find((s) => s.id === id);
  if (service) openServiceForm(service.type, service);
  else openVessel(vessel.id);
}

/** Save a service, then show the vessel with its refreshed totals (the list and totals reload from the server).
 *  An edit sends the version the form opened with (`version`: the one from a conflict, for "Save mine anyway"). */
async function saveService(version) {
  const { type, serviceId } = state.ctx;
  const payload = { type, agent: $('#svc-form [name=agent]').value, data: readServiceForm() };
  if (serviceId) payload.version = version ?? state.ctx.version;
  const vessel = await mutate(() => (serviceId
    ? api(`/api/services/${serviceId}/`, 'PUT', payload)
    : api(`/api/vessels/${vesselId()}/services/`, 'POST', payload)), (conflict) => showConflict(conflict, 'service', {
    reload: () => reloadServiceForm(serviceId), force: (current) => saveService(current),
  }));
  rememberVessels([vessel]);
  await refreshAfterChange();
  openVessel(vessel.id);
}

async function deleteService(button) {
  if (!confirm('Delete this service?')) return;
  const vessel = await mutate(() => api(`/api/services/${button.dataset.id}/`, 'DELETE'));
  rememberVessels([vessel]);
  await refreshAfterChange();
  openVessel(vessel.id);
}

async function saveVessel({ addAnother, version }) {
  const payload = vesselPayload();
  const id = vesselId();
  if (id) payload.version = version ?? state.ctx.version;
  const vessel = await mutate(() => (id ? api(`/api/vessels/${id}/`, 'PUT', payload) : api('/api/vessels/', 'POST', payload)),
    (conflict) => showConflict(conflict, 'vessel', {
      reload: () => reloadVesselForm(id), force: (current) => saveVessel({ addAnother, version: current }),
    }));
  await afterVesselSaved(vessel);
  if (addAnother) openVesselForm(null);
  else openVessel(vessel.id);
}

/** Delete a vessel (from its dialog or from the Delete button in its table row), after asking. */
async function deleteVessel(id = vesselId()) {
  const vessel = getVessel(id);
  if (!vessel || !confirm(`Delete ${vessel.name} and all of its services, hotel stays and transfers? This cannot be undone.`)) return;
  await mutate(() => api(`/api/vessels/${vessel.id}/`, 'DELETE'));
  state.cache.delete(vessel.id);
  closeModal();
  await refreshAfterChange();
}

/** Save or delete an exchange rate, then refresh the vessels (their totals depend on the rate). */
async function changeRate(request) {
  state.rates = (await mutate(request)).rates;
  state.cache.clear(); // cached figures used the old rate
  await refreshAfterChange();
  renderRatesPage();
}

/** Save or delete a Garbage & Sludge price (its money is on its own page and Calculations, not in vessel figures). */
async function changePrice(request) {
  state.prices = (await mutate(request)).prices;
  renderRatesPage();
}

async function changeOption(request) {
  state.options = (await mutate(request)).options;
  state.optionWrites += 1;
  fillQuickSelects();
  renderMasterPage();
}

async function removeOption(button) {
  const used = Number(button.dataset.used);
  const note = used ? `${used} ${usageUnit(button.dataset.kind, used)} ${used === 1 ? 'uses' : 'use'} it and will keep the value. ` : '';
  if (!confirm(`${note}Remove "${button.dataset.value}" from the list?`)) return;
  await changeOption(() => api(`/api/options/${button.dataset.id}/`, 'DELETE'));
}

/** Admins: move a Master-data value to another port ('' = All ports). */
export function moveOption(select) {
  return changeOption(() => api(`/api/options/${select.dataset.id}/`, 'PATCH', { port: select.value })).catch(() => {
    renderMasterPage(); // refused (e.g. duplicate): show the value where it really is
  });
}

const crewCard = (button) => button.closest('.crew-card');

export const actions = {
  close: closeModal,
  back: () => (vesselId() ? openVessel(vesselId()) : closeModal()),
  goto: (b) => { closeModal(); navigate(b.dataset.page); },
  print: () => window.print(),
  'open-vessel': (b) => openVessel(Number(b.dataset.id)),
  summary: (b) => { closePanel(); openSummary(Number(b.dataset.id)); },
  'opr-summary': (b) => openOprSummary(b.dataset.opr),
  'agent-jobs': (b) => openAgentJobs(b.dataset.agent),
  'toggle-theme': toggleTheme,
  'toggle-alerts': toggleAlerts,
  'show-alerts-panel': openPanel,
  'show-outside': async (b) => { await widenRangeTo(b.dataset.date); hideRangeNotice(); },
  'page-prev': () => setFilter({ page: Math.max(1, state.filter.page - 1) }),
  'page-next': () => setFilter({ page: state.filter.page + 1 }),

  'add-service': openTypePicker,
  'pick-type': (b) => openServiceForm(b.dataset.type, null),
  'edit-service': (b) => {
    const service = getVessel(vesselId()).services.find((s) => s.id === Number(b.dataset.id));
    openServiceForm(service.type, service);
  },
  'save-service': () => saveService(),
  'del-service': deleteService,
  'add-entry': () => { $('#entries').append(entryRowEl(state.ctx.type)); renumberEntries(); updatePreview(); },
  'rm-entry': (b) => { b.closest('.entry').remove(); renumberEntries(); updatePreview(); },

  'add-crew': (b) => { state.crew[b.dataset.group].push(newCrewMember()); renderCrewEditor(); },
  'rm-crew': (b) => { const c = crewCard(b); state.crew[c.dataset.group].splice(Number(c.dataset.i), 1); renderCrewEditor(); },
  'toggle-crew': (b) => {
    const card = crewCard(b);
    const member = state.crew[card.dataset.group][Number(card.dataset.i)];
    member._open = !member._open;
    card.classList.toggle('open', member._open);
  },

  'edit-vessel': () => openVesselForm(getVessel(vesselId())),
  'save-vessel': () => saveVessel({ addAnother: false }),
  'save-vessel-more': () => saveVessel({ addAnother: true }),
  'del-vessel': () => deleteVessel(),
  'del-vessel-row': (b) => deleteVessel(Number(b.dataset.id)),
  // The LOG letter of an on-signer: fetched, then saved as a file (an error shows in the status line instead).
  'crew-log': async (link) => {
    const error = await download(link.href, 'Could not make the LOG.');
    if (error) setStatus('error', error);
  },
  // The management workbook (.xlsx) of the Dashboard's From - To range and port.
  'dashboard-export': async () => {
    const { from, to, port } = state.filter;
    const query = new URLSearchParams({ from: from || '', to: to || '', port: port && port !== 'ALL' ? port : '' });
    const error = await download(`/api/dashboard/export/?${query}`, 'Could not make the Excel file.');
    if (error) setStatus('error', error);
  },
  receipt: (b) => openReceipt(Number(b.dataset.id)),
  'receipt-download': downloadReceipt,

  'time-now': (b) => {
    $(`#vessel-form [name="${b.dataset.target}"]`).value = nowLocalInput();
    updateDelayRow();
    syncSailingDate();
  },

  'save-rate': () => changeRate(() => api('/api/rates/', 'POST', formValues($('#rate-form')))),
  'del-rate': (b) => changeRate(() => api(`/api/rates/${b.dataset.id}/`, 'DELETE')),
  'save-price': () => changePrice(() => api('/api/disposal-prices/', 'POST', readPriceForm())),
  'copy-price': () => copyLastMonth(),
  'del-price': (b) => changePrice(() => api(`/api/disposal-prices/${b.dataset.id}/`, 'DELETE')),

  'add-option': (b) => {
    const input = $(`[data-new="${b.dataset.kind}"]`);
    if (!input.value.trim()) return undefined;
    const port = $(`select[data-new-port="${b.dataset.kind}"]`)?.value || '';
    newValuePort[b.dataset.kind] = port; // offered again for the next value of this list
    return changeOption(() => api('/api/options/', 'POST', { kind: b.dataset.kind, value: input.value, port }));
  },
  'del-option': removeOption,


  'booking-new': (b) => openBookingDialog(b.dataset.kind),
  'booking-open': (b) => openBookingDialog(b.dataset.kind, Number(b.dataset.id)),
  'booking-page': (b) => bookingsPage(b.dataset.kind).step(Number(b.dataset.step)),
  'calc-page': (b) => calculationsPage.step(Number(b.dataset.step)),
  'disposal-hide': (b) => disposalPage.hide(b.dataset.id),
  'disposal-show': (b) => disposalPage.show(b.dataset.id),
  'history-page': (b) => historyPage.step(Number(b.dataset.step)),
  'booking-pick-vessel': pickVessel,
  'booking-change-vessel': changeVessel,
  'booking-add-guest': addGuest,
  'booking-del-guest': removeGuest,
  'booking-save': () => saveBooking(),
  'booking-delete': deleteBooking,

  'closure-new': () => openClosureDialog(),
  'closure-open': (b) => openClosureDialog(Number(b.dataset.id)),
  'closure-save': () => saveClosure(),
  'closure-del': removeClosure,
  'closure-now': closureNow,

  'conflict-reload': () => conflictAction('reload'),
  'conflict-force': () => conflictAction('force'),
};
