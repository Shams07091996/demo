// Re-draw everything that depends on the vessel list.
import { state } from '../state.js';
import { buildNotifications } from './notifications.js';
import { renderDashboard } from './dashboard.js';
import { renderFilterInputs, renderPortBanner, renderTable } from './list.js';
import { renderPager } from './pager.js';

export function renderAll() {
  renderFilterInputs();
  renderTable();
  renderPager();
  renderPortBanner();
  buildNotifications();
  if (state.page === 'dashboard') renderDashboard();
}
