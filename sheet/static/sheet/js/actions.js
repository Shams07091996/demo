// Every button in the app has a data-act="name"; this file maps each name to what it does.
import { api, download, mutate } from './api.js';
import { afterVesselSaved, loadDashboardMoney, refreshAfterChange, setDashboardFilter, setFilter, widenRangeTo } from './data.js';
import { conflictAction, showConflict } from './conflict.js';
import { setStatus } from './feedback.js';
import { closeModal } from './modal.js';
import { saveAccountDialog, toggleAccount } from './modals/account.js';
import { savePortDialog, togglePort } from './modals/port.js';
import { addBerth, removeBerth, saveTerminalDialog } from './modals/terminal.js';
import { deleteWindowDialog, saveWindowDialog } from './modals/window.js';
import { windowsPage } from './pages/windows.js';
import { deleteVisit, openVisitDialog, saveVisit } from './modals/visit.js';
import { deleteListedDialog, saveListedDialog } from './modals/listedVessel.js';
import { opLivePage } from './pages/opLive.js';
import { opVesselsPage } from './pages/opVessels.js';
import { terminalsPage } from './pages/terminals.js';
import { vesselListPage } from './pages/vesselList.js';
import { openAgentJobs } from './modals/agentJobs.js';
import { closureNow, openClosureDialog, removeClosure, saveClosure } from './modals/closure.js';
import { addContactRow, deleteCustomerDialog, saveCustomerDialog } from './modals/customer.js';
import { deleteShipDialog, saveShipDialog } from './modals/ship.js';
import { toggleNavGroup } from './navGroups.js';
import { toggleTheme } from './theme.js';
import { openOprSummary, openSummary } from './modals/summary.js';
import { downloadReceipt, openReceipt } from './modals/receipt.js';
import {
  applyRate, cancelBookingRefs, entryRowEl, newCrewMember, openServiceForm, openTypePicker, readServiceForm, renderCrewEditor,
  renumberEntries, toggleCrewBooking, updatePreview,
} from './modals/service.js';
import {
  addGuest, changeVessel, deleteBooking, openBookingDialog, pickVessel, removeGuest, saveBooking,
} from './modals/booking.js';
import { openVessel, openVesselForm, syncSailingDate, updateDelayRow, vesselPayload } from './modals/vessel.js';
import { bookingsPage } from './pages/bookings.js';
import { calculationsPage } from './pages/calculations.js';
import { closuresPage } from './pages/closures.js';
import { customersPage } from './pages/customers.js';
import { disposalPage } from './pages/disposal.js';
import { accountsPage } from './pages/accounts.js';
import { portsPage } from './pages/ports.js';
import { historyPage } from './pages/history.js';
import { newValuePort, renderMasterPage, usageUnit } from './pages/master.js';
import { copyLastMonth, readPriceForm, renderRatesPage } from './pages/rates.js';
import { servicesPage } from './pages/services.js';
import { shipsPage } from './pages/ships.js';
import { MONEY_KINDS, currentDashboardView, showDashboardView } from './render/dashboard.js';
import { fillQuickSelects } from './render/list.js';
import { closePanel, openPanel, toggleAlerts } from './render/notifications.js';
import { hideRangeNotice } from './render/rangeNotice.js';
import { navigate } from './router.js';
import { filterParams, getVessel, rememberVessels, state } from './state.js';
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
  if (service) openServiceForm(service.type, service, { from: state.ctx.from });
  else openVessel(vessel.id);
}

/** After a service save / delete: back to the Services page when the dialog came from there, else the vessel. */
async function afterServiceChange(vessel, from) {
  rememberVessels([vessel]);
  await refreshAfterChange();
  if (from === 'services') {
    closeModal();
    await servicesPage.load();
  } else openVessel(vessel.id);
}

/** Save a service, then show the vessel with its refreshed totals (the list and totals reload from the server).
 *  An edit sends the version the form opened with (`version`: the one from a conflict, for "Save mine anyway"). */
