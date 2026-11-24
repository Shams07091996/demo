// Customers as the other screens need them: loaded from the server (kept until a customer is saved), and the
// <option>s of a customer dropdown (active customers, always keeping the one already chosen).
import { api } from './api.js';
import { h } from './dom.js';

let list = null;

/** Every customer with its contacts, rates and linked ships (`force` reloads). */
export async function loadCustomers(force = false) {
  if (force || !list) list = (await api('/api/customers/')).customers;
  return list;
}

export const customers = () => list || [];
export const customerById = (id) => customers().find((c) => c.id === id) || null;

/** <option>s: "—" (none), the active customers, and `current` (an id) even when it is inactive. */
export function customerOptionEls(currentId, { none = '—' } = {}) {
  const shown = customers().filter((c) => c.active || c.id === currentId);
  return [h('option', { value: '' }, none),
    ...shown.map((c) => h('option', { value: c.id, selected: c.id === currentId }, c.name))];
}
