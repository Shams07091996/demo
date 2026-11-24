// The "Quick add" bar above the vessel table. The name box searches the ship list (js/shipPicker.js); a vessel is
// always added for a ship, so with none picked the New ship panel opens under the bar.
import { api, mutate } from './api.js';
import { portOptionEls } from './components.js';
import { ME } from './config.js';
import { afterVesselSaved } from './data.js';
import { h, setChildren } from './dom.js';
import { newShipPanel } from './modals/ship.js';
import { openVessel } from './modals/vessel.js';
import { attachShipPicker } from './shipPicker.js';
import { $, today } from './util.js';

let picker = null;

/** Put the ship's OPR in the OPR box (adding it as a choice when this port's list doesn't have it). */
function showOpr(opr) {
  const select = $('#qa-opr');
  if (!opr) return;
  if (![...select.options].some((o) => o.value === opr)) select.append(h('option', { value: opr }, opr));
  select.value = opr;
}

function closeNewShip() {
  const box = $('#qa-newship');
  box.hidden = true;
  setChildren(box);
}

async function openNewShip(name) {
  const box = $('#qa-newship');
  const port = ME.isAdmin ? $('#qa-port').value || null : ME.port;
  const panel = await newShipPanel({
    name,
    port,
    onSaved: (ship) => { closeNewShip(); picker.set(ship); showOpr(ship.opr); $('#qa-name').focus(); },
    onCancel: closeNewShip,
  });
  setChildren(box, panel);
  box.hidden = false;
  panel.querySelector('[name="imo"]').focus();
}

async function addVessel({ thenOpen }) {
  const nameInput = $('#qa-name');
  const name = nameInput.value.trim();
  if (!name) {
    nameInput.focus();
    return;
  }
  const ship = picker.picked();
  if (!ship) {
    await openNewShip(name.toUpperCase());
    return;
  }
  const payload = {
    name,
    ship_id: ship.id,
    date: $('#qa-date').value || today(),
    opr: $('#qa-opr').value,
    poc: $('#qa-poc').value,
    arrival_agent: $('#qa-agent').value, // the sailing agent stays empty until someone chooses it
  };
  if (ME.isAdmin) payload.port = $('#qa-port').value;

  const vessel = await mutate(() => api('/api/vessels/', 'POST', payload));
  nameInput.value = '';
  picker.set(null);
  await afterVesselSaved(vessel);
  if (thenOpen) openVessel(vessel.id);
}

export function setupQuickAdd() {
  if (!ME.canEdit) {
    $('#quickAdd').hidden = true;
    return;
  }
  $('#qa-date').value = today();
  const nameInput = $('#qa-name');
  nameInput.addEventListener('input', (e) => { e.target.value = e.target.value.toUpperCase(); });
  picker = attachShipPicker(nameInput, {
    onPick: (ship) => { closeNewShip(); showOpr(ship.opr); },
    onNew: (name) => { openNewShip(name).catch(() => {}); },
    onEnter: () => { addVessel({ thenOpen: false }).catch(() => {}); },
  });
  $('#qa-add').addEventListener('click', () => addVessel({ thenOpen: false }).catch(() => {}));
  $('#qa-edit').addEventListener('click', () => addVessel({ thenOpen: true }).catch(() => {}));

  if (ME.isAdmin) {
    const select = $('#qa-port');
    // No port assumed: an admin picks one (the header's port when one is chosen there).
    setChildren(select, h('option', { value: '' }, 'Port'), portOptionEls());
    select.hidden = false;
  }
}
