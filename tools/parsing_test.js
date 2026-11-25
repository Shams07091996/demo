// Unit tests for the pure parsers: crew / flight text (no browser needed).
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildSync } = require('esbuild');

function load(entry) {
  const code = buildSync({
    entryPoints: [path.join(__dirname, '../sheet/static/sheet/js', entry)],
    bundle: true, write: false, format: 'cjs', logLevel: 'error',
  }).outputFiles[0].text;
  // Load the bundle as an ordinary CommonJS file (no eval / new Function).
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'parsing-')), `${path.basename(entry)}.cjs`);
  fs.writeFileSync(file, code);
  return require(file);
}
const { parsePersonal, parseFlightText } = load('crewParsing.js');
const { isDelayed, limitRows, statusNeeds, tickSummary } = load('util.js');
const { fillRevenue, rateFor } = load('rates.js');
const { stripMoney } = load('moneyKeys.js');
const { crewBookingDefaults } = load('crewBookings.js');
const { CAN_GROUPS, PAGE_GROUPS, grouped, withNeeds } = load('tickGroups.js');

let failed = 0;
const check = (cond, label) => { console.log(`${cond ? 'PASS' : 'FAIL'} ${label}`); if (!cond) failed += 1; };

/* ---------- crew / flights ---------- */
const p = parsePersonal('Surname: Test\nGiven name: Ahmed\nRank: 2/E\nNationality: Egyptian');
check(p.name === 'Ahmed Test' && p.rank === '2/E' && p.nationality === 'Egyptian', 'personal data lines are parsed');
check(parsePersonal('Surname: Only').name === 'Only', 'surname alone becomes the name');
check(Object.keys(parsePersonal('')).length === 0, 'empty personal data gives nothing');

const manual = 'FLIGHT TK 689 - Turkish Airlines\nDEPARTURE: Alexandria, Egypt  05 APR 08:55\nARRIVAL: Istanbul, Turkey  05 APR 12:30';
const seg = parseFlightText(manual)[0];
check(seg && seg.flightNo === 'TK689' && seg.airline === 'Turkish Airlines', 'manual flight number and airline');
check(seg.departureCity === 'Alexandria, Egypt' && seg.departureTime === '05 APR 08:55', 'manual departure');
check(seg.arrivalCity === 'Istanbul, Turkey' && seg.arrivalTime === '05 APR 12:30', 'manual arrival');
check(parseFlightText('nothing useful here').length === 0, 'unrecognised text gives no segments');
const dated = parseFlightText('FLIGHT     EK 337 - EMIRATES                         TUE 17 NOVEMBER 2026\n' +
  'DEPARTURE: MANILA, PH (NINOY AQUINO INTL), TERMINAL 3           17 NOV 07:55\n')[0];
check(dated && dated.flightNo === 'EK337' && dated.airline === 'EMIRATES', 'the flight date is not part of the airline');
check(parseFlightText('FLIGHT FZ 175 - FLYDUBAI TUE 17 NOVEMBER 2026')[0].airline === 'FLYDUBAI', 'one space before the date: still cut');

const itinerary = 'Travel Details Sunday 05 Apr 2026 ' +
  'Flight Information Airline Booking Ref VBCUSA Airline Turkish Airlines Flight TK689 Origin Alexandria, Borg el Arab Destination Istanbul Airport Departing 08:55 Arriving 12:30 ' +
  'Flight Information Airline Booking Ref VBCUSA Airline Turkish Airlines Flight TK1 Origin Istanbul Airport Destination London Departing 14:00';
