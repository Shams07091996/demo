// The Accounts page dialog: a new account (username, names, role, temporary password) or an existing one (names,
// role, Turn off / Turn on). Superuser and staff accounts are shown read-only: they are changed in the admin pages.
import { api, mutate } from '../api.js';
import { headEl } from '../components.js';
import { h, optionEls } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { state } from '../state.js';
import { $ } from '../util.js';

const field = (label, control) => h('div', { class: 'field' }, h('label', null, label), control);

export function openAccountDialog(account, roles, onDone) {
  const locked = Boolean(account && (account.superuser || account.staff));
  state.ctx = { view: 'account', accountId: account?.id ?? null, active: account?.active ?? true, onDone };
  const input = (name, value, extra = {}) => h('input', { attrs: { name, maxlength: 150, autocomplete: 'off', ...extra },
    value: value ?? '', disabled: locked });
  const password = h('input', { attrs: { name: 'password', type: 'password', autocomplete: 'new-password' } });
  const show = h('input', { attrs: { type: 'checkbox' } });
  show.addEventListener('change', () => { password.type = show.checked ? 'text' : 'password'; });
  const btn = (cls, act, label) => h('button', { class: `btn ${cls}`, dataset: { act } }, label);
  openModal(
    headEl(account ? account.username : 'Add account'),
    h('div', { class: 'm-body', id: 'account-form' },
      account ? null : field('Username', input('username', '', { maxlength: 30 })),
      h('div', { class: 'row two' },
        field('First name', input('first_name', account?.first_name)),
        field('Last name', input('last_name', account?.last_name))),
      field('Role', h('select', { attrs: { name: 'role' }, disabled: locked },
        optionEls(roles, account?.role ?? 'readonly'))),
      account ? null : field('Temporary password', h('div', null, password,
        h('label', { class: 'tick' }, show, ' Show'))),
      locked ? h('div', { class: 'none' }, 'Changed in the admin pages.') : null),
    h('div', { class: 'm-foot' },
      account && !locked ? btn('ghost', 'account-toggle', account.active ? 'Turn off' : 'Turn on') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', locked ? 'Close' : 'Cancel'),
        locked ? null : ' ', locked ? null : btn('primary', 'account-save', 'Save'))),
  );
}

function readAccount(isNew) {
  const value = (name) => $(`#account-form [name="${name}"]`).value;
  const payload = { first_name: value('first_name'), last_name: value('last_name'), role: value('role') };
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
