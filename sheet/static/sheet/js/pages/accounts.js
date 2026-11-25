// The Accounts page (Admins only): every account with its ports, two-step state, last sign-in and On / Off.
// A row opens its dialog; "+ Add account" opens an empty one. The server decides everything (/api/accounts/).
import { api } from '../api.js';
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openAccountDialog } from '../modals/account.js';
import { $, fmtStamp } from '../util.js';

let data = { accounts: [], ports: [], permissions: [], pages: [], templates: [] };
let ticket = 0;

// "Alexandria (home), Damietta"; an Admin (superuser) works in every port.
export const portsLabel = (account, ports) => {
  if (account.superuser) return 'Admin · all ports';
  const name = Object.fromEntries(ports.map(([key, label]) => [key, label]));
  const list = account.ports.map((key) => (key === account.home_port ? `${name[key] || key} (home)` : name[key] || key));
  const label = list.join(', ') || 'No port';
  return account.staff ? `${label} · Staff` : label;
};

export function twoStepLabel(account) {
  if (account.two_step === 'set_up') return 'Set up';
  if (account.two_step === 'exempt') return 'Exception';
  if (account.two_step === 'waiting') return `Waiting — until ${fmtStamp(account.setup_until)}`;
  return 'Setup expired';
}

function render() {
  const heads = ['Username', 'Name', 'Ports', 'Can', 'Two-step', 'Last sign-in', 'State'];
  setChildren($('#ac-head'), h('tr', null, heads.map((t) => h('th', null, t))));
  const row = (a) => h('tr', { class: a.active ? 'clickable' : 'clickable inactive', dataset: { act: 'account-open', id: a.id } },
    h('td', null, a.username),
    h('td', null, [a.first_name, a.last_name].filter(Boolean).join(' ') || '—'),
    h('td', null, portsLabel(a, data.ports)),
    h('td', null, a.superuser ? 'All' : `${a.permissions.length} of ${data.permissions.length}`),
    h('td', null, twoStepLabel(a)),
    h('td', null, a.last_login ? fmtStamp(a.last_login) : '—'),
    h('td', null, a.active ? 'On' : 'Off'));
  setChildren($('#ac-tbody'), data.accounts.map(row));
  $('#ac-empty').hidden = data.accounts.length > 0;
}

export const accountsPage = {
  async load() {
    const mine = ++ticket;
    try {
      const fresh = await api('/api/accounts/');
      if (mine !== ticket) return;
      data = fresh;
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(id) {
    const account = id ? data.accounts.find((a) => a.id === id) : null;
    if (id && !account) return;
    openAccountDialog(account, data, () => accountsPage.load());
  },
};