const leg = parseFlightText(itinerary);
check(leg.length === 1 && leg[0].flightNo === 'TK689', 'pasted itinerary: only the Egypt departure leg is kept');
check(leg[0].airline === 'Turkish Airlines' && leg[0].arrivalCity === 'Istanbul Airport', 'pasted itinerary airline and destination');
check(leg[0].departureTime === '05 Apr 2026 08:55', 'pasted itinerary departure date and time');
/* ---------- tickSummary: the label of a tick-box filter (Calculations, Services) ---------- */
const STATUSES = { in_progress: 'In progress', completed: 'Completed', cancelled: 'Cancelled' };
check(tickSummary('Status', STATUSES, ['in_progress', 'completed', 'cancelled']) === 'Status: All', 'tickSummary: all ticked');
check(tickSummary('Status', STATUSES, ['in_progress', 'cancelled']) === 'Status: All except Completed', 'tickSummary: all but one of three');
check(tickSummary('Status', STATUSES, ['in_progress']) === 'Status: In progress', 'tickSummary: one of three');
check(tickSummary('Billing', { account: 'On account', cash: 'Cash' }, ['cash']) === 'Billing: Cash', 'tickSummary: one of two');

/* ---------- limitRows: the alerts banner shows at most 20 missing-agent rows ---------- */
const many = limitRows(Array.from({ length: 25 }, (_, i) => i), 20);
check(many.shown.length === 20 && many.shown[19] === 19 && many.more === 5, 'limitRows: 25 rows → 20 shown, 5 more');
check(limitRows([1, 2], 20).more === 0 && limitRows([], 20).shown.length === 0, 'limitRows: short lists are shown whole');

/* ---------- delay (berthing more than 2 hours after arrival) ---------- */
check(isDelayed('2026-11-13T08:00', '2026-11-13T10:00') === false, 'isDelayed: exactly 2 hours is not delayed');
check(isDelayed('2026-11-13T08:00', '2026-11-13T10:01') === true, 'isDelayed: 2:01 is delayed');
check(isDelayed('2026-11-13T23:00', '2026-11-14T02:00') === true, 'isDelayed: across midnight');
check(isDelayed('', '2026-11-13T10:01') === false && isDelayed('2026-11-13T08:00', '') === false, 'isDelayed: a missing time is never delayed');

/* ---------- agreed rates fill in the revenue (js/rates.js) ---------- */
const UNITS = { 'Crew Change': 'service', 'Fresh Water': 'unit', Landing: 'line', 'Cash to Master': 'percent' };
const blue = { rates: { 'Crew Change': { amount: 300, currency: 'USD' }, 'Fresh Water': { amount: 12.35, currency: 'EGP' },
  Landing: { amount: 40, currency: 'USD' }, 'Cash to Master': { amount: 5, currency: 'USD' } } };
const none = new Set();
const fill = (serviceType, data, isNew = true, touched = none) =>
  fillRevenue({ serviceType, rate: rateFor(blue, serviceType, UNITS), data, isNew, touched });
check(rateFor(blue, 'Fresh Water', UNITS).unit === 'unit' && rateFor(null, 'Landing', UNITS) === null
  && rateFor(blue, 'Medical Treatment', UNITS) === null, 'rateFor: the payer\'s rate with its unit, or null');
let d = fill('Crew Change', { revenue: '', revenueCurrency: 'EGP' });
check(d.revenue === 300 && d.revenueCurrency === 'USD', 'fill service rate on new');
d = fill('Fresh Water', { quantity: 3 });
check(d.revenue === 37.05 && d.revenueCurrency === 'EGP', 'fill unit rate times quantity rounds to cent');
check(fill('Fresh Water', { quantity: '' }).revenue === undefined, 'fill unit rate waits for a quantity');
check(fill('Fresh Water', { quantity: 0.333 }).revenue === 4.11, 'fill unit rate: 12.35 x 0.333 = 4.11');
d = fill('Landing', { entries: [{ revenue: 7 }, { revenue: '' }] }, true, new Set(['entry:0']));
check(d.entries[0].revenue === 7 && d.entries[1].revenue === 40 && d.entries[1].revenueCurrency === 'USD', 'fill line rate skips touched entries');
check(fill('Cash to Master', { shareMode: 'percent' }).percentage === 5, 'fill percent in percent mode');
check(fill('Cash to Master', { shareMode: 'fixed', percentage: '' }).percentage === '', 'fill percent only in percent mode');
d = fill('Fresh Water', { quantity: 9, revenue: 900, revenueCurrency: 'USD' }, false);
check(d.revenue === 900 && d.revenueCurrency === 'USD', 'fill keeps saved non-zero revenue');
check(fill('Fresh Water', { quantity: 2, revenue: 0 }, false).revenue === 24.7, 'fill a saved 0 revenue');
check(fill('Crew Change', { revenue: 5 }, true, new Set(['revenue'])).revenue === 5, 'fill skips touched revenue');
// Switching to a payer with no rate for this type: what the previous rate filled is cleared (new service only).
const was = (serviceType) => rateFor(blue, serviceType, UNITS);
const clear = (serviceType, data, isNew = true, touched = none) =>
  fillRevenue({ rate: null, previous: was(serviceType), data, isNew, touched });
