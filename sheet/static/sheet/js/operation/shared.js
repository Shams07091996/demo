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
