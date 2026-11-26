// Live data (Operation): one card per turned-on terminal of the person's ports — the vessels under operation now
// (ATB, no ATD; moves/hr so far) and those due in the next 7 days. Loads when opened and with Refresh. The buttons
// under the port choice show All or one terminal (like the vessel list's All / ARK / MSK).
import { api } from '../api.js';
import { portOptionEls } from '../components.js';
import { ME } from '../config.js';
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { figure, stamp } from '../operation/shared.js';
import { $ } from '../util.js';

let port = '';
let terminal = ''; // a terminal id as text, '' = all
let terminals = [];
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
    h('td', null, v.vessel_name, v.arrived
      ? [' ', h('span', { class: 'status-chip st-operating', attrs: { title: `ATA ${stamp(v.ata)}` } }, 'Arrived')] : null,
      v.overdue ? [' ', h('span', { class: 'status-chip st-overdue', attrs: { title: `ETA ${stamp(v.eta)}` } }, 'Overdue')] : null),
    h('td', null, v.shipping_line), h('td', null, stamp(v.eta)),
    h('td', null, figure(v.loa)), h('td', null, v.planned_berth || '—'), h('td', null, stamp(v.etb)),
    h('td', null, stamp(v.etc))));
  return h('section', { class: 'panel op-card' },
    // The terminal's picture, when the server's folder has one (operation/pictures.py).
    t.picture ? h('img', { class: 'op-pic', attrs: { src: `/api/operation/terminals/${t.id}/picture/`, alt: t.name } }) : null,
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

function chips() {
  const chip = (id, label) => h('button', { class: terminal === id ? 'chip active' : 'chip', attrs: { type: 'button' },
    dataset: { terminal: id } }, label);
  setChildren($('#ol-terminals'), terminals.length > 1 ? [chip('', 'All'), ...terminals.map((t) => chip(String(t.id), t.name))] : []);
}

function render() {
  if (terminal && !terminals.some((t) => String(t.id) === terminal)) terminal = '';
  chips();
  const shown = terminal ? terminals.filter((t) => String(t.id) === terminal) : terminals;
  setChildren($('#ol-cards'), shown.map(card));
  $('#ol-empty').hidden = shown.length > 0;
}

function wire() {
  if (wired) return;
  wired = true;
  $('#ol-terminals').addEventListener('click', (event) => {
    const button = event.target.closest('[data-terminal]');
    if (!button) return;
    terminal = button.dataset.terminal;
    render();
  });
  if (ME.multiPort) {
    const select = $('#ol-port');
    setChildren(select, portOptionEls({ all: true }));
    select.hidden = false;
    select.addEventListener('change', () => {
      port = select.value === 'ALL' ? '' : select.value;
      terminal = '';
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
    terminals = data.terminals;
    render();
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
  }
}

/** The Excel's query: the page's port and its All / one-terminal choice. */
function exportQuery() {
  return new URLSearchParams({ ...(port ? { port } : {}), ...(terminal ? { terminal } : {}) }).toString();
}

export const opLivePage = { load, exportQuery };
