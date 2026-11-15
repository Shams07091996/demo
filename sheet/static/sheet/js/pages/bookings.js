// The Hotels and Transport pages: one list module, configured twice. The server filters, sorts and pages
// (/api/hotels/, /api/transfers/); read-only users get no prices and no Add button.
import { api } from '../api.js';
import { ME, PORTS } from '../config.js';
import { setStatus } from '../feedback.js';
import { pagerHtml } from '../render/pager.js';
import { PAGE_SIZES, defaultRange } from '../state.js';
import { $, dmy, esc, fmt, fmtStamp } from '../util.js';

const PLACE = { airport: 'Airport', hotel: 'Hotel', port: 'Port' };
const SEARCH_DELAY_MS = 300;
const DATE_DELAY_MS = 400;
const typingYear = (iso) => iso && Number(iso.slice(0, 4)) < 1900;

const guestsCell = (guests) => guests.map((g) => esc(g.rank ? `${g.name} (${g.rank})` : g.name)).join('<br>');
const priceCell = (amount, currency) => (amount === null || amount === undefined ? '—' : `${esc(currency)} ${fmt(amount)}`);

const HOTEL_COLUMNS = [
  { title: 'Check-in', sort: 'check_in', cell: (b) => dmy(b.check_in) },
  { title: 'Nights', sort: 'nights', cell: (b) => b.nights },
  { title: 'Check-out', cell: (b) => dmy(b.check_out) },
  { title: 'Hotel', sort: 'hotel', cell: (b) => esc(b.hotel) },
  { title: 'Guests', sort: 'guest', cell: (b) => guestsCell(b.guests) },
  { title: 'Nationality', cell: (b) => [...new Set(b.guests.map((g) => g.nationality).filter(Boolean))].map(esc).join(', ') || '—' },
  { title: 'Vessel', sort: 'vessel', cell: (b) => esc(b.vessel.name) },
  { title: 'Price/night', price: true, cell: (b) => priceCell(b.price_per_night, b.currency) },
];

const TRANSFER_COLUMNS = [
  { title: 'Date & time', sort: 'at', cell: (b) => fmtStamp(b.at) },
  {
    title: 'From → To',
    sort: 'from_place',
    cell: (b) => {
      // "Airport (Borg El Arab) → Hotel (Hilton)": which airport / hotel / port, as the driver needs it.
      const name = { airport: b.airport, hotel: b.hotel, port: b.port_name };
      const place = (p) => (name[p] ? `${PLACE[p]} (${esc(name[p])})` : PLACE[p]);
      return `${place(b.from_place)} → ${place(b.to_place)}`;
    },
  },
  { title: 'Guests', sort: 'guest', cell: (b) => guestsCell(b.guests) },
  { title: 'Flight', cell: (b) => [...new Set(b.guests.map((g) => g.flight).filter(Boolean))].map(esc).join(', ') || '—' },
  { title: 'Vessel', sort: 'vessel', cell: (b) => esc(b.vessel.name) },
  { title: 'Price', price: true, cell: (b) => priceCell(b.price, b.currency) },
];

function savedSize(key) {
  try {
    const n = Number(localStorage.getItem(key));
    return PAGE_SIZES.includes(n) ? n : 50;
  } catch {
    return 50;
  }
}

