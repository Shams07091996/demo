// Turning pasted text (e.g. cells copied from Excel) into vessel rows. Pure functions: no DOM.

const HEADER = /^(vessel( name)?|name|ship)$/i;
const DELIMITERS = ['\t', ';', ','];

export const detectDelimiter = (text) => DELIMITERS.find((d) => text.includes(d)) || '\t';

const cleanCell = (cell) => cell.trim().replace(/^"(.*)"$/, '$1').trim();

/** dd.mm.yyyy, dd/mm/yyyy, dd-mm-yyyy (day first) or yyyy-mm-dd -> 'yyyy-mm-dd', or '' when not a real date. */
export function parseDate(text) {
  const value = String(text).trim();
  let year; let month; let day;
  let match = value.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (match) {
    [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else {
    match = value.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$/);
    if (!match) return '';
    [day, month, year] = [Number(match[1]), Number(match[2]), Number(match[3])];
    if (match[3].length === 2) year += 2000;
  }
  const probe = new Date(Date.UTC(year, month - 1, day));
  const real = probe.getUTCFullYear() === year && probe.getUTCMonth() === month - 1 && probe.getUTCDate() === day;
  return real ? `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}` : '';
}

const keyOf = (name, date) => `${name.trim().toUpperCase()}|${date}`;

/**
 * (Re)compute every row's errors, warnings and skip flag. Pure apart from writing those three fields, so the
 * bulk-add table can call it after every edit.
 * A row: {line, name, date, opr, poc, agent, badDate?, exists?, errors[], warnings[], skip}
 *   badDate: the pasted text that was not a date (until the user picks one); exists: already saved (server check).
 * @param known  {opr: Set, poc: Set, agent: Set} master-data values (to warn about unknown ones)
 */
export function checkRows(rows, known = {}) {
  const taken = new Set();
  for (const row of rows) {
    row.errors = [];
    row.warnings = [];
    row.skip = false;
    if (!row.name.trim()) row.errors.push('Vessel name is missing.');
    if (!row.date) row.errors.push(row.badDate ? `"${row.badDate}" is not a valid date.` : 'Date is missing.');
    for (const kind of ['opr', 'poc', 'agent']) {
      if (row[kind] && known[kind] && !known[kind].has(row[kind])) {
        row.warnings.push(`${kind.toUpperCase()} "${row[kind]}" is not in Master data.`);
      }
    }
    if (row.errors.length) continue;
    const key = keyOf(row.name, row.date);
    if (row.exists) {
      row.skip = true;
      row.warnings.push('Already exists, so it will be skipped.');
    } else if (taken.has(key)) {
      row.skip = true;
      row.warnings.push('Same vessel and date as another row, so it will be skipped.');
    } else {
      taken.add(key);
    }
  }
  return rows;
}

/**
 * @param text      pasted lines: Vessel name, Date, OPR, POC, Agent
 * @param defaults  {date, opr, poc, agent} used for cells that are left out
 * @param existing  [{name, date}] vessels already saved (to spot duplicates)
 * @param known     {opr: Set, poc: Set, agent: Set} master-data values (to warn about unknown ones)
 * @returns rows (see checkRows)
 */
export function parseBulk(text, defaults = {}, existing = [], known = {}) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  const delimiter = detectDelimiter(text);
  const saved = new Set(existing.map((v) => keyOf(v.name, v.date)));
  const rows = [];

  lines.forEach((line, index) => {
    const cells = line.split(delimiter).map(cleanCell);
    if (index === 0 && HEADER.test(cells[0] || '')) return;
    const [name = '', dateText = '', opr = '', poc = '', agent = ''] = cells;
    const date = dateText ? parseDate(dateText) : defaults.date || '';
    rows.push({
      line: index + 1,
      name: name.toUpperCase(),
      date,
      badDate: dateText && !date ? dateText : '',
      exists: saved.has(keyOf(name, date)),
      opr: opr || defaults.opr || '',
      poc: poc || defaults.poc || '',
      agent: agent || defaults.agent || '',
      errors: [],
      warnings: [],
      skip: false,
    });
  });
  return checkRows(rows, known);
}
