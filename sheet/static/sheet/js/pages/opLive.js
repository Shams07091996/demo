// Live data (Operation): one card per turned-on terminal of the person's ports — the vessels under operation now
// (ATB, no ATD; moves/hr so far) and those due in the next 7 days. Loads when opened and with Refresh.
import { api } from '../api.js';
import { portOptionEls } from '../components.js';
import { ME } from '../config.js';
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { figure, stamp } from '../operation/shared.js';
import { $ } from '../util.js';

let port = '';
let ticket = 0;
let wired = false;

function table(heads, rows) {
  return h('table', null,
    h('thead', null, h('tr', null, heads.map((t) => h('th', null, t)))),
    h('tbody', null, rows.length ? rows : h('tr', null, h('td', { class: 'none', attrs: { colspan: heads.length } }, 'None'))));
}

function card(t) {
  const working = t.working.map((v) => h('tr', null,
    h('td', null, v.vessel_name), h('td', null, v.shipping_line), h('td', null, v.actual_berth || '—'),
    h('td', null, stamp(v.atb)), h('td', null, figure(v.cranes)), h('td', null, figure(v.discharge)),
    h('td', null, figure(v.loading)), h('td', null, figure(v.live_rate))));
  const upcoming = t.upcoming.map((v) => h('tr', null,
    h('td', null, v.vessel_name), h('td', null, v.shipping_line), h('td', null, stamp(v.eta)),
    h('td', null, figure(v.loa)), h('td', null, v.planned_berth || '—'), h('td', null, stamp(v.etb)),
    h('td', null, stamp(v.etc))));
  return h('section', { class: 'panel op-card' },
    h('h3', null, `${t.name} (${t.code})`),
    h('div', { class: 'op-meta' },
      ME.multiPort ? h('span', null, t.port_label) : null,
      h('span', null, `Quay ${t.quay_length} m`), h('span', null, `Berths ${t.berths.join(' / ')}`),
      h('span', null, `Cranes ${t.cranes}`), h('span', null, `Calls 7 days ${t.calls_7d}`)),
    h('div', { class: 'op-live-grid' },
      h('div', null, h('div', { class: 'dash-title' }, 'Under operation'),
        table(['Vessel', 'Line', 'Berth', 'ATB', 'Cranes', 'Discharge', 'Loading', 'Moves/hr'], working)),
      h('div', null, h('div', { class: 'dash-title' }, 'Next 7 days'),
        table(['Vessel', 'Line', 'ETA', 'LOA', 'Berth', 'ETB', 'ETC'], upcoming))));
}

function wire() {
  if (wired) return;
  wired = true;
  if (ME.multiPort) {
    const select = $('#ol-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => {
      port = select.value === 'ALL' ? '' : select.value;
      load();
    });
  }
}

async function load() {
  wire();
  const mine = ++ticket;
  try {
    const data = await api(`/api/operation/live/${port ? `?port=${encodeURIComponent(port)}` : ''}`);
    if (mine !== ticket) return;
    setChildren($('#ol-cards'), data.terminals.map(card));
    $('#ol-empty').hidden = data.terminals.length > 0;
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
  }
}

export const opLivePage = { load };
