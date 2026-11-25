// The values a crew member's Hotel / Transport boxes start with when the button is first pressed. Twin of the
// server's automatic values (sheet/crewbookings.py `_when`, sheet/logistics.py `crew_leg` / `parse_flight_time`):
// on-signers airport -> port at landing (hotel from the landing day), off-signers port -> airport at take-off (hotel
// from the vessel date); a flight time that can't be read -> the vessel date at 00:00. Pure, tested in parsing_test.js.

const MONTHS = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split(' ');
const DAY_MONTH_TIME = /(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\s+(?:(\d{4})\s+)?(\d{1,2}):(\d{2})/;
const TIME = /^\s*(\d{1,2}):(\d{2})\s*$/;
const DMY = /(\d{1,2})[./-](\d{1,2})[./-](\d{4})/;

const pad = (n) => String(n).padStart(2, '0');
const stamp = (y, m, d, hh, mm) => `${y}-${pad(m)}-${pad(d)}T${pad(hh)}:${pad(mm)}`;

// A real calendar day (31 FEB is not one).
const realDay = (y, m, d) => {
  const day = new Date(Date.UTC(y, m - 1, d));
  return day.getUTCFullYear() === y && day.getUTCMonth() === m - 1 && day.getUTCDate() === d;
};
const daysBetween = (a, b) => Math.abs(Date.UTC(...a) - Date.UTC(...b)) / 86400000;

/** 'YYYY-MM-DDTHH:MM' of a flight time ('13 NOV 10:00', year optional, or '10:00' + a dd.mm.yyyy date), or ''. */
export function flightMoment(text, segmentDate, vesselDate) {
  const [ny, nm, nd] = vesselDate.split('-').map(Number);
  const found = DAY_MONTH_TIME.exec(String(text || ''));
  if (found) {
    const [, day, mon, year, hour, minute] = found;
    const month = MONTHS.indexOf(mon.toUpperCase()) + 1;
    if (!month || Number(hour) > 23 || Number(minute) > 59) return '';
    const years = year ? [Number(year)] : [ny - 1, ny, ny + 1];
    const options = years.filter((y) => realDay(y, month, Number(day)));
    if (!options.length) return '';
    const best = options.reduce((a, b) => (daysBetween([b, month - 1, Number(day)], [ny, nm - 1, nd])
      < daysBetween([a, month - 1, Number(day)], [ny, nm - 1, nd]) ? b : a));
    return stamp(best, month, Number(day), Number(hour), Number(minute));
  }
  const clock = TIME.exec(String(text || ''));
  const onDay = DMY.exec(String(segmentDate || ''));
  if (clock && onDay && Number(clock[1]) <= 23 && Number(clock[2]) <= 59) {
    const [d, m, y] = onDay.slice(1).map(Number);
    if (realDay(y, m, d)) return stamp(y, m, d, Number(clock[1]), Number(clock[2]));
  }
  return '';
}

const nextDay = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
};

/** {hotel: {checkIn, checkOut}, transport: {from, to, at}} a member's boxes start with. */
export function crewBookingDefaults(member, group, vesselDate) {
  const segments = member?.flightStructured?.segments || [];
  const leg = segments.length ? (group === 'on' ? segments[segments.length - 1] : segments[0]) : null;
  const moment = leg ? flightMoment(group === 'on' ? leg.arrivalTime : leg.departureTime, leg.date, vesselDate) : '';
  const at = moment || `${vesselDate}T00:00`;
  const checkIn = moment && group === 'on' ? moment.slice(0, 10) : vesselDate;
  return {
    hotel: { checkIn, checkOut: nextDay(checkIn) },
    transport: group === 'on' ? { from: 'airport', to: 'port', at } : { from: 'port', to: 'airport', at },
  };
}
