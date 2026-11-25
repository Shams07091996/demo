// The Terminals page (Admins: every port; "Edit terminals and vessel list": their own ports): every terminal with
// its port, quay, cranes, berths and shipping lines. A row opens its dialog;
// "+ Add terminal" opens an empty one. Terminals are never deleted, only turned off.
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openTerminalDialog } from '../modals/terminal.js';
import { loadTerminals } from '../operation/shared.js';
import { $ } from '../util.js';

let list = [];
let ticket = 0;

function render() {
  const heads = ['Name', 'Code', 'Port', 'Quay (m)', 'Cranes', 'Berths', 'Shipping lines', 'State'];
  setChildren($('#tm-head'), h('tr', null, heads.map((t) => h('th', null, t))));
  const row = (t) => h('tr', { class: t.active ? 'clickable' : 'clickable inactive', dataset: { act: 'terminal-open', id: t.id } },
    h('td', null, t.name),
    h('td', null, t.code),
    h('td', null, t.port_label),
    h('td', null, String(t.quay_length)),
    h('td', null, String(t.cranes)),
    h('td', null, t.berths.join(' / ')),
    h('td', null, t.lines.length ? t.lines.join(', ') : 'All'),
    h('td', null, t.active ? 'On' : 'Off'));
  setChildren($('#tm-tbody'), list.map(row));
  $('#tm-empty').hidden = list.length > 0;
}

export const terminalsPage = {
  async load() {
    const mine = ++ticket;
    try {
      const fresh = await loadTerminals(true);
      if (mine !== ticket) return;
      list = fresh;
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(id) {
    const terminal = id ? list.find((t) => t.id === Number(id)) : null;
    if (id && !terminal) return;
    openTerminalDialog(terminal, () => terminalsPage.load());
  },
};