d = clear('Crew Change', { revenue: 300, revenueCurrency: 'USD' });
check(d.revenue === '' && d.revenueCurrency === 'USD', 'no rate: the previous service rate is cleared');
check(clear('Fresh Water', { quantity: 3, revenue: 37.05 }).revenue === '', 'no rate: the previous unit rate is cleared');
d = clear('Landing', { entries: [{ revenue: 7 }, { revenue: 40 }] }, true, new Set(['entry:0']));
check(d.entries[0].revenue === 7 && d.entries[1].revenue === '', 'no rate: untouched lines cleared, typed ones kept');
check(clear('Cash to Master', { shareMode: 'percent', percentage: 5 }).percentage === '', 'no rate: the previous percentage is cleared');
check(clear('Crew Change', { revenue: 300 }, true, new Set(['revenue'])).revenue === 300, 'no rate: a typed revenue stays');
check(clear('Crew Change', { revenue: 300 }, false).revenue === 300, 'no rate: a saved service keeps its revenue');
check(fillRevenue({ rate: null, previous: null, data: { revenue: 9 }, isNew: true, touched: none }).revenue === 9, 'no rate and none before: nothing changes');
const plain = { revenue: 1 };
check(fillRevenue({ serviceType: 'Landing', rate: null, data: plain, isNew: true, touched: none }).revenue === 1, 'no rate leaves data unchanged');
check(rateFor(blue, 'Others / Remarks', UNITS) === null, 'others has no rate');
const original = { entries: [{ revenue: '' }] };
fill('Landing', original);
check(original.entries[0].revenue === '', 'fill returns a copy');

/* ---------- service status needs (same rule as services.status_permissions) ---------- */
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
check(same(statusNeeds('cancelled', 'cancelled'), []), 'status: unchanged needs nothing');
check(same(statusNeeds('in_progress', 'cancelled'), ['services.cancel']), 'status: to Cancelled needs cancel');
check(same(statusNeeds('cancelled', 'in_progress'), ['services.cancel']), 'status: from Cancelled needs cancel');
check(same(statusNeeds('in_progress', 'completed'), ['services.complete']), 'status: to Completed needs complete');
check(same(statusNeeds('completed', 'in_progress'), ['services.complete']), 'status: from Completed needs complete');
check(same(statusNeeds('cancelled', 'completed'), ['services.cancel', 'services.complete']), 'status: both');

/* ---------- without money.edit the service dialog sends no money (js/moneyKeys.js, twin of moneyaccess.py) ---------- */
check(same(stripMoney('Fresh Water', { quantity: 5, cost: 10, costCurrency: 'USD', revenue: 20, revenueCurrency: 'EGP', exchangeRate: 50 }),
  { quantity: 5 }), 'money: a single service keeps only its quantity');
check(same(stripMoney('Delivery Parcels', { entries: [{ uid: 'a', awb: '123', weight: 4, cost: 1, costCurrency: 'USD', revenue: 2, revenueCurrency: 'USD' }], exchangeRate: 50 }),
  { entries: [{ uid: 'a', awb: '123', weight: 4 }] }), 'money: lines keep AWB, weight and uid');
check(same(stripMoney('Crew Change', { onSigners: [{ uid: 'a', name: 'Ali', needsHotel: true, brokenVisa: { cost: 5 } }], offSigners: [{ uid: 'b', name: 'Omar' }], cost: 3, revenue: 4 }),
  { onSigners: [{ uid: 'a', name: 'Ali', needsHotel: true }], offSigners: [{ uid: 'b', name: 'Omar' }] }), 'money: crew keep everything but the broken visa');
