// Unit tests for the pure parsers: crew / flight text and pasted vessel lists (no browser needed).
const path = require('path');
const { buildSync } = require('esbuild');

function load(file) {
  const code = buildSync({
    entryPoints: [path.join(__dirname, '../sheet/static/sheet/js', file)],
    bundle: true, write: false, format: 'cjs', logLevel: 'error',
  }).outputFiles[0].text;
  const mod = { exports: {} };
  new Function('module', 'exports', code)(mod, mod.exports);
  return mod.exports;
}
const { parsePersonal, parseFlightText, parsePdfText } = load('crewParsing.js');
const { parseBulk, parseDate, detectDelimiter } = load('bulkParsing.js');

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

const pdf = 'Travel Arrangements for SMITH/JOHN MR Booking Reference ABC123 Travel Details Sunday 05 Apr 2026 RANK: 4/E - APMID: 99 ' +
  'Flight Information Airline Booking Ref VBCUSA Airline Turkish Airlines Flight TK689 Origin Alexandria, Borg el Arab Destination Istanbul Airport Departing 08:55 Arriving 12:30 ' +
  'Flight Information Airline Booking Ref VBCUSA Airline Turkish Airlines Flight TK1 Origin Istanbul Airport Destination London Departing 14:00 ' +
  'Travel Arrangements for DOE/JANE MS Booking Reference XYZ Travel Details Monday 06 Apr 2026 ' +
  'Flight Information Airline Booking Ref Q Airline Egyptair Flight MS777 Origin Cairo International Destination Dubai Departing 23:10';
const members = parsePdfText(pdf);
check(members.length === 2, 'two crew members found in one PDF');
check(members[0].name === 'JOHN SMITH' && members[0].personalStructured.rank === '4/E', 'PDF name (SURNAME/GIVEN) and rank');
const leg = members[0].flightStructured.segments;
check(leg.length === 1 && leg[0].flightNo === 'TK689', 'only the Egypt departure leg is kept');
check(leg[0].airline === 'Turkish Airlines' && leg[0].arrivalCity === 'Istanbul Airport', 'PDF airline and destination');
check(leg[0].departureTime === '05 Apr 2026 08:55', 'PDF departure date and time');
check(members[1].name === 'JANE DOE' && members[1].flightStructured.segments[0].flightNo === 'MS777', 'second member parsed');

/* ---------- pasted vessel lists ---------- */
check(parseDate('13.11.2026') === '2026-11-13' && parseDate('13/11/2026') === '2026-11-13', 'dates: day-first dd.mm.yyyy and dd/mm/yyyy');
check(parseDate('2026-11-13') === '2026-11-13' && parseDate('1-2-26') === '2026-02-01', 'dates: ISO and short forms');
check(parseDate('31.02.2026') === '' && parseDate('13.13.2026') === '' && parseDate('soon') === '', 'dates: impossible or unreadable dates are rejected');
check(detectDelimiter('a\tb') === '\t' && detectDelimiter('a;b') === ';' && detectDelimiter('a,b') === ',', 'delimiter detection');

