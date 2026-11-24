# Data export (Excel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plain-table Excel files of Hotels, Transport, Port closures, Garbage & Sludge and Calculations: one per page
(that page's current filters) and one "All data" file with the five sheets.

**Architecture:** New `sheet/dataexport.py` turns each page's already-filtered rows (the same functions the page's
list request uses, without paging) into an `xlsx.Sheet` with a fixed header; `xlsx.py` gains date / date-time cells.
Two GET views download the files; each page and the Dashboard get a button that calls `api.download`.

**Tech Stack:** Django 5.2, standard library `xlsx.py`, vanilla ES modules, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-24-data-export-design.md`

## Global Constraints

- No new library; text cells stay inline strings (never formulas) — `xlsx._cell` already does this.
- Every role may export; vessels only through `access.scoped_vessels`, closures through `access.scoped_closures`
  (port users pinned to their port whatever `port` they send).
- `ratelimit.check(request, "export")` on both views; `api.audit(request, "data.export", page=…, …)`.
- The header row of each sheet is fixed (below), whatever the data; no rows → header alone. No titles / totals / notes.
- Screens only with `dom.js`; buttons carry `data-act`; no help text (the user keeps screens lean).
- LF line endings; `npm run check` green before merge; README / SECURITY test counts, STATUS, CLAUDE.md, DEPLOYMENT
  (no migration) updated.

## Columns (exact header text, in order)

- **Hotels:** Booking id, Vessel id, Vessel, Port, Guests, Hotel, Check-in, Nights, Check-out, Cost per night,
  Cost currency, Revenue per night, Revenue currency, Exchange rate, Draft, Cancelled, Accounting
- **Transport:** Booking id, Vessel id, Vessel, Port, Guests, From, To, Airport, Hotel, Port name, Date & time, Cost,
  Cost currency, Revenue, Revenue currency, Exchange rate, Draft, Cancelled, Accounting
- **Port closures:** Closure id, Port, Closed from, Reopened, Hours, Reason, Notes
- **Garbage & Sludge:** Vessel id, Vessel, Date, OPR, Port, Garbage m³, Sludge t, Hidden, Revenue EGP, Cost EGP,
  Profit EGP, Revenue USD, Cost USD, Profit USD, Rate missing, Price missing, Accounting
- **Calculations:** Vessel id, Vessel, Vessel date, OPR, Port, Item, Line, Note, Record, Record id, Cost, Cost currency,
  Revenue, Revenue currency, Cost EGP, Revenue EGP, Profit EGP, Cost USD, Revenue USD, Profit USD, Rate source,
  Rate missing, Price missing, Status, Cancellation reason, Accounting

Value rules: Port = port label ("Alexandria"); Guests = names joined with "; "; Check-in / Check-out / Date / Vessel
date = `xlsx.Day`; Date & time / Closed from / Reopened = `xlsx.Moment` (Cairo local time); money and rates = float or
empty; Nights / ids = int; Draft / Cancelled / Hidden / Rate missing / Price missing = bool (written Yes / No);
Accounting = "Open" / "Closed" ("" for a garbage & sludge row with no record); Status = the label from
`constants.SERVICE_STATUSES` ("" when none); Calculations Item = row `kind`, Record / Record id = `ref` kind / id
(empty when `ref` is None), Cost / Revenue = the side's rounded amount, currency from the side (empty when no side);
From / To = place labels as on the Transport page (`logistics._place`); Rate source = "own" / "month" / "".

## Review Focus

1. A port user asking `?port=suez` (or All data with another port) gets only their own port. Test:
   `test_port_user_gets_only_their_port` (both views).
2. Text that looks like a formula (`=HYPERLINK(...)`, `+1`, `@x`) in a guest name / note is written as a plain string.
   Test: `test_formula_text_stays_text`.
3. A page's filters are honoured exactly as on its list (search, status / accounting ticks, show filter, sort); more
   than one page of rows is all exported. Test: `test_page_file_has_every_filtered_row`.
4. Bad page names / bad dates → 400 JSON, not 500. Test: `test_bad_requests`.
5. Empty result → header row only, same columns. Test: `test_empty_has_header_only`.

---

### Task 1: Date and date-time cells in `xlsx.py`

**Files:** Modify `sheet/xlsx.py`; Test `sheet/tests_xlsx.py`

**Interfaces — Produces:** `xlsx.Day(value: date | None)`, `xlsx.Moment(value: datetime | None)` (frozen dataclasses;
None → empty cell). A Moment that is timezone-aware is converted to Cairo local time first. Both written as Excel
serial numbers (days since 1899-12-30, fraction for the time) with new styles: Day `dd/mm/yyyy` (built-in numFmt 14
is locale-dependent, so a custom numFmt), Moment `dd/mm/yyyy hh:mm`; style indexes appended after HOURS.

- [ ] **Step 1: failing tests** `test_day_cell` (date(2026, 11, 24) → `<v>46350</v>` with the Day style), `test_moment_cell`
  (aware 2026-11-24 08:00 UTC → Cairo 10:00 → `<v>46350.416666666664</v>` or rounded repr equal to
  `46350 + 10/24`), `test_empty_day_and_moment` (None → no `<c>`), and the stylesheet counts still match the xf list.
- [ ] **Step 2:** run `venv/Scripts/python.exe manage.py test sheet.tests_xlsx` → FAIL (no `Day`).
- [ ] **Step 3:** implement in `_cell` and the styles XML.
- [ ] **Step 4:** run again → PASS; whole `sheet.tests_xlsx` and `sheet.tests_management` green.
- [ ] **Step 5:** commit `feat(xlsx): date and date-time cells`.

### Task 2: `dataexport.py` sheets

**Files:** Create `sheet/dataexport.py`; Modify `sheet/logistics.py`, `sheet/calculations.py` (split the unpaged rows
out); Test `sheet/tests_dataexport.py`

**Interfaces:**
- Consumes: `logistics.parse_params / scoped / _in_range / booking_to_dict`, `closures.list_response`,
  `disposal.response`, `calculations.parse_params / rows_for`, `xlsx.Sheet / Day / Moment`.
- Produces: `logistics.filtered_rows(kind, profile, params) -> list[dict]` (search + sort, no paging; `list_response`
  pages it); `calculations.filtered_rows(profile, params) -> (rows, oprs)` (`response` uses it);
  `dataexport.PAGES = {"hotels", "transfers", "closures", "disposal", "calculations"}` (order = All data sheet order;
  titles "Hotels", "Transport", "Port closures", "Garbage & Sludge", "Calculations");
  `dataexport.sheet(page, profile, params) -> xlsx.Sheet`; `dataexport.page_file(page, profile, params) -> bytes`;
  `dataexport.all_file(profile, date_from, date_to, port) -> bytes` (each sheet = that page with
  `{from, to, port}`, i.e. each page's own date meaning: stays covering a night in the range, trips on a day in it,
  closures overlapping it, vessel dates for Garbage & Sludge and Calculations; Garbage & Sludge with `show=all`).
  The objects behind `booking_to_dict` are needed for Day / Moment values: build rows from the model objects
  (keep `booking_to_dict` for the page) — the builder's choice how, as long as both share one filter.

- [ ] **Step 1: failing tests** (on `ApiTestCase` fixtures, reading the bytes back with `zipfile` + the sheet XML):
  `test_headers_fixed` (each page's header row equals the Columns list), `test_empty_has_header_only`,
  `test_page_file_has_every_filtered_row` (250 hotel stays matching `q`, page_size default → 250 data rows; a
  Calculations `status=cancelled` filter → only cancelled lines), `test_formula_text_stays_text` (guest
  `=HYPERLINK("x")` → `t="inlineStr"`, no `<f>`), `test_values_typed` (Check-in is a Day number, money a number, Guests
  "A; B", Accounting "Closed" for a closed stay, port label), `test_all_file_has_five_sheets` (sheet names in order).
- [ ] **Step 2:** run `venv/Scripts/python.exe manage.py test sheet.tests_dataexport` → FAIL (no module).
- [ ] **Step 3:** implement; existing `tests_logistics` / `tests_calculations` stay green (the list responses unchanged).
- [ ] **Step 4:** run `sheet.tests_dataexport sheet.tests_logistics sheet.tests_calculations sheet.tests_closures sheet.tests_disposal` → PASS.
- [ ] **Step 5:** commit `feat(export): data sheets`.

### Task 3: Download views

**Files:** Modify `sheet/views.py`, `sheet/urls.py`; Test `sheet/tests_dataexport.py`

**Interfaces — Produces:** `GET /api/export/<page>/?<that page's list query>` (`views.data_export`, name
`api_data_export`; unknown page → 404 JSON) and `GET /api/export/all/?from=&to=&port=` (`views.data_export_all`, name
`api_data_export_all`; route before `<page>`; From / To required, From ≤ To, at most 24 months — the same messages as
`dashboard_export`, shared through one helper). Both: `@json_api`, GET only, `ratelimit.check(request, "export")`,
`audit(request, "data.export", page=page or "all", …)`, XLSX content type, `X-Content-Type-Options: nosniff`, file names
`"<Title> <today>.xlsx"` and `"All data <port label> <from> to <to>.xlsx"`.

