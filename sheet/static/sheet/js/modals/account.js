// The Accounts page dialog: a new account (username, names, home port, extra ports, pages, permissions, temporary
// password) or an existing one (the same without username / password, plus Turn off / Turn on). Superuser and staff
// accounts are shown read-only: they are changed in the admin pages. Only ports that are on are offered, plus any
// the account already has. A template only fills in the Pages / Can ticks; it is not saved.
import { api, mutate } from '../api.js';
import { headEl } from '../components.js';
import { h, optionEls } from '../dom.js';
import { closeModal, openModal } from '../modal.js';
import { state } from '../state.js';
import { $, $$ } from '../util.js';

const field = (label, control) => h('div', { class: 'field' }, h('label', null, label), control);

// The home port's tick is always on (the home port is one of the account's ports) and can't be untaken. A tick
// that was only on because its port was the home port goes off again when another home port is chosen.
function syncHomeTick() {
  const home = $('#account-form [name="home_port"]')?.value;
  $$('#account-form [data-port]').forEach((box) => {
    const isHome = box.dataset.port === home;
    if (isHome && !box.checked) {
      box.checked = true;
      box.dataset.auto = '1';
    } else if (!isHome && box.dataset.auto === '1') {
      box.checked = false;
      delete box.dataset.auto;
    }
    box.disabled = isHome || box.dataset.locked === '1';
  });
}

// Ticks that need another one are disabled (and unticked) without it: Calculations / Exchange rates and History
// need See money; Close / reopen lines needs the Calculations page. Vessels is always on; the History page follows
// the History permission (the server stores it the same way).
const box = (attr, key) => $(`#account-form [data-${attr}="${key}"]`);
function syncNeeds() {
  if (!box('perm', 'money.view')) return;
  const set = (attr, key, enabled, forced) => {
    const el = box(attr, key);
    if (!el) return;
    el.disabled = !enabled;
    if (forced !== undefined) el.checked = forced;
    else if (!enabled) el.checked = false;
  };
  const money = box('perm', 'money.view').checked;
  set('tick-page', 'calculations', money);
  set('tick-page', 'rates', money);
  set('perm', 'history.view', money);
  set('perm', 'accounting.close', box('tick-page', 'calculations').checked);
  set('tick-page', 'vessels', false, true);
  set('tick-page', 'history', false, box('perm', 'history.view').checked);
}

function applyTemplate(templates, key) {
  const template = templates.find(([k]) => k === key);
  if (!template) return;
  const [, , permissions, pages] = template;
  $$('#account-form [data-perm]').forEach((el) => { el.checked = permissions.includes(el.dataset.perm); });
  $$('#account-form [data-tick-page]').forEach((el) => { el.checked = pages.includes(el.dataset.tickPage); });
  syncNeeds();
}

function ticksEl(list, attr, chosen) {
  return h('div', { class: 'ticks' }, list.map(([key, label]) => {
    const tick = h('input', { attrs: { type: 'checkbox' }, dataset: { [attr]: key }, checked: chosen.has(key) });
    tick.addEventListener('change', syncNeeds);
    return h('label', { class: 'tick' }, tick, ` ${label}`);
  }));
}

export function openAccountDialog(account, lists, onDone) {
  const { ports, permissions = [], pages = [], templates = [] } = lists;
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
  const template = h('select', { attrs: { name: 'template', 'aria-label': 'Template' } },
    optionEls([['', 'Custom'], ...templates.map(([key, label]) => [key, label])], ''));
  template.addEventListener('change', () => applyTemplate(templates, template.value));
  const pageTicks = ticksEl(pages, 'tickPage', new Set(account?.pages ?? ['vessels']));
  const permTicks = ticksEl(permissions, 'perm', new Set(account?.permissions ?? []));
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
      locked ? null : field('Template', template),
      locked ? null : field('Pages', pageTicks),
      locked ? null : field('Can', permTicks),
      account ? null : field('Temporary password', h('div', null, password,
        h('label', { class: 'tick' }, show, ' Show'))),
      locked ? h('div', { class: 'none' }, 'Changed in the admin pages.') : null),
    h('div', { class: 'm-foot' },
      account && !locked ? btn('ghost', 'account-toggle', account.active ? 'Turn off' : 'Turn on') : h('span'),
      h('div', { class: 'right' }, btn('ghost', 'close', locked ? 'Close' : 'Cancel'),
        locked ? null : ' ', locked ? null : btn('primary', 'account-save', 'Save'))),
  );
  syncHomeTick();
  syncNeeds();
}

function readAccount(isNew) {
  const value = (name) => $(`#account-form [name="${name}"]`).value;
  const ports = $$('#account-form [data-port]').filter((box) => box.checked).map((box) => box.dataset.port);
  const ticked = (attr, key) => $$(`#account-form [data-${attr}]`).filter((el) => el.checked)
    .map((el) => el.dataset[key]);
  const payload = { first_name: value('first_name'), last_name: value('last_name'), home_port: value('home_port'),
    ports, permissions: ticked('perm', 'perm'), pages: ticked('tick-page', 'tickPage') };
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
