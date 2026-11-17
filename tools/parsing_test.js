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

const itinerary = 'Travel Details Sunday 05 Apr 2026 ' +
  'Flight Information Airline Booking Ref VBCUSA Airline Turkish Airlines Flight TK689 Origin Alexandria, Borg el Arab Destination Istanbul Airport Departing 08:55 Arriving 12:30 ' +
  'Flight Information Airline Booking Ref VBCUSA Airline Turkish Airlines Flight TK1 Origin Istanbul Airport Destination London Departing 14:00';
const leg = parseFlightText(itinerary);
check(leg.length === 1 && leg[0].flightNo === 'TK689', 'pasted itinerary: only the Egypt departure leg is kept');
check(leg[0].airline === 'Turkish Airlines' && leg[0].arrivalCity === 'Istanbul Airport', 'pasted itinerary airline and destination');
check(leg[0].departureTime === '05 Apr 2026 08:55', 'pasted itinerary departure date and time');

console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
process.exit(failed ? 1 : 0);
