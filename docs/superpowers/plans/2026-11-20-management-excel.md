# Management Excel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Excel button on the Dashboard downloads a nine-sheet `.xlsx` (tables + native Excel charts) for the range and port, written with the standard library only.

**Architecture:** `sheet/xlsx.py` is a generic writer (sheets of typed cells + charts → zip bytes). `sheet/report.py` works out the nine tables from the existing modules (Calculations rows for money, Dashboard rules for counts, vessel times, closures, crew data, disposal) and lays them out as `xlsx.Sheet`s. `views.dashboard_export` serves it; the Dashboard filter bar gets an Excel button that downloads through `api.download()`.

**Tech Stack:** Django 5.2, Python standard library (`zipfile`, `xml.sax.saxutils`), vanilla ES modules with `dom.js`.

**Spec:** `docs/superpowers/specs/2026-11-20-management-excel-design.md`

## Global Constraints

- Standard library only; no new package; `requirements.txt` unchanged.
- `.xlsx` (no macros, no external links); text cells are inline strings, never formulas; values starting `= + - @` stay text.
- Money from the Calculations rows only (full money: services, hotel stays, transfers, garbage & sludge); no new money maths.
- Counts follow `dashboard.py` (Crew Change = one service / one job; arrival and sailing one job each).
- Every role may download; scoped (`scoped_vessels`, `scoped_closures`); `ratelimit.check(request, "export")`; audit `dashboard.export`; no History record.
- Range required, at most 24 months: "Choose a From and To date." / "Choose a range of at most 24 months."
- No help text / placeholders in the UI (user's taste); every button `data-act`; `dom.js` only.
- LF line endings; `npm run check` green; README / SECURITY test counts, STATUS and CLAUDE.md updated (user: keep every .md current).

## Review Focus

- A range with no vessels, closures or garbage → a valid workbook whose sheets say "No data" and have no chart (Task 1 + Task 3 tests).
- A vessel / OPR / agent / reason text with markup or a leading `=` → shown literally as text in the cell (Task 1 test).
- A port user asking `port=` another port → only their port's figures (Task 4 test).
- A month in the range with nothing in it → still a row of zeros on By month (Task 2 test).
- A closure that started before the range or is still open → hours clipped to the range / counted to now (Task 3 test).

---

### Task 1: The xlsx writer

**Files:** Create `sheet/xlsx.py`, `sheet/tests_xlsx.py`

**Interfaces:**
- Produces:
  - `Bold(text: str)`, `Money(value: float)` (2 decimals, thousands), `Hours(value: float | None)` (1 decimal) — small wrappers; a plain `int` is a whole number, a plain `str` text, `None` an empty cell, a plain `float` is Money.
  - `Chart(kind: str  # "bar" | "column" | "line", title: str, categories: tuple[int, int, int]  # (first_row, last_row, col), 0-based, series: list[tuple[str, int, int, int]]  # (name, first_row, last_row, col), anchor: tuple[int, int])  # (col, row)` — a dataclass.
  - `Sheet(name: str, rows: list[list], widths: list[float], charts: list[Chart])` — a dataclass.
  - `build(sheets: list[Sheet]) -> bytes`.
  - `safe_sheet_name(name: str) -> str` (drop `[]:*?/\`, cut to 31).

- [ ] **Step 1: Write the failing tests** (`SimpleTestCase`; open the bytes with `zipfile.ZipFile(io.BytesIO(data))`):
  - `test_parts_present_and_parse` — one sheet with a chart, one without: names include `[Content_Types].xml`, `_rels/.rels`, `xl/workbook.xml`, `xl/_rels/workbook.xml.rels`, `xl/styles.xml`, `xl/worksheets/sheet1.xml`, `xl/worksheets/sheet2.xml`, `xl/worksheets/_rels/sheet1.xml.rels`, `xl/drawings/drawing1.xml`, `xl/charts/chart1.xml`; no `xl/drawings/drawing2.xml`; every `.xml` / `.rels` part parses with `xml.etree.ElementTree.fromstring`.
  - `test_numbers_are_numbers` — row `["A", 3, 12.5, xlsx.Hours(1.25)]` → sheet XML has `<v>3</v>`, `<v>12.5</v>`, `<v>1.25</v>` in cells without `t="inlineStr"`, and different `s=` style ids for int / money / hours.
  - `test_text_escaped_and_never_formula` — cells `"<b>x</b>"`, `"=1+1"`, `"@SUM(A1)"` → `&lt;b&gt;x&lt;/b&gt;` inside `<is><t>`; `t="inlineStr"` for all three; no `<f>` anywhere.
  - `test_bold_heading_style` — `xlsx.Bold("Title")` cell uses a style whose font is bold in `styles.xml`.
  - `test_chart_refers_to_its_sheet` — chart over rows 2-4 col 1 on sheet "By line" → chart XML contains `'By line'!$B$3:$B$5` and the categories ref `'By line'!$A$3:$A$5`; kind "bar" → `<c:barDir val="bar"/>`, "column" → `val="col"`, "line" → `<c:lineChart>`.
  - `test_safe_sheet_name` — `"a/b:c*d?[e]" * 3` → no forbidden characters, length ≤ 31.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_xlsx` → ImportError.
- [ ] **Step 3: Implement** `sheet/xlsx.py`: write each part with f-strings + `xml.sax.saxutils.escape` (attribute values with `quoteattr`), `zipfile.ZIP_DEFLATED`; cell refs A1-style (`_col_letter(i)`); one `<cols>` from `widths`; styles: 0 normal, 1 bold, 2 integer `#,##0`, 3 money `#,##0.00`, 4 hours `0.0`; one drawing per sheet that has charts (twoCellAnchor 8 columns × 18 rows from `anchor`), one chart part per chart; workbook rels, content types for every part.
- [ ] **Step 4: Run** the tests → pass; `venv/Scripts/python.exe -m ruff check sheet/`.
- [ ] **Step 5: Commit** `feat(excel): a standard-library xlsx writer with charts`

### Task 2: Money and count tables (sheets 1-4, 7)

**Files:** Create `sheet/report.py`, `sheet/tests_management.py`

**Interfaces:**
- Consumes: `calculations._vessel_rows` (via a new public `calculations.rows_for(vessels) -> list[dict]` that runs the loop `response` runs; `response` then uses it), `dashboard` counting (`dashboard._jobs`, `dashboard.Filters`), `serializers.vessel_to_dict`.
- Produces: `report.Range(date_from: date, date_to: date, port: str | None)` (dataclass); `report.data(profile, r: Range) -> dict[str, dict]` with keys `summary, months, lines, services, ports_perf, closures, agents, crew, disposal`; each value `{"title": str, "tables": [{"head": list[str], "rows": list[list], "total": list | None}], "notes": list[str]}`. This task fills `summary, months, lines, services, agents`; Task 3 the rest.

Table columns (exact headings):
- summary: `Port, Vessels, Services, Revenue (EGP), Cost (EGP), Profit (EGP)`, one row per port in `PORTS` order that has vessels, total row `Total`; notes `"Money includes hotels, transport and garbage & sludge."` always, `"<n> money lines used USD 1:1 (no exchange rate for that month)."` when n > 0, `"<n> garbage / sludge lines had no price."` when n > 0.
- months: `Month, Vessels, Services, Revenue (EGP), Cost (EGP), Profit (EGP)`; months `YYYY-MM` from the range's first to last month, zero-filled; total row.
- lines: table 1 `Line, Vessels, Services, Revenue (EGP), Cost (EGP), Profit (EGP)` sorted by revenue desc, empty OPR `(no line)`; table 2 `Line, Port, Vessels, Services, Revenue (EGP), Cost (EGP), Profit (EGP)`.
- services: `Service, Lines, Revenue (EGP), Cost (EGP), Profit (EGP)`: `SERVICE_TYPES` in order, then `Hotels`, `Transport`, `Garbage & Sludge` (Calculations kinds `Hotel stay`, `Transfer`, `Garbage & Sludge`); types with no lines left out; total row.
- agents: `Agent, Arrivals, Sailings, <each service type present>, Total`, busiest first, `(no agent)` last.

- [ ] **Step 1: Write the failing tests** (`ApiTestCase`; fixture in `setUpTestData`: Alexandria vessels in Oct and Dec 2026 (none in Nov), OPRs MSK / ARK / "", services with EGP and USD revenue, one Oct month rate 50 and Dec no rate, one hotel stay, one transfer, one garbage quantity with an Oct price; a Suez vessel):
  - `test_summary_equals_calculations_totals` — for admin and the whole range, summary Total revenue / cost / profit == `calculations.response(profile, {from, to})["totals"]`; notes include the hotels line and the USD 1:1 line.
  - `test_months_zero_filled` — rows are `2026-10, 2026-11, 2026-12`; November row is `["2026-11", 0, 0, 0.0, 0.0, 0.0]`.
  - `test_lines_sorted_by_revenue_and_no_line` — first column order by revenue desc; `(no line)` present for the empty OPR.
  - `test_services_include_bookings_and_garbage` — `Hotels`, `Transport`, `Garbage & Sludge` rows present; the table total equals the summary total.
  - `test_agents_match_dashboard` — the agents table equals `dashboard.response(...)["agents"]` turned into rows, `(no agent)` last.
  - `test_port_user_only_sees_their_port` — `alex` with `port="suez"` → summary has only Alexandria.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_management` → ImportError.
- [ ] **Step 3: Implement** `calculations.rows_for`, `report.Range`, `report.data` (the five tables; the other four keys return `{"title": …, "tables": [], "notes": []}` until Task 3). Vessels: `scoped_vessels(profile, r.port)` filtered by date; one pass for Calculations rows, one `vessel_to_dict` per vessel for service counts and agents.
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet.tests_management sheet.tests_calculations` → pass.
- [ ] **Step 5: Commit** `feat(excel): summary, months, lines, services and agents tables`

### Task 3: Operations tables (sheets 5, 6, 8, 9)

**Files:** Modify `sheet/report.py`, `sheet/crewbookings.py`, `sheet/tests_management.py`

**Interfaces:**
- Consumes: `constants.is_delayed`, `logistics.crew_moment` (as `crewbookings` imports it), `crewbookings.EARLY_DAYS`, closures overlap filter (as `closures.list_response`), `disposal` / Calculations rows.
- Produces: `crewbookings.early_on_signers(service) -> int` (every on-signer landing `EARLY_DAYS`+ days before the vessel date, no visa or look-back filter); fills `ports_perf, closures, crew, disposal` in `report.data`.

Tables (exact headings):
- ports_perf: table 1 `Port, Vessels with times, Avg waiting (h), Avg at berth (h), Avg in port (h), Delayed vessels` (per port); table 2 the same with `Month` first (months not split by port, zero-filled, averages `None` when no vessel has the pair); table 3 `Delay reason, Vessels`. Pairs: waiting = arrival→berthing, at berth = berthing→sailing, in port = arrival→sailing; each average over vessels that have both times; `Hours(...)` rounded to 1 decimal.
- closures: table 1 `Port, Closures, Hours closed, Still closed`; table 2 `Reason, Closures, Hours closed`. Closures overlapping the range; hours from `max(start, range start 00:00)` to `min(end or now, range end + 1 day 00:00)` (Cairo), never negative.
- crew: `Line, Crew changes, On-signers, Off-signers, Early arrivals, Broken visa revenue (EGP), Hotel nights, Transfers`; broken-visa revenue = `revenue_egp` of the Calculations rows of kind `Crew Change` whose label starts `"Broken visa"` (finance labels them `Broken visa · <name>`); hotel nights / transfers of the range's vessels' bookings (draft included); total row.
- disposal: table 1 `Port, Garbage (m³), Sludge (t), Revenue (EGP), Cost (EGP), Profit (EGP)`; table 2 the same with `Month` first, months not split by port, zero-filled. Quantities from `VesselDisposal` (hidden left out); money from the Calculations rows of kind `Garbage & Sludge`.

- [ ] **Step 1: Write the failing tests** (extend the fixture: times on two vessels — one waiting 3 h (delayed, reason "PORT CLOSED"), one 1 h; a closure from the day before the range to 12:00 on its first day; an open closure; a Crew Change with an on-signer landing 3 days early and a broken-visa revenue 20 USD at rate 50, one landing 1 day early; garbage 10 m³ / sludge 2 t on a hidden and a shown vessel):
  - `test_port_performance_averages` — Alexandria row `Avg waiting (h)` == 2.0, `Delayed vessels` == 1; reasons table `[["PORT CLOSED", 1]]`.
  - `test_closure_hours_clipped` — the closure from before the range counts 12.0 hours; the open one counts up to now and adds 1 to `Still closed`.
  - `test_crew_counts_every_early_arrival` — `Early arrivals` == 1 though a broken-visa amount is entered; `Broken visa revenue (EGP)` == 1000.0.
  - `test_disposal_hidden_left_out_and_money_matches` — garbage total 10 counts only the shown vessel; revenue equals the sum of Calculations `Garbage & Sludge` rows.
  - `test_empty_range_has_no_rows` — a range with nothing → every operations table has no rows.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_management` → the new tests fail.
- [ ] **Step 3: Implement** `crewbookings.early_on_signers` and the four tables.
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet` → all pass.
- [ ] **Step 5: Commit** `feat(excel): port performance, closures, crew and garbage tables`

### Task 4: The workbook and the endpoint

**Files:** Modify `sheet/report.py` (`workbook`), `sheet/views.py` (`dashboard_export`), `sheet/urls.py`, `sheet/tests_management.py`

**Interfaces:**
- Consumes: `xlsx.build/Sheet/Chart/Bold/Money/Hours`, `report.data`.
- Produces: `report.workbook(profile, r: Range, now: datetime) -> bytes`; route `api/dashboard/export/` name `api_dashboard_export`, GET only.

Layout per sheet: row 0 `Bold(title)`, row 1 `"<dd/mm/yyyy> to <dd/mm/yyyy> · <port label or All ports> · made <dd/mm/yyyy HH:MM>"`, a blank row, then each table (heading row in `Bold`, rows, total row in `Bold` label), a blank row between tables, then the notes; a sheet with no rows in any table shows `"No data"` and gets no chart. Sheet names: `Summary, By month, By line, Profit by service, Port performance, Port closures, Agents, Crew, Garbage & Sludge`. Charts (anchor two columns right of the widest table, row 3): Summary column profit per port (table 1, Profit column); By month line revenue / cost / profit; By line bar revenue (table 1); Profit by service bar profit; Port performance column avg waiting per port (table 1); Port closures column hours per port (table 1); Agents bar total; Crew column on- and off-signers per line; Garbage & Sludge column garbage m³ and sludge t per month (table 2). Chart ranges exclude the total row.

Endpoint: `@json_api`, GET, `ratelimit.check(request, "export")`, `from` / `to` via `listing.date_param` — missing → `BadRequest("Choose a From and To date.")`, from > to → `"From must be on or before To."`, more than 24 months (`(to.year*12+to.month) - (from.year*12+from.month) >= 24`) → `"Choose a range of at most 24 months."`; `port` passed through `scoped_vessels` / `scoped_closures` (port users pinned); `audit(request, "dashboard.export", ...)`; `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `Content-Disposition: attachment; filename="Management <All ports|port label> <from> to <to>.xlsx"` (ISO dates), `X-Content-Type-Options: nosniff`.

- [ ] **Step 1: Write the failing tests:**
  - `test_export_downloads_nine_sheets` — admin GET with a range → 200, content type as above, the zip's `xl/workbook.xml` names the nine sheets in order; `xl/charts/chart1.xml` exists.
  - `test_export_needs_a_range` — no dates → 400 "Choose a From and To date."; 25 months → 400 "Choose a range of at most 24 months."; 24 months (Jan 2025 – Dec 2026) → 200.
  - `test_export_empty_range_no_charts` — a range with no data → 200, no `xl/charts/` parts, the Summary sheet XML contains `No data`.
  - `test_export_port_user_pinned` — alex with `port=suez` → the Summary sheet has `Alexandria`, not `Suez`.
  - `test_export_read_only_allowed_and_rate_limited` — viewer → 200; with `RATE_LIMIT_EXPORTS_PER_USER=2` the third GET → 429.
  - `test_export_text_literal` — a vessel OPR `=HYPERLINK("x")` → in the By line sheet as inline string, no `<f>`.
- [ ] **Step 2: Run** → fail (404 route).
- [ ] **Step 3: Implement** `report.workbook`, the view, the route.
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet` → pass; ruff clean.
- [ ] **Step 5: Commit** `feat(excel): the management workbook and its download`

### Task 5: The Excel button

**Files:** Modify `sheet/templates/sheet/index.html` (button after `#d-service`: `<button class="btn ghost small" data-act="dashboard-export"><svg class="ic" aria-hidden="true"><use href="#i-file"></use></svg> Excel</button>`), `sheet/static/sheet/js/actions.js` (`'dashboard-export'`: builds `/api/dashboard/export/?from=&to=&port=` from the Dashboard's current From / To / port and calls `api.download(url, 'Could not make the Excel file.')`; an error goes to `setStatus('error', …)`), `tools/ui_smoke_test.js`

- [ ] **Step 1: Write the failing smoke checks** (every role, on the Dashboard after it loads): `[data-act="dashboard-export"]` exists; a direct fetch of `/api/dashboard/export/?from=<first of this month>&to=<today>` returns 200 with the spreadsheet content type; with the Dashboard on All dates, clicking the button shows `Choose a From and To date.` in the status line.
- [ ] **Step 2: Run** the smoke test for alex (fresh database, `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`, see `CLAUDE.md`) → the new checks fail.
- [ ] **Step 3: Implement** the button and the action.
- [ ] **Step 4: Run** `cd tools && npm run check`, then the smoke test for alex, admin, viewer, suez → pass.
- [ ] **Step 5: Commit** `feat(excel): Excel button on the Dashboard`

### Task 6: Docs, hand check and review

- [ ] **Step 1:** Open a generated workbook with the seeded demo data in LibreOffice headless (`soffice --headless --convert-to pdf`) if installed, else note it for the user; the file must open without a repair prompt and show the charts. Record the result.
- [ ] **Step 2:** Update `docs/STATUS.md` (where things stand: branch, no migration; built table; decisions), `CLAUDE.md` (a **Management Excel** paragraph: `xlsx.py`, `report.py`, the endpoint, money from Calculations), `README.md` / `SECURITY.md` (test counts; SECURITY: the export is scoped, rate limited, text cells never formulas).
- [ ] **Step 3:** `cd tools && npm run check` green; fresh reviewer (most capable model) on the whole branch; important findings fixed test-first; minors to STATUS "Left open".
- [ ] **Step 4: Commit** `docs: management Excel` — merge into `main` only when the user agrees.
