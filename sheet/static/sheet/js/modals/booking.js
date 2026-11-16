// The add / edit dialog for a hotel stay or a transfer: pick the vessel, tick guests from its crew change (or add
// other guests), fill in the booking and an optional price. The server checks everything again.
import { api, mutate } from '../api.js';
import { head, optionChoices } from '../components.js';
import { el } from '../config.js';
import { setStatus } from '../feedback.js';
import { closeModal, openModal } from '../modal.js';
import { bookingsPage } from '../pages/bookings.js';
import { optionValues, state } from '../state.js';
import { $, $$, dmy, esc } from '../util.js';

const PLACES = [['airport', 'Airport'], ['hotel', 'Hotel'], ['port', 'Port']];
// The API names of the cost / revenue amounts (per room per night for hotels, per trip for transfers).
const MONEY_KEYS = { hotels: ['cost_per_night', 'revenue_per_night'], transfers: ['cost', 'revenue'] };
const MONEY_FORM = { cost: '', cost_currency: 'EGP', revenue: '', revenue_currency: 'EGP', exchange_rate: '' };
const SEARCH_DELAY_MS = 300;
const MAX_GUESTS = 6; // keep in step with MAX_GUESTS in sheet/constants.py

const ctx = () => state.ctx;
// Every await below checks that the dialog it started for is still the one open (state.ctx is replaced when
// another dialog opens or the dialog closes), so a late answer can never fill in a different booking.
const stillOpen = (mine) => state.ctx === mine;
const isHotel = () => ctx().kind === 'hotels';
const touches = (form, place) => form.from_place === place || form.to_place === place;
const touchesHotel = (form) => touches(form, 'hotel');

const blankForm = (kind) => (kind === 'hotels'
  ? { hotel: '', check_in: '', nights: '1', ...MONEY_FORM }
  : { from_place: 'airport', to_place: 'port', airport: '', port_name: '', hotel: '', at: '', ...MONEY_FORM });

/** The Master-data value that names this place (e.g. "Borg El Arab Airport" for the city "Borg El Arab"), or ''. */
function matchOption(kind, text) {
  const needle = (text || '').trim().toLowerCase();
  if (!needle) return '';
  return optionValues(kind, ctx().vessel?.port ?? null).find((v) => v.toLowerCase().includes(needle) || needle.includes(v.toLowerCase())) || '';
}

const addDays = (iso, n) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** Open the dialog for a new booking (id null) or an existing one. */
export async function openBookingDialog(kind, id = null) {
  const mine = { view: 'booking', kind, id, vessel: null, crew: [], guests: [], form: blankForm(kind), results: [] };
  state.ctx = mine;
  if (id) {
    let booking;
    try {
      booking = await api(`/api/${kind}/${id}/`);
    } catch (error) {
      if (stillOpen(mine)) setStatus('error', error.message);
      return;
    }
    if (!stillOpen(mine)) return; // another booking was opened meanwhile
    const form = ctx().form;
    Object.assign(ctx(), {
      vessel: { id: booking.vessel.id, name: booking.vessel.name, port: booking.vessel.port, port_label: booking.vessel.port_label },
      guests: booking.guests.map((g) => ({ ...g })),
    });
    for (const key of Object.keys(form)) if (key in booking) form[key] = booking[key] ?? '';
    form.nights = String(booking.nights ?? form.nights);
    const [costKey, revenueKey] = MONEY_KEYS[kind];
    form.cost = booking[costKey] ?? '';
    form.revenue = booking[revenueKey] ?? '';
  }
  render({ fresh: true }); // a new dialog starts at the top
  if (id) loadCrew();
}

async function loadCrew() {
  const mine = ctx();
  const vesselId = mine.vessel.id;
  let crew;
  try {
    ({ crew } = await api(`/api/vessels/${vesselId}/crew/`));
  } catch (error) {
    if (stillOpen(mine)) setStatus('error', `Could not load the crew: ${error.message}`);
    crew = [];
  }
  if (!stillOpen(mine) || mine.vessel?.id !== vesselId) return; // closed, another dialog, or another vessel
  mine.crew = crew;
  // When editing, tick the crew members who are already guests (matched by name).
  for (const guest of mine.guests) {
    if (guest.crewIndex !== undefined) continue;
    const index = crew.findIndex((c) => c.name.toUpperCase() === guest.name.toUpperCase());
    if (index >= 0 && !mine.guests.some((g) => g.crewIndex === index)) guest.crewIndex = index;
  }
  render();
}

/* ---- drawing ---- */

