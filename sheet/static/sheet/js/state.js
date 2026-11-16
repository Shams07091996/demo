// The one place that holds mutable application state.
import { localISO } from './util.js';

export const PAGE_SIZES = [10, 25, 50, 100];
const PAGE_SIZE_KEY = 'sheet.pageSize';

/** The current calendar month as {from, to} (YYYY-MM-DD, local date). */
export function defaultRange(now = new Date()) {
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return { from: localISO(first), to: localISO(last) };
}

function savedPageSize() {
  try {
    const saved = Number(localStorage.getItem(PAGE_SIZE_KEY));
    return PAGE_SIZES.includes(saved) ? saved : 50;
  } catch {
    return 50;
  }
}

export function savePageSize(size) {
  try {
    localStorage.setItem(PAGE_SIZE_KEY, String(size));
  } catch {
    // private window / blocked storage: the choice just isn't remembered
  }
}

export const state = {
  // What the vessel list (and Dashboard) asks the server for. `port` is the admin / read-only port selector.
  filter: {
    ...defaultRange(), q: '', bucket: 'ALL', port: 'ALL', sort: 'date', dir: 'desc', page: 1, pageSize: savedPageSize(),
  },
  vessels: [],        // the current page only
  list: { count: 0, pages: 1, page: 1, totals: null },
  cache: new Map(),   // every vessel seen so far, by id (dialogs read from here)
  alerts: { today: [], tomorrow: [] },
  dashboard: { count: 0, oprs: [] },
  options: [],        // OPR / POC / Agent master data
  rates: [],          // monthly USD -> EGP rates
  page: 'vessels',
  ctx: { view: null, vesselId: null },   // what the modal is currently showing
  crew: { onSigners: [], offSigners: [] }, // crew members being edited in the service form
};

/** The current filter as query parameters (empty values and "ALL" are left out). `extra` overrides. */
export function filterParams(extra = {}) {
  const f = state.filter;
  const values = {
    from: f.from,
    to: f.to,
    q: f.q.trim(),
    bucket: f.bucket === 'ALL' ? '' : f.bucket,
    port: f.port === 'ALL' ? '' : f.port,
    sort: f.sort,
    dir: f.dir,
    page: f.page,
    page_size: f.pageSize,
    ...extra,
  };
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) params.set(key, value);
  });
  return params;
}

export const getVessel = (id) => state.cache.get(id);

export function rememberVessels(vessels) {
  vessels.forEach((v) => state.cache.set(v.id, v));
}

/** Is an ISO date inside the current From–To range? (an empty end is open) */
export const inRange = (iso) => (!state.filter.from || iso >= state.filter.from) && (!state.filter.to || iso <= state.filter.to);

/** Master-data values of a list; with `port`, only that port's values and the All-ports ones (port ''). */
export const optionValues = (kind, port = null) => [...new Set(state.options
  .filter((o) => o.kind === kind && (port === null || !o.port || o.port === port))
  .map((o) => o.value))];

export const resetContext = () => { state.ctx = { view: null, vesselId: null }; };
