# Bulk Add Editable Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Preview, the bulk-add table is editable (name, date, OPR/POC/Agent), with live checks, remove / add
rows and "Set on all rows", and Create sends exactly what the table shows.

**Architecture:** The row checks move out of `parseBulk` into a pure `checkRows(rows, known)` in `bulkParsing.js`, so
every edit re-runs the same rules. `pages/bulk.js` keeps the `rows` array, renders inputs once, and on each edit
updates only that row's check cell and the summary (so focus is never lost). The server duplicate check is re-run
300 ms after edits stop and when an admin changes the bulk port.

**Tech Stack:** vanilla ES modules; Node test scripts in `tools/` (esbuild + jsdom). No server change.

**Spec:** `docs/superpowers/specs/2026-11-15-bulk-add-editable-preview-design.md` (approved)

**Not a git repo:** each task ends with a checkpoint (tests) instead of a commit.

## Global Constraints

- Limit 200 rows, counting added rows (`MAX_ROWS` in `pages/bulk.js`, matches `BULK_MAX_ROWS`).
- Create stays blocked while any row has ✗; rows marked skipped are left out; button text `Create N vessel(s)`.
- Values not in Master data are kept, shown as an extra dropdown option, and give ⚠ `OPR "X" is not in Master data.`
- Re-Preview after edits asks exactly: `Replace the rows below with the pasted text?`
- "Set on all rows" overwrites that column on every row; empty choices are ignored.
- Every value goes into inputs via escaped `value` attributes / `<option>` text (`esc()`), never raw HTML.

## Review Focus

1. **Typing in a cell**: focus and caret stay in the input while the check cell updates (Task 2 smoke check types two characters in a row).
2. **Editing a row into a duplicate of another row** (same name + date): the later row turns ↷ skipped, and editing it back makes it ✓ again (Task 1 test).
3. **Clearing a date** (date input emptied): row becomes ✗ `Date is missing.`, Create disabled (Task 1 test).
4. **Removing the only ✗ row**: Create becomes enabled with the right count (Task 2 smoke check).
5. **201st row via "+ Add row"**: refused with the limit message (Task 2 smoke check).

---

### Task 1: Pure row checks (`checkRows`)

**Files:**
- Modify: `sheet/static/sheet/js/bulkParsing.js`
- Test: `tools/parsing_test.js`

**Interfaces:**
- Produces: `checkRows(rows: Row[], known: {opr?: Set, poc?: Set, agent?: Set}) -> Row[]` (same array, each row's
  `errors`, `warnings`, `skip` recomputed). `Row = {line, name, date, opr, poc, agent, badDate?: string, exists?: bool,
  errors: string[], warnings: string[], skip: bool}`. `badDate` = the pasted text that wasn't a date (cleared when the
  user picks a date). `exists` = set by the server duplicate check.
- `parseBulk(text, defaults, existing, known)` keeps its signature and output; it builds rows then calls `checkRows`.

- [ ] **Step 1: Write the failing tests** (append to `tools/parsing_test.js`, using its `check(cond, label)`)

```js
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
```

- [ ] **Step 2: Run to verify they fail** — `cd tools && npm run test:parsing` → FAIL (`checkRows` is not a function).
- [ ] **Step 3: Implement `checkRows`** in `bulkParsing.js`; make `parseBulk` set `badDate` for unparseable date text, mark rows that match `existing` with `exists: true`, then return `checkRows(rows, known)`. Order of warnings: master-data ones, then the skip reason. The in-table duplicate rule compares `name.trim().toUpperCase()` + `date` against earlier non-error rows only. Missing date with no default: `Date is missing.` (this replaces the old "(add one or set a default date)" wording; update the existing test on line 78 only if it checks the text — it checks the count).
- [ ] **Step 4: Run to verify they pass** — `npm run test:parsing` → `ALL PASSED`.

---

### Task 2: Editable preview table

**Files:**
- Modify: `sheet/static/sheet/js/pages/bulk.js`, `sheet/static/sheet/js/actions.js`, `sheet/static/sheet/js/main.js` (input/change listener on `#bk-preview`, change on `#bk-port`), `sheet/templates/sheet/index.html` (help text), `sheet/static/sheet/app.css`
- Test: `tools/ui_smoke_test.js` (bulk add section)

