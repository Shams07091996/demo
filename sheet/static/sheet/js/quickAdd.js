// The "Quick add" bar above the vessel table.
import { api, mutate } from './api.js';
import { ME, PORTS } from './config.js';
import { afterVesselSaved } from './data.js';
import { openVessel } from './modals/vessel.js';
import { $, today } from './util.js';

async function addVessel({ thenOpen }) {
  const nameInput = $('#qa-name');
  const name = nameInput.value.trim();
  if (!name) {
    nameInput.focus();
    return;
  }
  const payload = {
    name,
    date: $('#qa-date').value || today(),
    opr: $('#qa-opr').value,
    poc: $('#qa-poc').value,
    agent: $('#qa-agent').value,
  };
  if (ME.isAdmin) payload.port = $('#qa-port').value;

  const vessel = await mutate(() => api('/api/vessels/', 'POST', payload));
  nameInput.value = '';
  await afterVesselSaved(vessel);
  if (thenOpen) openVessel(vessel.id);
}

export function setupQuickAdd() {
  if (!ME.canEdit) {
    $('#quickAdd').style.display = 'none';
    return;
  }
  $('#qa-date').value = today();
  $('#qa-name').addEventListener('input', (e) => { e.target.value = e.target.value.toUpperCase(); });
  $('#qa-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') addVessel({ thenOpen: false }).catch(() => {}); });
  $('#qa-add').addEventListener('click', () => addVessel({ thenOpen: false }).catch(() => {}));
  $('#qa-edit').addEventListener('click', () => addVessel({ thenOpen: true }).catch(() => {}));

  if (ME.isAdmin) {
    const select = $('#qa-port');
    select.innerHTML = PORTS.map((p) => `<option value="${p.key}">${p.label}</option>`).join('');
    select.style.display = '';
  }
}
