// The bell and the banner: vessels with a date of today or tomorrow (state.alerts, from the server).
import { state } from '../state.js';
import { $, dayISO, dmy, esc, today } from '../util.js';  // today / dayISO only label the groups

const COLLAPSED_KEY = 'sheet.alertsCollapsed';

/** Is the banner shrunk to its one-line summary? (remembered in this browser) */
export function alertsCollapsed() {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

export function toggleAlerts() {
  try {
    localStorage.setItem(COLLAPSED_KEY, alertsCollapsed() ? '0' : '1');
  } catch {
    // storage blocked: nothing to remember it in
  }
  buildNotifications();
}

const serviceTags = (v) => v.services.map((s) => `<span class="tag">${esc(s.type)}</span>`).join(' ');

export function buildNotifications() {
  const todayIso = today();
  const tomorrowIso = dayISO(1);
  const todays = state.alerts.today;
  const tomorrows = state.alerts.tomorrow;
  const total = todays.length + tomorrows.length;

  const badge = $('#bellBadge');
  badge.style.display = total ? 'flex' : 'none';
  badge.textContent = total > 9 ? '9+' : total;
  $('#bell').classList.toggle('alert', total > 0);

  const bannerRow = (v, kind, label) =>
    `<div class="notif-row ${kind}" data-act="summary" data-id="${v.id}"><b>${label}</b><span>🚢 ${esc(v.name)}</span>${serviceTags(v)}</div>`;
  const banner = $('#notifBanner');
  const collapsed = alertsCollapsed();
  banner.style.display = total ? 'flex' : 'none';
  banner.classList.toggle('collapsed', collapsed);
  const head = `<div class="notif-head"><span>🔴 <b>${todays.length}</b> today · 🟡 <b>${tomorrows.length}</b> tomorrow</span>
    <span class="spacer"></span>
    <button class="btn ghost small" data-act="toggle-alerts" aria-expanded="${!collapsed}">${collapsed ? 'Show ▾' : 'Hide ▴'}</button></div>`;
  banner.innerHTML = head + (collapsed ? '' :
    todays.map((v) => bannerRow(v, 'today', '🔴 Today')).join('') +
    tomorrows.map((v) => bannerRow(v, 'tomorrow', '🟡 Tomorrow')).join(''));

  const panelItem = (v) => `<div class="notif-item" data-act="summary" data-id="${v.id}">
      <b>🚢 ${esc(v.name)}</b>
      <div class="none" style="font-size:12px">📅 ${dmy(v.date)} · ${esc(v.opr)}</div>
      <div style="margin-top:4px">${serviceTags(v)}</div></div>`;
  const group = (list, color, title) =>
    list.length ? `<div class="notif-group" style="color:${color}">${title}</div>${list.map(panelItem).join('')}` : '';
  $('#notifPanel').innerHTML = total
    ? group(todays, 'var(--danger)', `🔴 Today — ${dmy(todayIso)}`) + group(tomorrows, 'var(--gold)', `🟡 Tomorrow — ${dmy(tomorrowIso)}`)
    : '<div class="empty">✅ No vessels today or tomorrow.</div>';
}

export const closePanel = () => $('#notifPanel').classList.remove('open');

export function togglePanel() {
  buildNotifications();
  $('#notifPanel').classList.toggle('open');
}
