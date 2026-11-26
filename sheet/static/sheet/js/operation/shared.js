// The Operation pages' shared bits: the terminals of the person's ports (cached), the Analysis / Charts filter,
// and small formatters. The server works out every figure; these only show them.
import { api } from '../api.js';
import { h } from '../dom.js';
import { fmtStamp } from '../util.js';

let terminals = null;

/** The terminals of the person's ports ({id, name, code, port, port_label, quay_length, cranes, berths, active}). */
export async function loadTerminals(fresh = false) {
  if (!terminals || fresh) terminals = (await api('/api/operation/terminals/')).terminals;
  return terminals;
}

let listed = null;

/** The vessel list ({id, name, loa}), all ports; the visit dialog fills the LOA from it. */
export async function loadListed(fresh = false) {
  if (!listed || fresh) listed = (await api('/api/operation/vessels/')).vessels;
  return listed;
}

/** A shipping line's <option>s for a visit at `terminal`: its own lines when it has any, else its port's list. */
export const terminalLines = (terminal, values) => (terminal?.lines?.length ? terminal.lines : values);

/** Berthing windows: Mon = 0 … Sun = 6, shown "Tue 06:00 → Wed 18:00". */
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const windowText = (w) => `${DAYS[w.start_day]} ${w.start_time} → ${DAYS[w.end_day]} ${w.end_time}`;

export const terminalById = (id) => (terminals || []).find((t) => t.id === Number(id)) || null;

/** Analysis reports and Report charts share one filter (and one server response). */
export const opFilter = { port: '', terminal: '', berth: '', from: '', to: '', line: '' };

export const opQuery = () => new URLSearchParams(Object.entries(opFilter).filter(([, v]) => v));

export const STATUS_CLASS = { Planned: 'st-scheduled', Working: 'st-operating', Completed: 'st-ops_finished' };

export const statusEl = (status) => h('span', { class: `status-chip ${STATUS_CLASS[status] || ''}` }, status);

/** A figure from the server: a dash when there is none. */
export const figure = (value) => (value === null || value === undefined || value === '' ? '—' : String(value));

export const stamp = (local) => (local ? fmtStamp(local) : '—');

/** <option>s of the terminals: "All terminals" first when `all`. */
export const terminalOptionEls = (list, selected, all = 'All terminals') => [
  all ? h('option', { value: '' }, all) : null,
  ...list.map((t) => h('option', { value: t.id, selected: String(t.id) === String(selected) }, t.name)),
].filter(Boolean);