function vesselBlock() {
  const { vessel, id, results } = ctx();
  if (vessel) {
    return `<div class="field"><label>Vessel</label><div class="bkd-vessel"><b>${esc(vessel.name)}</b>
      ${vessel.date ? `<span class="none">${dmy(vessel.date)}</span>` : ''} <span class="none">${esc(vessel.port_label || '')}</span>
      ${id ? '' : '<button class="btn ghost small" data-act="booking-change-vessel">Change</button>'}</div></div>`;
  }
  const found = results.map((v) => `<button class="btn ghost small" data-act="booking-pick-vessel" data-id="${v.id}">
      ${esc(v.name)} · ${dmy(v.date)} · ${esc(v.port_label)}</button>`).join('');
  return `<div class="field"><label for="bkd-vessel-q">Vessel</label>
    <input class="input" id="bkd-vessel-q" autocomplete="off" aria-label="Find the vessel by name">
    <div id="bkd-vessel-results" class="bkd-results">${found}</div></div>`;
}

function guestsBlock() {
  const { crew, guests, vessel } = ctx();
  if (!vessel) return '';
  const ticked = (i) => guests.some((g) => g.crewIndex === i);
  const crewList = crew.length
    ? crew.map((c, i) => `<label class="bkd-crew-item"><input type="checkbox" data-crew-i="${i}" ${ticked(i) ? 'checked' : ''}>
        ${c.group === 'on' ? '↑ On' : '↓ Off'} · ${esc(c.name)}${c.rank ? ` · ${esc(c.rank)}` : ''}</label>`).join('')
    : '<span class="none">No crew change on this vessel. Add guests by name below.</span>';
  const line = (g, i) => `<div class="bkd-guest" data-g-i="${i}">
      <input class="input" data-g-f="name" value="${esc(g.name)}" aria-label="Guest name">
      <input class="input" data-g-f="rank" value="${esc(g.rank)}" aria-label="Rank">
      <input class="input" data-g-f="nationality" value="${esc(g.nationality)}" aria-label="Nationality">
      <input class="input" data-g-f="flight" value="${esc(g.flight)}" aria-label="Flight">
      <button class="btn ghost small" data-act="booking-del-guest" data-i="${i}" title="Remove this guest">🗑</button></div>`;
  const headings = guests.length
    ? '<div class="bkd-guest bkd-guest-head"><span>Name</span><span>Rank</span><span>Nationality</span><span>Flight</span><span></span></div>'
    : '';
  return `<div class="section-title"><span>Guests</span></div>
    <div id="bkd-crew" class="bkd-crew">${crewList}</div>
    <div id="bkd-guests">${headings}${guests.map(line).join('')}</div>
    ${guests.length < MAX_GUESTS ? '<button class="btn ghost small" data-act="booking-add-guest">+ Other guest</button>' : ''}`;
}

