// The Ships page: every ship (name, IMO, OPR, customer, port calls), searched by name or IMO. Admins and port users
// add and edit ships; everyone reads them. Inactive ships are greyed (and left out of the vessel name dropdown).
import { api } from '../api.js';
import { ME } from '../config.js';
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openShipDialog } from '../modals/ship.js';
import { $ } from '../util.js';

const SEARCH_DELAY_MS = 300;
const filter = { q: '', active: 'all' };
let ships = [];
let ticket = 0;
let wired = false;

function render() {
  setChildren($('#sh-head'), h('tr', null, ['Name', 'IMO', 'OPR', 'Customer', 'Port calls'].map((t) => h('th', null, t))));
  const row = (s) => h('tr', { class: [ME.canEdit ? 'clickable' : '', s.active ? '' : 'inactive'].join(' ').trim(),
    dataset: ME.canEdit ? { act: 'ship-open', id: s.id } : null },
  h('td', null, s.name), h('td', null, s.imo || 'No IMO'), h('td', null, s.opr || '—'),
  h('td', null, s.customer ? s.customer.name : '—'), h('td', null, String(s.calls)));
  setChildren($('#sh-tbody'), ships.map(row));
  $('#sh-empty').hidden = ships.length > 0;
}

function wire() {
  if (wired) return;
  wired = true;
  let timer = null;
  $('#sh-q').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { filter.q = e.target.value.trim(); shipsPage.load(); }, SEARCH_DELAY_MS);
  });
  $('#sh-active').addEventListener('change', (e) => { filter.active = e.target.value; shipsPage.load(); });
}

export const shipsPage = {
  async load() {
    wire();
    const mine = ++ticket;
    const params = new URLSearchParams();
    if (filter.q) params.set('q', filter.q);
    if (filter.active === 'active') params.set('active', '1');
    try {
      const data = await api(`/api/ships/?${params}`);
      if (mine !== ticket) return;
      ships = data.ships;
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(id) {
    const ship = id ? ships.find((s) => s.id === id) : null;
    openShipDialog(ship, () => shipsPage.load());
  },
};
