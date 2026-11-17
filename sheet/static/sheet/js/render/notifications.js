// The bell and the banner: vessels with a date of today or tomorrow (state.alerts, from the server).
import { state } from '../state.js';
import { h, setChildren } from '../dom.js';
import { $, dayISO, dmy, today } from '../util.js';  // today / dayISO only label the groups

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

// Tags separated by spaces, as before.
const serviceTags = (v) => v.services.flatMap((s, i) => [i ? ' ' : null, h('span', { class: 'tag' }, s.type)]);

export function buildNotifications() {
  const todayIso = today();
  const tomorrowIso = dayISO(1);
  const todays = state.alerts.today;
  const tomorrows = state.alerts.tomorrow;
  const total = todays.length + tomorrows.length;

  const badge = $('#bellBadge');
  badge.hidden = !total;
  badge.textContent = total > 9 ? '9+' : total;
  $('#bell').classList.toggle('alert', total > 0);

  const bannerRow = (v, kind, label) =>
    h('div', { class: `notif-row ${kind}`, dataset: { act: 'summary', id: v.id } },
      h('b', null, label), h('span', null, `🚢 ${v.name}`), serviceTags(v));
  const banner = $('#notifBanner');
  const collapsed = alertsCollapsed();
  banner.hidden = !total;
  banner.classList.toggle('collapsed', collapsed);
  const head = h('div', { class: 'notif-head' },
    h('span', null, '🔴 ', h('b', null, todays.length), ' today · 🟡 ', h('b', null, tomorrows.length), ' tomorrow'),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn ghost small', dataset: { act: 'toggle-alerts' }, attrs: { 'aria-expanded': String(!collapsed) } },
      collapsed ? 'Show ▾' : 'Hide ▴'));
  setChildren(banner, head, collapsed ? null : [
    todays.map((v) => bannerRow(v, 'today', '🔴 Today')),
    tomorrows.map((v) => bannerRow(v, 'tomorrow', '🟡 Tomorrow')),
  ]);

  const panelItem = (v) => h('div', { class: 'notif-item', dataset: { act: 'summary', id: v.id } },
    h('b', null, `🚢 ${v.name}`),
    h('div', { class: 'none', style: { fontSize: '12px' } }, `📅 ${dmy(v.date)} · ${v.opr}`),
    h('div', { style: { marginTop: '4px' } }, serviceTags(v)));
  const group = (list, color, title) =>
    list.length ? [h('div', { class: 'notif-group', style: { color } }, title), list.map(panelItem)] : null;
  setChildren($('#notifPanel'), total
    ? [group(todays, 'var(--danger)', `🔴 Today — ${dmy(todayIso)}`), group(tomorrows, 'var(--gold)', `🟡 Tomorrow — ${dmy(tomorrowIso)}`)]
    : h('div', { class: 'empty' }, '✅ No vessels today or tomorrow.'));
}

export const closePanel = () => $('#notifPanel').classList.remove('open');

export function togglePanel() {
  buildNotifications();
  $('#notifPanel').classList.toggle('open');
}