function detailsBlock() {
  const { form, vessel } = ctx();
  if (!vessel) return '';
  const field = (label, html) => `<div class="field"><label>${label}</label>${html}</div>`;
  const hotelSelect = `<select class="select" data-bf="hotel">${optionChoices('hotel', form.hotel, vessel.port)}</select>`;
  let details;
  if (isHotel()) {
    const out = form.check_in && Number(form.nights) > 0 ? dmy(addDays(form.check_in, Number(form.nights))) : '—';
    details = `<div class="row three">
        ${field('Hotel', hotelSelect)}
        ${field('Check-in', `<input class="input" type="date" data-bf="check_in" value="${esc(form.check_in)}">`)}
        ${field('Nights', `<input class="input" type="number" min="1" max="60" step="1" data-bf="nights" value="${esc(form.nights)}">`)}
      </div><div class="help">Check-out: <b id="bkd-check-out">${out}</b></div>`;
  } else {
    const placeSelect = (key) => `<select class="select" data-bf="${key}">${PLACES.map(([v, label]) =>
      `<option value="${v}" ${form[key] === v ? 'selected' : ''}>${label}</option>`).join('')}</select>`;
    // Which airport / hotel / port: asked only for the ends the trip uses.
    const named = [
      touches(form, 'airport') && field('Airport', `<select class="select" data-bf="airport">${optionChoices('airport', form.airport, vessel.port)}</select>`),
      touchesHotel(form) && field('Hotel', hotelSelect),
      touches(form, 'port') && field('Port', `<select class="select" data-bf="port_name">${optionChoices('port', form.port_name, vessel.port)}</select>`),
    ].filter(Boolean).join('');
    details = `<div class="row three">
        ${field('From', placeSelect('from_place'))}
        ${field('To', placeSelect('to_place'))}
        ${field('Date & time', `<input class="input" type="datetime-local" data-bf="at" value="${esc(form.at)}">`)}
      </div><div class="row three">${named}</div>`;
  }
  const currencySelect = (key) => `<select class="select" data-bf="${key}">${['EGP', 'USD'].map((c) =>
    `<option ${form[key] === c ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
  const amount = (key) => `<input class="input" type="number" min="0" step="any" data-bf="${key}" value="${esc(form[key])}">`;
  const usd = form.cost_currency === 'USD' || form.revenue_currency === 'USD';
  const per = isHotel() ? ' per night' : '';
  const price = `<div class="section-title"><span>Money ${isHotel() ? '(per room per night)' : '(per trip)'} — optional</span></div>
    <div class="row three">
      ${field(`Cost${per} (we pay)`, amount('cost'))}
      ${field('Currency', currencySelect('cost_currency'))}
      ${usd ? field('Exchange rate (optional)', amount('exchange_rate')) : '<div></div>'}
    </div>
    <div class="row three">
      ${field(`Revenue${per} (we get)`, amount('revenue'))}
      ${field('Currency', currencySelect('revenue_currency'))}
    </div>`;
  return `<div class="section-title"><span>${isHotel() ? 'Hotel stay' : 'Transfer'}</span></div>${details}${price}`;
}

/** A selector that finds the same field again after a redraw, or null. */
function fieldKey(element) {
  if (!element || !el.modal.contains(element)) return null;
  if (element.dataset.bf) return `[data-bf="${element.dataset.bf}"]`;
  if (element.dataset.gF) return `[data-g-i="${element.closest('[data-g-i]').dataset.gI}"] [data-g-f="${element.dataset.gF}"]`;
  if (element.dataset.crewI !== undefined) return `[data-crew-i="${element.dataset.crewI}"]`;
  return element.id ? `#${element.id}` : null;
}

/** Draw the dialog. Redraws keep the scroll position and the field being used, so nothing jumps. */
function render({ fresh = false } = {}) {
  const { kind, id } = ctx();
  const scroll = el.modal.scrollTop;
  const focused = fresh ? null : fieldKey(document.activeElement);
  const title = `${id ? 'Edit' : 'Add'} ${kind === 'hotels' ? 'hotel stay' : 'transfer'}`;
  openModal(`${head(title)}
    <div class="m-body" id="booking-form">${vesselBlock()}${guestsBlock()}${detailsBlock()}</div>
    <div class="m-foot">
      ${id ? '<button class="btn danger" data-act="booking-delete">Delete</button>' : '<span></span>'}
      <div class="right"><button class="btn ghost" data-act="close">Cancel</button>
        <button class="btn primary" data-act="booking-save" ${ctx().vessel && !ctx().saving ? '' : 'disabled'}>Save</button></div></div>`);
  if (fresh) return;
  el.modal.scrollTop = scroll;
  if (focused) el.modal.querySelector(focused)?.focus();
}

/* ---- pre-filling from the crew's flights and existing stays ---- */

async function prefill() {
  const mine = ctx();
  const { form, guests, crew, vessel } = mine;
  const first = guests.find((g) => g.crewIndex !== undefined);
  const member = first ? crew[first.crewIndex] : null;
  if (isHotel()) {
    if (!form.check_in && member?.arrival) form.check_in = member.arrival.slice(0, 10);
  } else {
    const moment = member?.group === 'off' ? member?.departure : member?.arrival;
    if (!form.at && moment) form.at = moment;
    if (touches(form, 'airport') && !form.airport) form.airport = matchOption('airport', member?.city);
    if (touches(form, 'port') && !form.port_name) form.port_name = matchOption('port', vessel.port_label);
    const guestName = guests[0]?.name?.toUpperCase();
    if (touchesHotel(form) && !form.hotel && guestName) {
      try {
        const { bookings } = await api(`/api/hotels/?${new URLSearchParams({ q: guestName, page_size: 50 })}`);
        const stay = bookings.find((b) => b.vessel.id === vessel.id && b.guests.some((g) => g.name === guestName));
        if (stay && !form.hotel) form.hotel = stay.hotel;
      } catch {
        // no pre-fill
      }
      if (!stillOpen(mine)) return;
    }
  }
  render();
}

/* ---- events (wired in main.js / actions.js) ---- */

let searchTimer;
let searchTicket = 0;

/** Typing in the dialog: keep the values in state.ctx, re-draw only when the layout changes. */
export function onBookingInput(event) {
  if (ctx().view !== 'booking') return;
  const input = event.target;
  if (input.id === 'bkd-vessel-q') {
    if (event.type !== 'input') return; // "change" on leaving the box would only search again
    clearTimeout(searchTimer);
    const q = input.value.trim();
    const mine = ctx();
    const ticket = ++searchTicket;
    searchTimer = setTimeout(async () => {
      const box = () => $('#bkd-vessel-results');
      if (!q) {
        mine.results = [];
        if (box()) box().innerHTML = '';
        return;
      }
      let vessels;
      try {
        ({ vessels } = await api(`/api/vessels/?${new URLSearchParams({ q, page_size: 10 })}`));
      } catch (error) {
        if (stillOpen(mine)) setStatus('error', error.message);
        return;
      }
      if (!stillOpen(mine) || mine.vessel || ticket !== searchTicket) return; // an older search answering late
      mine.results = vessels;
      if (box()) box().innerHTML = vessels.map((v) => `<button class="btn ghost small" data-act="booking-pick-vessel" data-id="${v.id}">
          ${esc(v.name)} · ${dmy(v.date)} · ${esc(v.port_label)}</button>`).join('') || '<span class="none">No vessel found.</span>';
    }, SEARCH_DELAY_MS);
    return;
  }
  if (input.dataset.gF) {
    const guest = ctx().guests[Number(input.closest('[data-g-i]').dataset.gI)];
    guest[input.dataset.gF] = input.value;
    return;
  }
  if (input.dataset.crewI !== undefined && event.type === 'change') {
    toggleCrew(Number(input.dataset.crewI), input.checked);
    return;
  }
  if (!input.dataset.bf) return;
  const form = ctx().form;
  const before = form[input.dataset.bf];
  form[input.dataset.bf] = input.value;
  if (before === input.value) return;
  if (['from_place', 'to_place', 'cost_currency', 'revenue_currency'].includes(input.dataset.bf)) {
    render();
    if (!input.dataset.bf.endsWith('currency')) prefill();
  } else if (isHotel() && ['check_in', 'nights'].includes(input.dataset.bf)) {
    const out = form.check_in && Number(form.nights) > 0 ? dmy(addDays(form.check_in, Number(form.nights))) : '—';
    const box = $('#bkd-check-out');
    if (box) box.textContent = out;
  }
}

function toggleCrew(index, on) {
  const { guests, crew } = ctx();
  if (on) {
    if (guests.length >= MAX_GUESTS) {
      render();
      return;
    }
    const c = crew[index];
    guests.push({ name: c.name, rank: c.rank, nationality: c.nationality, group: c.group, flight: c.flight, crewIndex: index });
    prefill();
  } else {
    ctx().guests = guests.filter((g) => g.crewIndex !== index);
    render();
  }
}

export async function pickVessel(button) {
  const vessel = ctx().results.find((v) => v.id === Number(button.dataset.id));
  if (!vessel) return;
  Object.assign(ctx(), { vessel, crew: [], guests: [] });
  render();
  await loadCrew();
}

export function changeVessel() {
  Object.assign(ctx(), { vessel: null, crew: [], guests: [], results: [] });
  render();
}

export function addGuest() {
  if (ctx().guests.length >= MAX_GUESTS) return;
  ctx().guests.push({ name: '', rank: '', nationality: '', group: '', flight: '' });
  render();
  $$('#bkd-guests [data-g-f="name"]').pop()?.focus();
}

export function removeGuest(button) {
  ctx().guests.splice(Number(button.dataset.i), 1);
  render();
}

/** Run one save / delete at a time for this dialog: a double click must not create a booking twice. */
async function once(mine, action) {
  if (mine.saving) return false;
  mine.saving = true;
  $$('#modal .m-foot .btn').forEach((b) => { b.disabled = true; });
  try {
    await mutate(action);
    return true;
  } catch {
    return false; // mutate already showed the error in the dialog
  } finally {
    mine.saving = false;
    if (stillOpen(mine)) $$('#modal .m-foot .btn').forEach((b) => { b.disabled = b.dataset.act === 'booking-save' && !mine.vessel; });
  }
}

export async function saveBooking() {
  const mine = ctx();
  const { kind, id, vessel, guests, form } = mine;
  const { cost, revenue, ...fields } = form;
  const [costKey, revenueKey] = MONEY_KEYS[kind];
  const payload = {
    ...fields,
    vessel: vessel.id,
    guests: guests.map(({ name, rank, nationality, group, flight }) => ({ name, rank, nationality, group, flight })),
    [costKey]: cost,
    [revenueKey]: revenue,
  };
  if (kind === 'hotels') payload.nights = Number(form.nights);
  const saved = await once(mine, () => (id ? api(`/api/${kind}/${id}/`, 'PUT', payload) : api(`/api/${kind}/`, 'POST', payload)));
  if (!saved || !stillOpen(mine)) return;
  closeModal();
  await bookingsPage(kind).load();
}

export async function deleteBooking() {
  const mine = ctx();
  const { kind, id } = mine;
  if (mine.saving || !confirm(`Delete this ${kind === 'hotels' ? 'hotel stay' : 'transfer'}? This cannot be undone.`)) return;
  if (!(await once(mine, () => api(`/api/${kind}/${id}/`, 'DELETE'))) || !stillOpen(mine)) return;
  closeModal();
  await bookingsPage(kind).load();
}