- [ ] **Step 1: failing tests** `test_page_download` (200, content type, attachment name, audit record),
  `test_all_download`, `test_port_user_gets_only_their_port` (alex with `port=suez` → only Alexandria rows, both views),
  `test_bad_requests` (unknown page 404, all without dates 400, 25 months 400, bad date 400), `test_export_rate_limited`
  (the export counter refuses after its limit, as in `tests_ratelimit`), `test_viewer_may_export`.
- [ ] **Step 2:** run → FAIL (404 routes).
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run `sheet.tests_dataexport` → PASS; full `manage.py test sheet` green.
- [ ] **Step 5:** commit `feat(export): download views`.

### Task 4: Buttons and smoke test

**Files:** Modify `sheet/templates/sheet/index.html` (an **Excel** button in each of the five pages' filter bars,
`data-act="page-export" data-page="<page>"`; an **All data** button beside the Dashboard's Excel button,
`data-act="dashboard-data-export"`), `sheet/static/sheet/js/actions.js`, each page module's exported query builder
(`pages/bookings.js`, `pages/closures.js`, `pages/disposal.js`, `pages/calculations.js`: a `query()` returning the same
`URLSearchParams` its load uses, minus `page` / `page_size`), `tools/ui_smoke_test.js`.

**Interfaces — Consumes:** `api.download(url, message)` (returns an error message or null), the views of Task 3.

- [ ] **Step 1:** smoke steps (every role): each page's Excel button requests `/api/export/<page>/` with that page's
  current filters (record the fetched URL, as the Dashboard Excel check does) and gets a 200 `.xlsx`; All data
  requests `/api/export/all/` with the Dashboard's From / To / port; All data without dates shows the error.
- [ ] **Step 2:** implement; `npm run check` green.
- [ ] **Step 3:** fresh throwaway database (`fresh_db.sh`), server with `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`, smoke
  for alex / admin / viewer / suez → ALL PASSED.
- [ ] **Step 4:** commit `feat(ui): Excel buttons for page data`.

### Task 5: Docs and review

STATUS (where things stand, decisions: "export, not import"; both files), CLAUDE.md (a **Data export** paragraph),
README / SECURITY test counts, DEPLOYMENT (no migration). Fresh opus whole-branch review; Critical / Important fixed
test-first. Commit `docs: data export`.