async function saveService(version) {
  const { type, serviceId, from } = state.ctx;
  const status = $('#svc-form [name=status]').value;
  const payload = {
    type, agent: $('#svc-form [name=agent]').value, status, data: readServiceForm(),
    billing: $('#svc-form [name=billing]').value,
    billing_party: Number($('#svc-form [name=billing_party]').value) || null,
    cancel_reason: status === 'cancelled' ? $('#svc-form [name=cancel_reason]').value : '',
  };
  const refs = status === 'cancelled' ? cancelBookingRefs() : [];
  if (refs.length) payload.cancel_bookings = refs;
  if (serviceId) payload.version = version ?? state.ctx.version;
  const vessel = await mutate(() => (serviceId
    ? api(`/api/services/${serviceId}/`, 'PUT', payload)
    : api(`/api/vessels/${vesselId()}/services/`, 'POST', payload)), (conflict) => showConflict(conflict, 'service', {
    reload: () => reloadServiceForm(serviceId), force: (current) => saveService(current),
  }));
  await afterServiceChange(vessel, from);
}

async function deleteService(button) {
  if (!confirm('Delete this service?')) return;
  const { from } = state.ctx;
  const vessel = await mutate(() => api(`/api/services/${button.dataset.id}/`, 'DELETE'));
  await afterServiceChange(vessel, from);
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
// A crew member's Hotel / Transport button: switch it and show / hide its boxes.
const crewBooking = (button, kind) => {
  const card = crewCard(button);
  toggleCrewBooking(state.crew[card.dataset.group][Number(card.dataset.i)], kind, card.dataset.group);
  renderCrewEditor();
};

export const actions = {
  close: closeModal,
  back: () => (vesselId() ? openVessel(vesselId()) : closeModal()),
  goto: (b) => { closeModal(); navigate(b.dataset.page); },
  print: () => window.print(),
  'open-vessel': (b) => openVessel(Number(b.dataset.id)),
  summary: (b) => { closePanel(); openSummary(Number(b.dataset.id)); },
  'opr-summary': (b) => openOprSummary(b.dataset.opr),
  'agent-jobs': (b) => openAgentJobs(b.dataset.agent),
  'dash-view': (b) => {
    const leaving = currentDashboardView() === 'money';
    showDashboardView(b.dataset.view);
    if (b.dataset.view === 'money') return loadDashboardMoney();
    // Hotels / Transport / Garbage & Sludge exist only on the Money view: leaving it drops that choice.
    if (leaving && MONEY_KINDS.includes(state.dashboardFilter.service)) return setDashboardFilter({ service: '' });
    return null;
  },
  'toggle-theme': toggleTheme,
  'toggle-nav-group': toggleNavGroup,
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
  'add-entry': () => { $('#entries').append(entryRowEl(state.ctx.type)); renumberEntries(); updatePreview(); applyRate(); },
  'rm-entry': (b) => { b.closest('.entry').remove(); renumberEntries(); updatePreview(); },

  'add-crew': (b) => { state.crew[b.dataset.group].push(newCrewMember()); renderCrewEditor(); },
  'rm-crew': (b) => { const c = crewCard(b); state.crew[c.dataset.group].splice(Number(c.dataset.i), 1); renderCrewEditor(); },
  'crew-hotel': (b) => crewBooking(b, 'hotel'),
  'crew-transport': (b) => crewBooking(b, 'transport'),
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
  // A page's rows as a plain-table Excel file (its current filters, every page of them).
  'page-export': async (b) => {
    const pages = { vessels: { exportQuery: () => filterParams({ page: '', page_size: '' }) }, hotels: bookingsPage('hotels'), transfers: bookingsPage('transfers'), closures: closuresPage,
      disposal: disposalPage, calculations: calculationsPage, services: servicesPage };
    const page = pages[b.dataset.page];
    if (!page) return;
    const error = await download(`/api/export/${b.dataset.page}/?${page.exportQuery()}`, 'Could not make the Excel file.');
    if (error) setStatus('error', error);
  },
  // The five pages' rows for the Dashboard's From - To range and port, one sheet each.
  'dashboard-data-export': async () => {
    const { from, to, port } = state.filter;
    const query = new URLSearchParams({ from: from || '', to: to || '', port: port && port !== 'ALL' ? port : '' });
    const error = await download(`/api/export/all/?${query}`, 'Could not make the Excel file.');
    if (error) setStatus('error', error);
  },
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
  'services-page': (b) => servicesPage.step(Number(b.dataset.step)),
  'service-row': (b) => servicesPage.open(Number(b.dataset.id)),
  'sv-toggle': (b) => servicesPage.toggle(Number(b.dataset.id)),
  'acct-toggle': (b) => calculationsPage.toggleClosed(b),
  'disposal-hide': (b) => disposalPage.hide(b.dataset.id),
  'disposal-show': (b) => disposalPage.show(b.dataset.id),
  'history-page': (b) => historyPage.step(Number(b.dataset.step)),
  'booking-pick-vessel': pickVessel,
  'booking-change-vessel': changeVessel,
  'booking-add-guest': addGuest,
  'booking-del-guest': removeGuest,
  'booking-save': () => saveBooking(),
  'booking-delete': deleteBooking,

  'customer-new': () => customersPage.open(null),
  'customer-open': (b) => customersPage.open(Number(b.dataset.id)),
  'customer-save': () => saveCustomerDialog(),
  'customer-del': () => deleteCustomerDialog(),
  'contact-add': () => addContactRow(),
  'contact-remove': (b) => b.closest('.contact-row')?.remove(),
  'customer-ship': (b) => shipsPage.openById(Number(b.dataset.id)),
  'account-new': () => accountsPage.open(null),
  'account-open': (b) => accountsPage.open(Number(b.dataset.id)),
  'account-save': () => saveAccountDialog(),
  'account-toggle': () => toggleAccount(),
  'port-new': () => portsPage.open(null),
  'port-open': (b) => portsPage.open(b.dataset.key),
  'port-save': () => savePortDialog(),
  'port-toggle': () => togglePort(),
  'ship-new': () => shipsPage.open(null),
  'ship-open': (b) => shipsPage.open(Number(b.dataset.id)),
  'ship-save': () => saveShipDialog(),
  'ship-del': () => deleteShipDialog(),
  'closure-new': () => openClosureDialog(),
  'closure-open': (b) => openClosureDialog(Number(b.dataset.id)),
  'closure-save': () => saveClosure(),
  'closure-del': removeClosure,
  'closure-now': closureNow,
  'terminal-new': () => terminalsPage.open(null),
  'terminal-open': (b) => terminalsPage.open(Number(b.dataset.id)),
  'terminal-save': () => saveTerminalDialog(),
  'terminal-berth-add': () => addBerth(),
  'terminal-berth-del': removeBerth,
  'window-new': () => windowsPage.open(null),
  'window-open': (b) => windowsPage.open(Number(b.dataset.id)),
  'window-save': () => saveWindowDialog(),
  'window-delete': () => deleteWindowDialog(),
  'vl-new': () => vesselListPage.open(null),
  'vl-open': (b) => vesselListPage.open(Number(b.dataset.id)),
  'vl-save': () => saveListedDialog(),
  'vl-del': () => deleteListedDialog(),
  'opv-new': () => openVisitDialog(),
  'opv-open': (b) => openVisitDialog(Number(b.dataset.id)),
  'opv-save': () => saveVisit(),
  'opv-save-another': () => saveVisit(undefined, true),
  'opv-del': () => deleteVisit(),
  'opv-sort': (b) => opVesselsPage.sort(b.dataset.key),
  'opv-prev': () => opVesselsPage.prev(),
  'opv-next': () => opVesselsPage.next(),
  'opv-export': async () => {
    const error = await download(`/api/operation/visits/export/?${opVesselsPage.exportQuery()}`, 'Could not make the Excel file.');
    if (error) setStatus('error', error);
  },
  'op-live-refresh': () => opLivePage.load(),
  'live-export': async () => {
    const error = await download(`/api/operation/live/export/?${opLivePage.exportQuery()}`, 'Could not make the Excel file.');
    if (error) setStatus('error', error);
  },

  'conflict-reload': () => conflictAction('reload'),
  'conflict-force': () => conflictAction('force'),
};
