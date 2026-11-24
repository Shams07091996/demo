// The type-ahead on a vessel name box (quick-add bar and vessel form): as the person types, up to 10 active ships
// matching the name or IMO; the last item is always "+ New ship". Picking fills the box and reports the ship;
// typing after a pick clears it. Keyboard: Up / Down, Enter, Escape. Built with dom.js only.
import { api } from './api.js';
import { h, setChildren } from './dom.js';

const DELAY_MS = 250;
const MIN_CHARS = 2;
const LIMIT = 10;

export const shipLabel = (s) => `${s.name} · ${s.imo || 'No IMO'} · ${s.opr || '—'}`;

/**
 * attachShipPicker(input, { picked, onPick(ship), onClear(), onNew(name), onEnter() })
 * `picked` is the ship already linked (or null). onEnter runs when Enter is pressed with a ship picked (quick-add
 * adds the vessel). Returns { picked() -> ship | null, set(ship) }.
 */
export function attachShipPicker(input, { picked = null, onPick, onClear, onNew, onEnter } = {}) {
  const menu = h('div', { class: 'ship-menu', attrs: { role: 'listbox' }, hidden: true });
  input.after(menu);
  input.setAttribute('autocomplete', 'off');
  let current = picked;
  let items = [];
  let active = -1;
  let ticket = 0;
  let timer = null;

  // Closing also drops a search still waiting or on its way, so it can't reopen the list afterwards.
  const close = () => { clearTimeout(timer); ticket += 1; menu.hidden = true; active = -1; };
  const render = () => {
    setChildren(menu, items.map((item, i) => h('div', {
      class: i === active ? 'ship-opt active' : 'ship-opt', attrs: { role: 'option' }, dataset: { i },
    }, item.ship ? shipLabel(item.ship) : `+ New ship "${item.name}"`)));
    menu.hidden = items.length === 0;
  };
  const pick = (ship) => {
    current = ship;
    input.value = ship.name;
    close();
    onPick?.(ship);
  };
  const choose = (i) => {
    const item = items[i];
    if (!item) return null;
    if (item.ship) pick(item.ship);
    else { close(); onNew?.(item.name); }
    return item;
  };

  async function search() {
    const text = input.value.trim().toUpperCase();
    const mine = ++ticket;
    if (text.length < MIN_CHARS) { items = []; render(); return; }
    let ships = [];
    try {
      ships = (await api(`/api/ships/?${new URLSearchParams({ active: '1', limit: String(LIMIT), q: text })}`)).ships;
    } catch {
      ships = []; // the "+ New ship" item still shows
    }
    if (mine !== ticket) return; // an older answer: a newer search is on its way
    items = [...ships.map((ship) => ({ ship })), { name: text }];
    active = -1;
    render();
  }

  input.addEventListener('input', () => {
    if (current) { current = null; onClear?.(); }
    clearTimeout(timer);
    timer = setTimeout(search, DELAY_MS);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (menu.hidden) return;
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      active = (active + step + items.length) % items.length;
      render();
    } else if (event.key === 'Escape' && !menu.hidden) {
      event.stopPropagation(); // close the list, not the dialog
      close();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (!menu.hidden && active >= 0) {
        const item = choose(active);
        if (item?.ship) onEnter?.();
      } else if (current) onEnter?.();
      else if (input.value.trim()) { close(); onNew?.(input.value.trim().toUpperCase()); }
    }
  });
  // mousedown, not click: the box keeps its focus, so the list doesn't close before the pick.
  menu.addEventListener('mousedown', (event) => {
    const option = event.target.closest('.ship-opt');
    if (!option) return;
    event.preventDefault();
    choose(Number(option.dataset.i));
  });
  input.addEventListener('blur', () => setTimeout(close, 150));

  return {
    picked: () => current,
    set: (ship) => { current = ship; if (ship) input.value = ship.name; },
  };
}
