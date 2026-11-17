// Dark / light mode. The page follows the computer until the user picks; the pick is kept in a cookie (so the server
// renders it at once, no flash) and in localStorage (kept if the cookie is cleared).
import { $ } from './util.js';

const KEY = 'theme';
const THEMES = ['light', 'dark'];

/** The mode shown now: the chosen one, else the computer's. */
export function currentTheme() {
  const chosen = document.documentElement.dataset.theme;
  if (THEMES.includes(chosen)) return chosen;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function labelButton() {
  const label = $('#themeBtn .label');
  if (label) label.textContent = currentTheme() === 'dark' ? 'Light mode' : 'Dark mode';
}

function apply(theme, { remember }) {
  document.documentElement.dataset.theme = theme;
  if (remember) {
    const secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `${KEY}=${theme}; path=/; max-age=31536000; SameSite=Lax${secure}`;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // private window / blocked storage: the cookie still remembers it
    }
  }
  labelButton();
}

export function toggleTheme() {
  apply(currentTheme() === 'dark' ? 'light' : 'dark', { remember: true });
}

/** On load: the server already applied the cookie; otherwise use a choice remembered in localStorage. */
export function initTheme() {
  if (!THEMES.includes(document.documentElement.dataset.theme)) {
    let saved = null;
    try {
      saved = localStorage.getItem(KEY);
    } catch {
      // blocked storage: follow the computer
    }
    if (THEMES.includes(saved)) apply(saved, { remember: true });
  }
  labelButton();
}
