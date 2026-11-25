// The sidebar's folders (Marine, Reports, Master data): each opens / closes, remembered per computer; the folder
// holding the page on screen is always opened.
import { $$ } from './util.js';

const KEY = 'sheet.navGroups'; // {group: false} for the closed ones

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    return saved && typeof saved === 'object' ? saved : {};
  } catch {
    return {};
  }
}

function remember(group, open) {
  const saved = load();
  if (open) delete saved[group];
  else saved[group] = false;
  try {
    localStorage.setItem(KEY, JSON.stringify(saved));
  } catch {
    // not remembered
  }
}

function setOpen(groupEl, open) {
  groupEl.querySelector('.nav-group-items').hidden = !open;
  groupEl.querySelector('.nav-group-head').setAttribute('aria-expanded', String(open));
  groupEl.classList.toggle('closed', !open);
}

/** Close the folders closed last time. */
export function initNavGroups() {
  const saved = load();
  $$('#nav .nav-group').forEach((groupEl) => setOpen(groupEl, saved[groupEl.dataset.group] !== false));
}

/** A folder head clicked. */
export function toggleNavGroup(button) {
  const groupEl = button.closest('.nav-group');
  const open = groupEl.querySelector('.nav-group-items').hidden;
  setOpen(groupEl, open);
  remember(groupEl.dataset.group, open);
}

/** The page on screen: its folder opens (and stays open next time). */
export function openGroupOf(page) {
  const groupEl = $$('#nav .nav-group').find((g) => g.querySelector(`.nav-item[data-page="${page}"]`));
  if (groupEl && groupEl.querySelector('.nav-group-items').hidden) {
    setOpen(groupEl, true);
    remember(groupEl.dataset.group, true);
  }
}
