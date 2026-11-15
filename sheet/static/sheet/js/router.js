// Sidebar navigation. The page lives in the URL hash (#vessels, #master…), so refresh and Back work.
import { ME } from './config.js';
import { loadDashboard, loadOptions, loadRates } from './data.js';
import { hotelsPage, transportPage } from './pages/bookings.js';
import { initBulkPage } from './pages/bulk.js';
import { renderMasterPage } from './pages/master.js';
import { renderRatesPage } from './pages/rates.js';
import { state } from './state.js';
import { $, $$ } from './util.js';

const TITLES = {
  vessels: 'Vessels',
  bulk: 'Bulk add',
  hotels: 'Hotels',
  transport: 'Transport',
  dashboard: 'Dashboard',
  master: 'Master data',
  rates: 'Exchange rates',
};

const pageFromHash = () => {
  const name = window.location.hash.slice(1);
  return name in TITLES ? name : 'vessels';
};

export async function showPage(requested) {
  const name = requested === 'bulk' && !ME.canEdit ? 'vessels' : requested; // read-only users cannot add
  state.page = name;
  $$('.page').forEach((page) => { page.hidden = page.id !== `page-${name}`; });
  $$('#nav .nav-item').forEach((link) => link.classList.toggle('active', link.dataset.page === name));
  $('#pageTitle').textContent = TITLES[name];
  document.body.classList.remove('nav-open');

  if (name === 'dashboard') await loadDashboard();
  if (name === 'bulk') initBulkPage();
  if (name === 'hotels') await hotelsPage.load();
  if (name === 'transport') await transportPage.load();
  if (name === 'master') {
    await loadOptions(); // refresh the "used by N vessels" counts
    renderMasterPage();
  }
  if (name === 'rates') {
    await loadRates();
    renderRatesPage();
  }
}

/** Go to a page (used by buttons inside dialogs). */
export function navigate(name) {
  if (window.location.hash === `#${name}`) showPage(name);
  else window.location.hash = name;
}

export function startRouter() {
  window.addEventListener('hashchange', () => showPage(pageFromHash()));
  return showPage(pageFromHash());
}