function createBookingsPage({ kind, prefix, noun, columns, defaultSort }) {
  const sizeKey = `sheet.${kind}.pageSize`;
  const id = (name) => `#${prefix}-${name}`;
  const cols = columns.filter((c) => !c.price || ME.canEdit);
  const filter = { ...defaultRange(), q: '', port: 'ALL', sort: defaultSort, dir: 'asc', page: 1, pageSize: savedSize(sizeKey) };
  let list = { bookings: [], count: 0, pages: 1, page: 1 };
  let ticket = 0;
  let wired = false;

  function params() {
    const values = {
      from: filter.from, to: filter.to, q: filter.q.trim(), port: filter.port === 'ALL' ? '' : filter.port,
      sort: filter.sort, dir: filter.dir, page: filter.page, page_size: filter.pageSize,
    };
    return new URLSearchParams(Object.entries(values).filter(([, v]) => v !== '' && v !== null && v !== undefined));
  }

  function renderHead() {
    $(id('head')).innerHTML = `<tr>${cols.map((c) => {
      const arrow = c.sort ? ` <span class="arrow">${filter.sort === c.sort ? (filter.dir === 'asc' ? '↑' : '↓') : '↕'}</span>` : '';
      return `<th ${c.sort ? `data-bsort="${c.sort}"` : ''}>${esc(c.title)}${arrow}</th>`;
    }).join('')}</tr>`;
  }

  function render() {
    renderHead();
    const rowAttrs = (b) => (ME.canEdit ? `data-act="booking-open" data-kind="${kind}" data-id="${b.id}" class="clickable"` : '');
    $(id('tbody')).innerHTML = list.bookings
      .map((b) => `<tr ${rowAttrs(b)}>${cols.map((c) => `<td>${c.cell(b)}</td>`).join('')}</tr>`).join('');
    $(id('empty')).style.display = list.bookings.length ? 'none' : 'block';
    $(id('pager')).innerHTML = pagerHtml({
      count: list.count, pages: list.pages, page: list.page, size: filter.pageSize, noun, sizeId: `${prefix}-page-size`,
      prev: `data-act="booking-page" data-kind="${kind}" data-step="-1"`,
      next: `data-act="booking-page" data-kind="${kind}" data-step="1"`,
    });
    const from = $(id('from'));
    const to = $(id('to'));
    if (document.activeElement !== from) from.value = filter.from;
    if (document.activeElement !== to) to.value = filter.to;
    from.max = filter.to;
    to.min = filter.from;
  }

  async function load() {
    wire();
    const mine = ++ticket;
    let data;
    try {
      data = await api(`/api/${kind}/?${params()}`);
    } catch (error) {
      if (mine === ticket) setStatus('error', error.message);
      return;
    }
    if (mine !== ticket) return; // a newer request is on its way
    if (!data.bookings.length && filter.page > data.pages) {
      filter.page = data.pages; // the last row of the last page went away: show the new last page
      return load();
    }
    list = data;
    render();
  }

  function setFilter(patch) {
    Object.assign(filter, patch);
    if (!('page' in patch)) filter.page = 1;
    if ('pageSize' in patch) {
      try {
        localStorage.setItem(sizeKey, String(patch.pageSize));
      } catch {
        // not remembered
      }
    }
    return load();
  }

  /** Hook up this page's own controls once, the first time it is shown. */
  function wire() {
    if (wired) return;
    wired = true;
    $(id('add')).style.display = ME.canEdit ? '' : 'none';
    if (ME.seesAll) {
      const select = $(id('port'));
      select.innerHTML = `<option value="ALL">🌐 All ports</option>${PORTS.map((p) => `<option value="${p.key}">${esc(p.label)}</option>`).join('')}`;
      select.style.display = '';
      select.addEventListener('change', () => setFilter({ port: select.value }));
    }
    let searchTimer;
    $(id('search')).addEventListener('input', (event) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => setFilter({ q: event.target.value }), SEARCH_DELAY_MS);
    });
    let dateTimer;
    const onDate = () => {
      clearTimeout(dateTimer);
      dateTimer = setTimeout(() => {
        const from = $(id('from')).value;
        const to = $(id('to')).value;
        if (typingYear(from) || typingYear(to)) return;
        if (from && to && from > to) {
          setStatus('error', 'From must be on or before To.');
          return;
        }
        if (from !== filter.from || to !== filter.to) setFilter({ from, to });
      }, DATE_DELAY_MS);
    };
    $(id('from')).addEventListener('change', onDate);
    $(id('to')).addEventListener('change', onDate);
    $(id('clear')).addEventListener('click', () => setFilter({ from: '', to: '' }));
    $(id('head')).addEventListener('click', (event) => {
      const th = event.target.closest('[data-bsort]');
      if (!th) return;
      const sort = th.dataset.bsort;
      setFilter({ sort, dir: filter.sort === sort && filter.dir === 'asc' ? 'desc' : 'asc' });
    });
    $(id('pager')).addEventListener('change', (event) => {
      if (event.target.id === `${prefix}-page-size`) setFilter({ pageSize: Number(event.target.value) });
    });
  }

  return {
    kind,
    load,
    setFilter,
    step: (n) => setFilter({ page: Math.min(Math.max(1, filter.page + n), list.pages) }),
  };
}

export const hotelsPage = createBookingsPage({
  kind: 'hotels', prefix: 'h', noun: 'hotel stays', columns: HOTEL_COLUMNS, defaultSort: 'check_in',
});
export const transportPage = createBookingsPage({
  kind: 'transfers', prefix: 't', noun: 'transfers', columns: TRANSFER_COLUMNS, defaultSort: 'at',
});
export const bookingsPage = (kind) => (kind === 'hotels' ? hotelsPage : transportPage);