**Interfaces:**
- Consumes: `checkRows`, `parseBulk` (Task 1); `optionChoices(kind, current)` from `components.js`; `POST /api/vessels/bulk/check/`, `POST /api/vessels/bulk/`.
- Produces (in `pages/bulk.js`): `previewBulk()`, `createBulk()`, `clearBulk()`, `viewCreated()` (existing), plus `onPreviewEdit(event)`, `addBulkRow()`, `removeBulkRow(index)`, `applyToAllRows()`, `onBulkPortChange()`.
- Markup: each row `<tr data-i="{index}">` with inputs `data-f="name|date|opr|poc|agent"` (`date` is `type=date`; the three others are `<select>` from `optionChoices`); check cell `.bk-check`; remove button `data-act="bulk-del-row" data-i`. Above the table: `#bk-all-date`, `#bk-all-opr`, `#bk-all-poc`, `#bk-all-agent`, button `data-act="bulk-apply-all"`; below: `data-act="bulk-add-row"`. Summary `.bulk-summary` keeps the `bulk-create` button.

- [ ] **Step 1: Write the failing smoke checks** — replace the bulk section's second preview with:

```js
type($('#bk-text'), ['BULK A\t13.11.2026\tSMOKE-OPR\tALY\tSMOKE AGENT', 'bulk b\t31.02.2026', 'BULK C\t14.11.2026'].join('\n'));
click($('[data-act="bulk-preview"]'));
ok(await waitFor(() => $('#bk-preview tr[data-i="1"] [data-f=date]')), 'bulk: preview rows are editable');
const cell = (i, f) => $(`#bk-preview tr[data-i="${i}"] [data-f=${f}]`);
ok($('[data-act="bulk-create"]').disabled && /not a valid date/.test($('#bk-preview tr[data-i="1"] .bk-check').textContent), 'bulk: a bad pasted date shows ✗');
const nameInput = cell(2, 'name'); nameInput.focus(); type(nameInput, 'BULK C2');
ok(w.document.activeElement === nameInput, 'bulk: typing in a cell keeps focus');
type(cell(1, 'date'), '2026-11-14');
ok(await waitFor(() => !$('[data-act="bulk-create"]').disabled && $('[data-act="bulk-create"]').textContent.includes('Create 3')), 'bulk: fixing the date enables Create 3');
type(cell(2, 'date'), '');
ok($('[data-act="bulk-create"]').disabled, 'bulk: clearing a date blocks Create');
click($('#bk-preview tr[data-i="2"] [data-act="bulk-del-row"]'));
ok(await waitFor(() => $('[data-act="bulk-create"]').textContent.includes('Create 2') && !$('[data-act="bulk-create"]').disabled), 'bulk: removing the bad row enables Create 2');
type($('#bk-all-agent'), 'SMOKE AGENT'); click($('[data-act="bulk-apply-all"]'));
ok(cell(1, 'agent').value === 'SMOKE AGENT', 'bulk: "Set on all rows" fills the agent');
click($('[data-act="bulk-add-row"]'));
ok($$('#bk-preview tbody tr').length === 3 && /name is missing/.test($('#bk-preview tr[data-i="2"] .bk-check').textContent), 'bulk: + Add row adds a blank row');
click($('#bk-preview tr[data-i="2"] [data-act="bulk-del-row"]'));
w.confirm = () => false; click($('[data-act="bulk-preview"]'));
ok($$('#bk-preview tbody tr').length === 2 && cell(1, 'agent').value === 'SMOKE AGENT', 'bulk: re-Preview asks before replacing edited rows');
w.confirm = () => true;
```

Then the existing create / "View them" / server-duplicate steps continue; the created vessels are `BULK A` and `BULK B` (rename the second pasted line to `bulk b` as today) — keep the cleanup list in step. Add, for admins only: change `#bk-port` after Preview and assert the duplicate mark updates (`↷` appears for `BULK A` when the port is the one it was created in, disappears for another port).

- [ ] **Step 2: Run to verify they fail** — server on 8765 against the scratch DB, `UI_TEST_PASSWORD=… node ui_smoke_test.js alex` → FAIL at "preview rows are editable".
- [ ] **Step 3: Implement** in `pages/bulk.js`: render inputs once per Preview / add / remove / apply-all; `onPreviewEdit` writes the field into `rows[i]` (`name` upper-cased; `date` clears `badDate`), runs `checkRows`, updates every row's `.bk-check` and row class plus the summary (not the inputs), and schedules the server check (300 ms debounce, clears `exists` flags then sets them from the response indexes). Re-Preview confirms when `edited` is true. "+ Add row" refuses past 200 with the existing limit message. Update the help text: "Preview, then fix anything in the table before creating."
- [ ] **Step 4: Run to verify they pass** — `node ui_smoke_test.js alex`, `admin`, `viewer` → `ALL PASSED`; `npm run test:parsing` → `ALL PASSED`; `python manage.py test sheet` → 100 OK.
- [ ] **Step 5: Checkpoint** — README Bulk add row: "paste, then edit rows in the table (dates, OPR, POC, agent), add / remove rows, set a value on all rows".
