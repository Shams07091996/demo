// The Berthing windows page (Admins: every port; "Edit terminals and vessel list": their own ports): each line's
// weekly berthing windows at each terminal. A row opens its dialog; "+ Add window" an empty one.
import { api } from '../api.js';
import { ME } from '../config.js';
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openWindowDialog } from '../modals/window.js';
import { loadTerminals, terminalOptionEls, windowText } from '../operation/shared.js';
import { $ } from '../util.js';

let list = [];
let terminals = [];
let ticket = 0;
let wired = false;

function render() {
  const shown = $('#wn-terminal').value ? list.filter((w) => w.terminal === Number($('#wn-terminal').value)) : list;
  const heads = ['Terminal', 'Line', 'Window', 'Length'];
  setChildren($('#wn-head'), h('tr', null, heads.map((t) => h('th', null, t))));
  setChildren($('#wn-tbody'), shown.map((w) => h('tr', { class: 'clickable', dataset: { act: 'window-open', id: w.id } },
    h('td', null, w.terminal_name, ME.multiPort ? h('span', { class: 'none' }, ` · ${w.port_label}`) : null),
    h('td', null, w.line),
    h('td', null, windowText(w)),
    h('td', null, `${w.hours} h`))));
  $('#wn-empty').hidden = shown.length > 0;
}

function wire() {
  if (wired) return;
  wired = true;
  $('#wn-terminal').addEventListener('change', render);
}

export const windowsPage = {
  async load() {
    wire();
    const mine = ++ticket;
    try {
      const [fresh, terms] = await Promise.all([api('/api/operation/windows/'), loadTerminals(true)]);
      if (mine !== ticket) return;
      list = fresh.windows;
      terminals = terms;
      const chosen = $('#wn-terminal').value;
      setChildren($('#wn-terminal'), terminalOptionEls(terminals, chosen));
      $('#wn-terminal').value = terminals.some((t) => String(t.id) === chosen) ? chosen : '';
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(id) {
    const found = id ? list.find((w) => w.id === Number(id)) : null;
    if (id && !found) return;
    openWindowDialog(found, terminals, () => windowsPage.load());
  },
};
