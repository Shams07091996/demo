// The vessel list (Operation): each vessel's fixed LOA, shared by all ports. Everyone with Vessel Data reads it (the
// visit dialog fills the LOA from it); "Edit terminals and vessel list" adds and changes entries; Admins delete.
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openListedDialog } from '../modals/listedVessel.js';
import { loadListed } from '../operation/shared.js';
import { $ } from '../util.js';

let list = [];
let ticket = 0;
let wired = false;

function render() {
  const q = $('#vl-q').value.trim().toUpperCase();
  const shown = q ? list.filter((v) => v.name.includes(q)) : list;
  setChildren($('#vl-head'), h('tr', null, h('th', null, 'Vessel'), h('th', null, 'LOA (m)')));
  setChildren($('#vl-tbody'), shown.map((v) => h('tr', { class: 'clickable', dataset: { act: 'vl-open', id: v.id } },
    h('td', null, v.name), h('td', null, String(v.loa)))));
  $('#vl-empty').hidden = shown.length > 0;
}

export const vesselListPage = {
  async load() {
    if (!wired) {
      wired = true;
      $('#vl-q').addEventListener('input', () => render());
    }
    const mine = ++ticket;
    try {
      const fresh = await loadListed(true);
      if (mine !== ticket) return;
      list = fresh;
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(id) {
    const vessel = id ? list.find((v) => v.id === Number(id)) : null;
    if (id && !vessel) return;
    openListedDialog(vessel, () => vesselListPage.load());
  },
};
