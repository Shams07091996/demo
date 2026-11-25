// The Accounts dialog's groups of "Can" and "Pages" ticks, and what one tick needs (twin of constants.PAGE_NEEDS /
// PERMISSION_NEEDS; sheet/tests_permissions.py checks every key is in exactly one group). Pure: tested in
// tools/parsing_test.js. Ticks are named "perm:<key>" / "page:<key>".

export const CAN_GROUPS = Object.freeze([
  ['Marine', ['vessels.edit', 'vessels.delete', 'services.edit', 'services.cancel', 'services.complete', 'documents',
    'closures.edit', 'bookings.edit', 'disposal.edit', 'customers.edit', 'accounting.close']],
  ['Operation', ['operation.edit', 'operation.delete', 'operation.master']],
  ['General', ['exports', 'money.edit', 'money.view', 'history.view', 'master.edit']],
]);

export const PAGE_GROUPS = Object.freeze([
  ['Marine', ['vessels', 'services', 'closures', 'ships']],
  ['Operation', ['op_vessels', 'op_live', 'op_analysis', 'op_charts']],
  ['Reports', ['dashboard', 'disposal', 'hotels', 'transport', 'calculations']],
  ['Master data', ['master', 'customers', 'rates', 'history']],
]);

export const NEEDS = Object.freeze({
  'page:calculations': 'perm:money.view',
  'page:rates': 'perm:money.view',
  'page:history': 'perm:history.view',
  'perm:history.view': 'perm:money.view',
  'perm:accounting.close': 'page:calculations',
  'perm:operation.edit': 'page:op_vessels',
  'perm:operation.delete': 'page:op_vessels',
  'perm:operation.master': 'page:op_vessels',
});

/** The ticks plus everything they need, all the way down. */
export function withNeeds(ids) {
  const out = new Set();
  const add = (id) => {
    if (!id || out.has(id)) return;
    out.add(id);
    add(NEEDS[id]);
  };
  ids.forEach(add);
  return out;
}

/** [[key, label]] from the server → [[group label, [[key, label]]]] in the server's order; empty groups dropped,
 * a key no group names goes to "Other" (so a new permission still shows). */
export function grouped(list, groups) {
  const known = new Set(groups.flatMap(([, keys]) => keys));
  const out = groups.map(([label, keys]) => [label, list.filter(([key]) => keys.includes(key))]);
  out.push(['Other', list.filter(([key]) => !known.has(key))]);
  return out.filter(([, items]) => items.length);
}
