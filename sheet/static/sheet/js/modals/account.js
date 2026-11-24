// The Accounts page dialog: a new account (username, names, home port, extra ports, temporary password) or an
// existing one (names, ports, Turn off / Turn on). Superuser and staff accounts are shown read-only: they are
// changed in the admin pages. Only ports that are on are offered, plus any the account already has.
import { api, mutate } from '../api.js';
import { headEl } from '../components.js';
import { h, optionEls } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { state } from '../state.js';
import { $, $$ } from '../util.js';

const field = (label, control) => h('div', { class: 'field' }, h('label', null, label), control);

// The home port's tick is always on (the home port is one of the account's ports) and can't be untaken.
function syncHomeTick() {
  const home = $('#account-form [name="home_port"]')?.value;
  $$('#account-form [data-port]').forEach((box) => {
    const isHome = box.dataset.port === home;
    if (isHome) box.checked = true;
    box.disabled = isHome || box.dataset.locked === '1';
  });
}

export function openAccountDialog(account, ports, onDone) {
  const locked = Boolean(account && (account.superuser || account.staff));
  state.ctx = { view: 'account', accountId: account?.id ?? null, active: account?.active ?? true, onDone };
  const input = (name, value, extra = {}) => h('input', { attrs: { name, maxlength: 150, autocomplete: 'off', ...extra },
    value: value ?? '', disabled: locked });
  const password = h('input', { attrs: { name: 'password', type: 'password', autocomplete: 'new-password' } });
  const show = h('input', { attrs: { type: 'checkbox' } });
  show.addEventListener('change', () => { password.type = show.checked ? 'text' : 'password'; });
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  const has = new Set(account?.ports ?? []);
  const offered = ports.filter(([key, , active]) => active || has.has(key));
  const home = h('select', { attrs: { name: 'home_port' }, disabled: locked },
    optionEls(offered.map(([key, label]) => [key, label]), account?.home_port || offered[0]?.[0] || ''));
  home.addEventListener('change', syncHomeTick);
  const ticks = offered.map(([key, label]) => h('label', { class: 'tick' },
    h('input', { attrs: { type: 'checkbox' }, dataset: { port: key, locked: locked ? '1' : '0' }, checked: has.has(key) }),
    ` ${label}`));
  openModal(
    headEl(account ? account.username : 'Add account'),
    h('div', { class: 'm-body', id: 'account-form' },
      account ? null : field('Username', input('username', '', { maxlength: 30 })),
      h('div', { class: 'row two' },
        field('First name', input('first_name', account?.first_name)),
        field('Last name', input('last_name', account?.last_name))),
      locked ? null : field('Home port', home),
      locked ? null : field('Extra ports', h('div', { class: 'ticks' }, ticks)),
      account ? null : field('Temporary password', h('div', null, password,
        h('label', { class: 'tick' }, show, ' Show'))),
      locked ? h('div', { class: 'none' }, 'Changed in the admin pages.') : null),
    h('div', { class: 'm-foot' },
      account && !locked ? btn('ghost', 'account-toggle', account.active ? 'Turn off' : 'Turn on') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', locked ? 'Close' : 'Cancel'),
        locked ? null : ' ', locked ? null : btn('primary', 'account-save', 'Save'))),
  );
  syncHomeTick();
}

function readAccount(isNew) {
  const value = (name) => $(`#account-form [name="${name}"]`).value;
  const ports = $$('#account-form [data-port]').filter((box) => box.checked).map((box) => box.dataset.port);
  const payload = { first_name: value('first_name'), last_name: value('last_name'), home_port: value('home_port'),
    ports };
  if (isNew) {
    payload.username = value('username');
    payload.password = value('password');
  }
  return payload;
}

let saving = false;

async function send(payload) {
  const { accountId, onDone } = state.ctx;
  if (saving) return;
  saving = true;
  try {
    await mutate(() => (accountId ? api(`/api/accounts/${accountId}/`, 'PUT', payload)
      : api('/api/accounts/', 'POST', payload)));
  } catch {
    return; // mutate showed the server's message
  } finally {
    saving = false;
  }
  closeModal();
  await onDone?.();
}

export function saveAccountDialog() {
  if (state.ctx.view !== 'account') return undefined;
  return send(readAccount(!state.ctx.accountId));
}

export function toggleAccount() {
  if (state.ctx.view !== 'account' || !state.ctx.accountId) return undefined;
  return send({ active: !state.ctx.active });
}