check(same(stripMoney('Cash to Master', { amount: 100, amountCurrency: 'USD', shareMode: 'percent', percentage: 5, fixedRevenue: null, exchangeRate: null }), {}),
  'money: Cash to Master sends nothing');
check(same(stripMoney('Others / Remarks', { note: 'x', cost: 1 }), { note: 'x' }), 'money: a note stays');

/* ---------- crew card Hotel / Transport: the boxes' starting values (twin of crewbookings._when) ---------- */
const oneLeg = (extra) => ({ flightStructured: { segments: [{ arrivalTime: '', departureTime: '', date: '', ...extra }] } });
check(same(crewBookingDefaults({ flightStructured: { segments: [{ arrivalTime: '01 NOV 05:00' }, { arrivalTime: '20 NOV 14:30' }] } }, 'on', '2026-11-13'),
  { hotel: { checkIn: '2026-11-20', checkOut: '2026-11-21' }, transport: { from: 'airport', to: 'port', at: '2026-11-20T14:30' } }),
'crew defaults: on-signer lands on the last leg, hotel from that day for 1 night');
check(same(crewBookingDefaults({ flightStructured: { segments: [{ departureTime: '25 NOV 09:00' }, { departureTime: '26 NOV 01:00' }] } }, 'off', '2026-11-24'),
  { hotel: { checkIn: '2026-11-24', checkOut: '2026-11-25' }, transport: { from: 'port', to: 'airport', at: '2026-11-25T09:00' } }),
'crew defaults: off-signer takes off on the first leg, hotel from the vessel date');
check(same(crewBookingDefaults({}, 'on', '2026-11-30'),
  { hotel: { checkIn: '2026-11-30', checkOut: '2026-12-01' }, transport: { from: 'airport', to: 'port', at: '2026-11-30T00:00' } }),
'crew defaults: no flight -> vessel date 00:00');
check(crewBookingDefaults(oneLeg({ arrivalTime: '10:05', date: '02.01.2027' }), 'on', '2026-12-30').transport.at === '2027-01-02T10:05',
  'crew defaults: a time plus a dd.mm.yyyy date');
check(crewBookingDefaults(oneLeg({ arrivalTime: '02 JAN 10:05' }), 'on', '2026-12-30').transport.at === '2027-01-02T10:05',
  'crew defaults: no year -> the one nearest the vessel date');
check(crewBookingDefaults(oneLeg({ arrivalTime: '31 FEB 10:05' }), 'on', '2026-12-30').transport.at === '2026-12-30T00:00',
  'crew defaults: an impossible day falls back to the vessel date');

console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
/* ---------- Accounts dialog: Can / Pages groups and what an "All" tick brings with it (js/tickGroups.js) ---------- */
check(same(CAN_GROUPS.map(([g]) => g), ['Marine', 'Operation', 'General']), 'ticks: Can groups');
check(same(PAGE_GROUPS.map(([g]) => g), ['Marine', 'Operation', 'Reports', 'Master data']), 'ticks: Pages groups like the sidebar');
check(same(CAN_GROUPS[1][1], ['operation.edit', 'operation.delete', 'operation.master']), 'ticks: Operation can');
check(same([...withNeeds(['perm:operation.edit'])].sort(), ['page:op_vessels', 'perm:operation.edit']), 'ticks: operation needs Vessel Data');
check(same([...withNeeds(['perm:accounting.close'])].sort(), ['page:calculations', 'perm:accounting.close', 'perm:money.view']),
  'ticks: close lines needs Calculations and so See money');
check(same([...withNeeds(['page:history'])].sort(), ['page:history', 'perm:history.view', 'perm:money.view']), 'ticks: History page chain');
const g = grouped([['vessels.edit', 'A'], ['exports', 'B'], ['new.thing', 'C']], CAN_GROUPS);
check(same(g.map(([label, items]) => [label, items.map(([k]) => k)]), [['Marine', ['vessels.edit']], ['General', ['exports']], ['Other', ['new.thing']]]),
  'ticks: grouped keeps the server order, drops empty groups, unknown keys go to Other');

process.exit(failed ? 1 : 0);
