// Sidebar navigation. The page lives in the URL hash (#vessels, #master…), so refresh and Back work.
import { ME } from './config.js';
import { loadDashboard, loadOptions, loadRates } from './data.js';
import { hotelsPage, transportPage } from './pages/bookings.js';
import { calculationsPage } from './pages/calculations.js';
import { closuresPage } from './pages/closures.js';
import { disposalPage } from './pages/disposal.js';
import { historyPage } from './pages/history.js';
import { renderMasterPage } from './pages/master.js';
import { renderRatesPage } from './pages/rates.js';
import { shipsPage } from './pages/ships.js';
import { state } from './state.js';
import { $, $$ } from './util.js';

const TITLES = {
  vessels: 'Vessels',
  hotels: 'Hotels',
  transport: 'Transport',
  closures: 'Port closures',
  disposal: 'Garbage & Sludge',
  calculations: 'Calculations',
  dashboard: 'Dashboard',
  ships: 'Ships',
  master: 'Master data',
  rates: 'Exchange rates',
  history: 'History',
};

const pageFromHash = () => {
  const name = window.location.hash.slice(1);
  return name in TITLES ? name : 'vessels';
};

export async function showPage(requested) {
  let name = requested;
  if (name === 'history' && !ME.isAdmin) name = 'vessels'; // the change history is for admins only
  state.page = name;
  $$('.page').forEach((page) => { page.hidden = page.id !== `page-${name}`; });
  $$('#nav .nav-item').forEach((link) => link.classList.toggle('active', link.dataset.page === name));
  $('#pageTitle').textContent = TITLES[name];
  document.body.classList.remove('nav-open');

  if (name === 'dashboard') await loadDashboard();
  if (name === 'hotels') await hotelsPage.load();
  if (name === 'transport') await transportPage.load();
  if (name === 'closures') await closuresPage.load();
  if (name === 'disposal') await disposalPage.load();
  if (name === 'calculations') await calculationsPage.load();
  if (name === 'history') await historyPage.load();
  if (name === 'ships') await shipsPage.load();
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
