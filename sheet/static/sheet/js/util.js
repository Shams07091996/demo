// Small pure helpers: DOM lookups, number / date formatting. (No escaping: screens are built with dom.js.)

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

/** The first `max` items and how many more there are (the alerts banner caps its missing-agent rows). */
export const limitRows = (list, max) => ({ shown: list.slice(0, max), more: Math.max(0, list.length - max) });

export const num = (x) => {
  const n = parseFloat(x);
  return Number.isFinite(n) ? n : 0;
};

export const fmt = (n) =>
  Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtShort = (n) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : Number(n || 0).toFixed(0);

export const sign = (n) => (n >= 0 ? '+' : '') + fmt(n);

/** '2026-11-13' -> '13.11.2026' */
export const dmy = (iso) => (iso ? iso.split('-').reverse().join('.') : '');

/** Group an operator name into the ARK / MSK / OTH buckets used by the colours and filters. */
export const oprClass = (opr) => {
  const upper = (opr || '').trim().toUpperCase();
  return upper === 'ARK' ? 'ARK' : upper === 'MSK' ? 'MSK' : 'OTH';
};

/** Local-time YYYY-MM-DD (toISOString would shift the day around midnight). */
export const localISO = (date = new Date()) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

export const today = () => localISO();

export const dayISO = (offsetDays) => {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return localISO(date);
};

/** Collect {name: value} from every [name] field inside root. */
export const formValues = (root) => {
  const values = {};
  $$('[name]', root).forEach((el) => { values[el.name] = el.value; });
  return values;
};

/** Hours -> "1d 3h", "5h 20m", "45m"; missing -> "—". */
export const fmtDuration = (hours) => {
  if (hours === null || hours === undefined) return '—';
  const minutes = Math.round(hours * 60);
  const days = Math.floor(minutes / 1440);
  const hrs = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  return [days && `${days}d`, hrs && `${hrs}h`, (mins || (!days && !hrs)) && `${mins}m`].filter(Boolean).join(' ');
};

/** '2026-11-13T08:30' -> '13.11.2026 08:30' */
export const fmtStamp = (local) => {
  if (!local) return '';
  const [day, clock] = local.split('T');
  return `${dmy(day)} ${clock}`;
};

/** Now, as the value of an <input type="datetime-local">. */
export const nowLocalInput = () => {
  const d = new Date();
  return `${localISO(d)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

// Mirrors constants.DELAY_LIMIT: berthing more than 2 hours after arrival needs a delay reason (the server decides).
const DELAY_LIMIT_MS = 2 * 60 * 60 * 1000;
// Read the wall-clock times as UTC so a clock change in the browser's own zone never shifts the gap.
const wallClockMs = (local) => Date.parse(`${local}:00Z`);

/** Two datetime-local values ('2026-11-13T08:30'): did the vessel berth more than 2 hours after it arrived? */
export const isDelayed = (arrival, berthing) => {
  if (!arrival || !berthing) return false;
  const gap = wallClockMs(berthing) - wallClockMs(arrival);
  return Number.isFinite(gap) && gap > DELAY_LIMIT_MS;
};