const defaults = { date: '2026-11-20', opr: 'ARK', poc: 'ALY', agent: 'NILE' };
const known = { opr: new Set(['ARK', 'MSK']), poc: new Set(['ALY']), agent: new Set(['NILE']) };
const existing = [{ name: 'OLD SHIP', date: '2026-11-13' }];
const text = [
  'Vessel\tDate\tOPR\tPOC\tAgent',            // header: ignored
  'msc aurora\t13.11.2026\tMSK\tALY\tNILE',   // complete row, name is upper-cased
  'arkas star',                               // only a name: defaults fill the rest
  'old ship\t13.11.2026',                     // already saved -> skipped
  'MSC AURORA\t13.11.2026',                   // repeated in the paste -> skipped
  '\t13.11.2026',                             // no name -> error
  'BAD DATE\tsoon',                           // unreadable date -> error
  'UNKNOWN\t14.11.2026\tZZZ\t\t',             // OPR not in master data -> warning, still created
].join('\n');
const rows = parseBulk(text, defaults, existing, known);
check(rows.length === 7, 'header row is ignored, six data rows plus the blank-name row are read');
check(rows[0].name === 'MSC AURORA' && rows[0].date === '2026-11-13' && rows[0].opr === 'MSK' && !rows[0].errors.length, 'complete row');
check(rows[1].date === '2026-11-20' && rows[1].opr === 'ARK' && rows[1].poc === 'ALY' && rows[1].agent === 'NILE', 'missing cells use the defaults');
check(rows[2].skip && /exists/.test(rows[2].warnings[0]), 'a vessel that is already saved is skipped');
check(rows[3].skip, 'a vessel repeated in the paste is skipped');
check(rows[4].errors.length === 1 && /name/i.test(rows[4].errors[0]), 'missing name is an error');
check(rows[5].errors.length === 1 && /not a valid date/.test(rows[5].errors[0]), 'unreadable date is an error');
check(!rows[6].errors.length && rows[6].warnings.some((w) => /OPR "ZZZ"/.test(w)), 'unknown OPR is only a warning');
check(parseBulk('A;13.11.2026;ARK', {}, [], {})[0].opr === 'ARK', 'semicolon-separated lines work');
check(parseBulk('A,2026-11-13', {}, [], {})[0].date === '2026-11-13', 'comma-separated lines work');
check(parseBulk('"QUOTED NAME";13.11.2026', {}, [], {})[0].name === 'QUOTED NAME', 'quotes around cells are removed');
check(parseBulk('A', {}, [], {})[0].errors.length === 1, 'no date and no default is an error');
check(parseBulk('', defaults).length === 0 && parseBulk('\n\n  \n', defaults).length === 0, 'blank input gives no rows');

/* ---------- checkRows: the same rules re-run after every edit in the preview table ---------- */
const { checkRows } = load('bulkParsing.js');
const r = (o) => ({ line: 1, name: 'A', date: '2026-11-13', opr: '', poc: '', agent: '', errors: [], warnings: [], skip: false, ...o });
let rs = checkRows([r({}), r({ line: 2 })], {});
check(!rs[0].skip && rs[1].skip && rs[1].warnings.includes('Same vessel and date as another row, so it will be skipped.'), 'checkRows: second identical row is skipped');
rs[1].date = '2026-11-14'; checkRows(rs, {});
check(!rs[1].skip && rs[1].warnings.length === 0, 'checkRows: editing the duplicate back makes it ready');
rs = checkRows([r({ date: '' })], {});
check(rs[0].errors.join() === 'Date is missing.', 'checkRows: empty date is an error');
rs = checkRows([r({ date: '', badDate: '31.02.2026' })], {});
check(rs[0].errors.join() === '"31.02.2026" is not a valid date.', 'checkRows: pasted bad date keeps its message');
rs = checkRows([r({ name: '  ' })], {});
check(rs[0].errors.join() === 'Vessel name is missing.', 'checkRows: blank name is an error');
rs = checkRows([r({ opr: 'ZZZ' })], { opr: new Set(['ARK']) });
check(rs[0].warnings.join() === 'OPR "ZZZ" is not in Master data.' && !rs[0].skip, 'checkRows: unknown OPR warns');
rs = checkRows([r({ exists: true })], {});
check(rs[0].skip && rs[0].warnings.includes('Already exists, so it will be skipped.'), 'checkRows: server duplicate is skipped');
rs = checkRows([r({ errors: ['old'], warnings: ['old'], skip: true })], {});
check(!rs[0].errors.length && !rs[0].warnings.length && !rs[0].skip, 'checkRows: recomputes from scratch');
check(parseBulk('A\t31.02.2026', {}, [], {})[0].badDate === '31.02.2026', 'parseBulk: keeps the pasted text of a bad date');
check(parseBulk('A\t13.11.2026', {}, [{ name: 'a', date: '2026-11-13' }], {})[0].exists === true, 'parseBulk: marks rows that already exist');

console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
process.exit(failed ? 1 : 0);
