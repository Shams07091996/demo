// Loading data from the server into `state`, then re-drawing. The server filters, sorts, pages and totals;
// the browser only keeps the current page (plus a cache by id for dialogs).
import { api } from './api.js';
import { setStatus } from './feedback.js';
import { calculationsPage } from './pages/calculations.js';
import { MONEY_KINDS, currentDashboardView, renderDashboard, renderDashboardMoney } from './render/dashboard.js';
import { renderAll } from './render/index.js';
import { fillQuickSelects, renderFilterInputs } from './render/list.js';
import { hideRangeNotice, noticeIfOutsideRange } from './render/rangeNotice.js';
import { dashboardParams, emptyDashboard, filterParams, rememberVessels, savePageSize, state } from './state.js';

let latestList = 0;

/** Load the current page of the vessel list. A response that arrives after a newer request is ignored. */
export async function loadVessels() {
  const ticket = ++latestList;
  setStatus('saving', 'Loading…');
  let data;
  try {
    data = await api(`/api/vessels/?${filterParams()}`);
  } catch (error) {
    if (ticket !== latestList) return;
    setStatus('error', 'Load error');
    alert(error.message);
    return;
  }
  if (ticket !== latestList) return;
  state.vessels = data.vessels;
  state.list = { count: data.count, pages: data.pages, page: data.page, totals: data.totals };
  rememberVessels(data.vessels);
  setStatus('ok', 'Synced');
  renderAll();
}

let latestAlerts = 0;

/** Vessels dated today or tomorrow, whatever range the list shows. A late answer to an older request is ignored. */
export async function loadAlerts() {
  const ticket = ++latestAlerts;
  let alerts;
  try {
    const port = state.filter.port === 'ALL' ? '' : `?port=${encodeURIComponent(state.filter.port)}`;
    alerts = await api(`/api/vessels/alerts/${port}`);
  } catch {
    alerts = { today: [], tomorrow: [], missing: [] };
  }
  if (ticket !== latestAlerts) return;
  state.alerts = alerts;
  rememberVessels([...alerts.today, ...alerts.tomorrow]);
  renderAll();
}

let latestDashboard = 0;

export async function loadDashboard() {
  const ticket = ++latestDashboard;
  try {
    const params = dashboardParams();
    if (MONEY_KINDS.includes(params.get('service'))) params.delete('service'); // hotels etc. are the Money view's only
    const data = await api(`/api/dashboard/?${params}`);
    if (ticket !== latestDashboard) return;
    state.dashboard = data;
  } catch (error) {
    if (ticket !== latestDashboard) return;
    state.dashboard = emptyDashboard();
    setStatus('error', error.message);
  }
  renderDashboard();
  if (currentDashboardView() === 'money') await loadDashboardMoney();
}

let latestMoney = 0;

/** The Money view's figures for the Dashboard's filters (only while that view is shown). */
export async function loadDashboardMoney() {
  const ticket = ++latestMoney;
  try {
    const data = await api(`/api/dashboard/money/?${dashboardParams()}`);
    if (ticket !== latestMoney) return;
    state.dashboardMoney = data;
  } catch (error) {
    if (ticket !== latestMoney) return;
    state.dashboardMoney = null;
    setStatus('error', error.message);
  }
  renderDashboardMoney();
}

/** Change one of the Dashboard's own filters (OPR / agent / service type) and reload it. */
export function setDashboardFilter(patch) {
  Object.assign(state.dashboardFilter, patch);
  return loadDashboard();
}

/** Change the filter and reload. Any change except an explicit page goes back to page 1. */
export function setFilter(patch) {
  Object.assign(state.filter, patch);
  if (!('page' in patch)) state.filter.page = 1;
  if ('pageSize' in patch) savePageSize(patch.pageSize);
  hideRangeNotice();
  renderFilterInputs(); // both From / To pairs show the new range at once, before the server answers
  const loads = [loadVessels()];
  if ('port' in patch) loads.push(loadAlerts());
  if (state.page === 'dashboard' && ('from' in patch || 'to' in patch || 'port' in patch)) loads.push(loadDashboard());
  return Promise.all(loads);
}

/** Move From earlier / To later just enough to include these dates (an empty end stays open). */
export function widenRangeTo(fromIso, toIso = fromIso) {
  const patch = {};
  if (state.filter.from && fromIso < state.filter.from) patch.from = fromIso;
  if (state.filter.to && toIso > state.filter.to) patch.to = toIso;
  return setFilter(patch);
}

/** A vessel from the cache, or fetched from the server (e.g. opened from an alert or another page). */
export async function ensureVessel(id) {
  if (state.cache.has(id)) return state.cache.get(id);
  try {
    const vessel = await api(`/api/vessels/${id}/`);
    rememberVessels([vessel]);
    return vessel;
  } catch {
    setStatus('error', 'That vessel is no longer available.');
    return null;
  }
}

/** After creating or editing a vessel: keep it findable. If it belongs to another port than the one shown, switch
 * the port selector to All; if its date is outside the range, show the "Show it" notice. */
export async function afterVesselSaved(vessel) {
  rememberVessels([vessel]);
  if (state.filter.port !== 'ALL' && vessel.port !== state.filter.port) {
    document.querySelector('#portSelect').value = 'ALL';
    await setFilter({ port: 'ALL' });
  } else {
    await refreshAfterChange();
  }
  noticeIfOutsideRange(vessel);
}

/** After any save or delete: reload the page, alerts and (if open) the Dashboard so totals stay right. */
export async function refreshAfterChange() {
  await Promise.all([
    loadVessels(),
    loadAlerts(),
    state.page === 'dashboard' ? loadDashboard() : null,
    state.page === 'calculations' ? calculationsPage.load() : null, // an edit made from that page shows there at once
  ]);
  if (!state.vessels.length && state.filter.page > state.list.pages) {
    state.filter.page = state.list.pages; // the last row of the last page was deleted
    await loadVessels();
  }
}

export async function loadOptions() {
  const writes = state.optionWrites;
  let options;
  try {
    options = (await api('/api/options/')).options;
  } catch {
    options = [];
  }
  // A change saved while this was loading already brought a newer list: keep that one.
  if (state.optionWrites !== writes) return;
  state.options = options;
  fillQuickSelects();
}

export async function loadRates() {
  const [rates, prices] = await Promise.allSettled([api('/api/rates/'), api('/api/disposal-prices/')]);
  state.rates = rates.status === 'fulfilled' ? rates.value.rates : [];
  state.prices = prices.status === 'fulfilled' ? prices.value.prices : [];
}
