// The Ports page (Admins only): every port with its key, On / Off, and how many vessels and Users it has.
// A row opens its dialog (rename, Turn off / on); "+ Add port" opens an empty one. Ports are never deleted.
import { api } from '../api.js';
import { PORT_LABEL, PORTS } from '../config.js';
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openPortDialog } from '../modals/port.js';
import { $ } from '../util.js';

let data = { ports: [] };
let ticket = 0;

// After a save: every dropdown and label in the open page reads the new names (PORTS / PORT_LABEL are shared).
function refreshPorts(rows) {
  PORTS.splice(0, PORTS.length, ...rows.map((p) => ({ key: p.key, label: p.name, active: p.active })));
  Object.keys(PORT_LABEL).forEach((key) => { delete PORT_LABEL[key]; });
  rows.forEach((p) => { PORT_LABEL[p.key] = p.name; });
}

function render() {
  const heads = ['Name', 'Key', 'State', 'Vessels', 'Users'];
  setChildren($('#pt-head'), h('tr', null, heads.map((t) => h('th', null, t))));
  const row = (p) => h('tr', { class: p.active ? 'clickable' : 'clickable inactive', dataset: { act: 'port-open', key: p.key } },
    h('td', null, p.name),
    h('td', null, p.key),
    h('td', null, p.active ? 'On' : 'Off'),
    h('td', null, String(p.vessels)),
    h('td', null, String(p.users)));
  setChildren($('#pt-tbody'), data.ports.map(row));
  $('#pt-empty').hidden = data.ports.length > 0;
}

export const portsPage = {
  async load() {
    const mine = ++ticket;
    try {
      const fresh = await api('/api/ports/');
      if (mine !== ticket) return;
      data = fresh;
      refreshPorts(data.ports);
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(key) {
    const port = key ? data.ports.find((p) => p.key === key) : null;
    if (key && !port) return;
    openPortDialog(port, () => portsPage.load());
  },
};
