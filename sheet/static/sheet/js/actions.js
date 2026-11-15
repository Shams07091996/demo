// Every button in the app has a data-act="name"; this file maps each name to what it does.
import { api, mutate } from './api.js';
import { afterVesselSaved, refreshAfterChange, setFilter, widenRangeTo } from './data.js';
import { closeModal } from './modal.js';
import { openOprSummary, openSummary } from './modals/summary.js';
import {
  entryRowHtml, newCrewMember, openServiceForm, openTypePicker, readServiceForm, renderCrewEditor,
  renumberEntries, updatePreview,
} from './modals/service.js';
import {
  addGuest, changeVessel, deleteBooking, openBookingDialog, pickVessel, removeGuest, saveBooking,
} from './modals/booking.js';
import { openVessel, openVesselForm, vesselPayload } from './modals/vessel.js';
import { bookingsPage } from './pages/bookings.js';
import {
  addBulkRow, applyToAllRows, clearBulk, createBulk, previewBulk, removeBulkRow, viewCreated,
} from './pages/bulk.js';
import { renderMasterPage, usageUnit } from './pages/master.js';
import { renderRatesPage } from './pages/rates.js';
import { fillQuickSelects } from './render/list.js';
import { closePanel, toggleAlerts } from './render/notifications.js';
import { hideRangeNotice } from './render/rangeNotice.js';
import { navigate } from './router.js';
import { getVessel, rememberVessels, state } from './state.js';
import { $, formValues, nowLocalInput } from './util.js';

const vesselId = () => state.ctx.vesselId;

/** Save a service, then show the vessel with its refreshed totals (the list and totals reload from the server). */
async function saveService() {
  const { type, serviceId } = state.ctx;
  const payload = { type, data: readServiceForm() };
  const vessel = await mutate(() => (serviceId
    ? api(`/api/services/${serviceId}/`, 'PUT', payload)
    : api(`/api/vessels/${vesselId()}/services/`, 'POST', payload)));
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

async function saveVessel({ addAnother }) {
  const payload = vesselPayload();
  const id = vesselId();
  const vessel = await mutate(() => (id ? api(`/api/vessels/${id}/`, 'PUT', payload) : api('/api/vessels/', 'POST', payload)));
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

async function changeOption(request) {
  state.options = (await mutate(request)).options;
  fillQuickSelects();
  renderMasterPage();
}

async function removeOption(button) {
  const used = Number(button.dataset.used);
  const note = used ? `${used} ${usageUnit(button.dataset.kind, used)} ${used === 1 ? 'uses' : 'use'} it and will keep the value. ` : '';
  if (!confirm(`${note}Remove "${button.dataset.value}" from the list?`)) return;
  await changeOption(() => api(`/api/options/${button.dataset.id}/`, 'DELETE'));
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
  'toggle-alerts': toggleAlerts,
  'show-outside': async (b) => { await widenRangeTo(b.dataset.date); hideRangeNotice(); },
  'page-prev': () => setFilter({ page: Math.max(1, state.filter.page - 1) }),
  'page-next': () => setFilter({ page: state.filter.page + 1 }),

  'add-service': openTypePicker,
  'pick-type': (b) => openServiceForm(b.dataset.type, null),
  'edit-service': (b) => {
    const service = getVessel(vesselId()).services.find((s) => s.id === Number(b.dataset.id));
    openServiceForm(service.type, service);
  },
  'save-service': saveService,
  'del-service': deleteService,
  'add-entry': () => { $('#entries').insertAdjacentHTML('beforeend', entryRowHtml(state.ctx.type)); renumberEntries(); updatePreview(); },
  'rm-entry': (b) => { b.closest('.entry').remove(); renumberEntries(); updatePreview(); },

  'add-crew': (b) => { state.crew[b.dataset.group].push(newCrewMember()); renderCrewEditor(); },
  'rm-crew': (b) => { const c = crewCard(b); state.crew[c.dataset.group].splice(Number(c.dataset.i), 1); renderCrewEditor(); },
  'toggle-crew': (b) => {
    const card = crewCard(b);
    const member = state.crew[card.dataset.group][Number(card.dataset.i)];
    member._open = !member._open;
    card.classList.toggle('open', member._open);
  },
  'pdf-pick': () => $('#pdf-input').click(),

  'edit-vessel': () => openVesselForm(getVessel(vesselId())),
  'save-vessel': () => saveVessel({ addAnother: false }),
  'save-vessel-more': () => saveVessel({ addAnother: true }),
  'del-vessel': () => deleteVessel(),
  'del-vessel-row': (b) => deleteVessel(Number(b.dataset.id)),
  'time-now': (b) => { $(`#vessel-form [name="${b.dataset.target}"]`).value = nowLocalInput(); },

  'save-rate': () => changeRate(() => api('/api/rates/', 'POST', formValues($('#rate-form')))),
  'del-rate': (b) => changeRate(() => api(`/api/rates/${b.dataset.id}/`, 'DELETE')),

  'add-option': (b) => {
    const input = $(`[data-new="${b.dataset.kind}"]`);
    if (!input.value.trim()) return undefined;
    return changeOption(() => api('/api/options/', 'POST', { kind: b.dataset.kind, value: input.value }));
  },
  'del-option': removeOption,

  'bulk-preview': previewBulk,
  'bulk-create': createBulk,
  'bulk-clear': clearBulk,
  'bulk-view': viewCreated,
  'bulk-add-row': addBulkRow,
  'bulk-del-row': (b) => removeBulkRow(Number(b.dataset.i)),
  'bulk-apply-all': applyToAllRows,

  'booking-new': (b) => openBookingDialog(b.dataset.kind),
  'booking-open': (b) => openBookingDialog(b.dataset.kind, Number(b.dataset.id)),
  'booking-page': (b) => bookingsPage(b.dataset.kind).step(Number(b.dataset.step)),
  'booking-pick-vessel': pickVessel,
  'booking-change-vessel': changeVessel,
  'booking-add-guest': addGuest,
  'booking-del-guest': removeGuest,
  'booking-save': saveBooking,
  'booking-delete': deleteBooking,
};
