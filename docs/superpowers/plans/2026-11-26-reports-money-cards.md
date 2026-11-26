# Visit add-another, Reports folder, Live data Excel, Dashboard money, Calculations cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user's eight points of 2026-11-26, in three pieces on three branches.

**Architecture:** Server modules work everything out (Django JSON API, `api.json_api`, scoped querysets); the
vanilla ES-module front end only draws (`dom.js` `h()`). Excel through the stdlib writer `sheet/xlsx.py`.

**Tech Stack:** Django 5.2, Python stdlib, vanilla JS, Node test scripts in `tools/`.

**Spec:** `docs/superpowers/specs/2026-11-26-reports-money-cards-design.md`

## Global Constraints

- No new library; Excel only with `sheet/xlsx.py`, pictures read by header bytes (no PIL).
- No `innerHTML` / inline `style=` attributes in templates; build screens with `dom.js`; no emoji; no help text,
  placeholders or stat cards; sidebar folder names without capitals.
- Every API view `@json_api`, vessels / visits only through `scoped_*`; page routes `require_page`; exports
  `require(profile, "exports")` + `ratelimit.check(request, "export")` + `audit(...)`.
- Money only from `finance` / `calculations.rows_for`; rounding once per sum to the cent.
- Files LF; commit with explicit paths (never `git commit -a`, never `.env.example`).
- Tests first; `cd tools && npm run check` green before asking to merge; smoke test on a scratch database.

## Review Focus

- A terminal picture that is a PNG/JPEG by signature but has a truncated header → no picture, no crash
  (Task 1 test `test_unreadable_size_is_skipped`).
- Live data Excel for a User asking `terminal=` of another port's terminal → 404, never that terminal's data
  (Task 2 test `test_other_port_terminal_404`).
- Dashboard `customer=` with a non-number or unknown id → 400 "Unknown customer." (Task 4 test).
- Money view for someone with the Dashboard page but no `money.view` → 403 (Task 5 test).
- Calculations sorted by profit where two vessels tie → newest vessel first, stable across pages (Task 7 test).

---

## Piece 1 — branch `feature/operation-extras`

### Task 1: Pictures in the Excel writer

**Files:** Modify `sheet/xlsx.py`; Test `sheet/tests_xlsx.py`

**Interfaces — Produces:**
- `xlsx.picture_size(data: bytes) -> tuple[int, int] | None` (PNG: IHDR width/height at bytes 16–24; JPEG: first
  SOF0–SOF15 marker except C4/C8/CC; anything else / truncated → None).
- `@dataclass xlsx.Picture(data: bytes, kind: str  # "png" | "jpeg", width: int, height: int, anchor: tuple  # (col, row) 0-based)`
- `Sheet.pictures: list = field(default_factory=list)`.
- `build()` writes pictures into the sheet's drawing (same `drawingN.xml` as its charts; picture anchors after the
  chart anchors), `xl/media/imageN.<png|jpeg>`, drawing rels `image` type after the chart rels, `<Default
  Extension="png" ContentType="image/png"/>` / `jpeg` → `image/jpeg` once each when used; anchor
  `xdr:oneCellAnchor` with `xdr:ext cx/cy` = pixels × 9525.

- [ ] Step 1: tests: `test_png_size` (a minimal 2×3 PNG made in the test → (2, 3)), `test_jpeg_size` (a hand-built
  SOF0 header 640×480 → (640, 480)), `test_unreadable_size_is_skipped` (`b"\x89PNG\r\n\x1a\n"` alone → None),
  `test_picture_in_workbook` (sheet with one Picture: zip has `xl/media/image1.png`, the drawing has `xdr:pic`,
  `[Content_Types].xml` has `Extension="png"`, sheet xml has `<drawing r:id="rId1"/>`), `test_chart_and_picture_share_drawing`.
- [ ] Step 2: run `venv/Scripts/python.exe manage.py test sheet.tests_xlsx` → FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run → PASS. Commit `feat(xlsx): pictures in a sheet`.

### Task 2: Live data Excel

**Files:** Modify `operation/live.py`, `operation/views.py`, `operation/urls.py`; Test `operation/tests_live.py`

**Interfaces — Consumes:** Task 1; `pictures.picture(terminal)`; `live.response(profile, port, now)`.
**Produces:**
- `live.WORKING_HEAD = ["Vessel", "Line", "Actual berth", "ATB", "Cranes", "Discharge", "Loading", "Moves/hr"]`
- `live.UPCOMING_HEAD = ["Vessel", "Line", "ETA", "LOA (m)", "Planned berth", "ETB", "ETC", "Status"]`
- `live.export_file(profile, port: str | None, terminal: str | None, now) -> bytes` (`terminal` digits → only that
  card, not one of the person's terminals → `Http404`; non-digits → `BadRequest("Choose a terminal.")`).
- `live.title_line(card) -> str`: `"{name} | Berth No. {b1 / b2} | Quay {quay:,} m | Gantry Cranes: {n}"`, parts with
  no value left out (check `terminal_to_dict` key names for quay / cranes / berths).
- View `live_export` (GET), route `api/operation/live/export/` name `api_op_live_export`: `require_page("op_live")`,
  `require("exports")`, `ratelimit.check(request, "export")`, audit `live.export`, file `Live data <date>.xlsx`
  via the module's `_xlsx_response`.
- Sheet per card: rows = title (`xlsx.Title`), muted line `Live data · DD.MM.YYYY HH:MM · Calls in 7 days: N`,
  picture rows reserved (`ceil(height_scaled / 20)` empty rows, picture scaled to width ≤ 1000 px), bold
  "Under operation", header + body rows (`looks`), or a muted "No vessels", empty row, bold "Next 7 days",
  header + rows (Status `xlsx.Status("Arrived", "info")` / `xlsx.Status("Overdue", "cancel")`… use the tones the
  page's chips match), `fit_widths`. No cards → one sheet "No data".

- [ ] Step 1: tests: `test_one_sheet_per_terminal` (two terminals → two sheet names = codes), `test_working_and_next_rows`
  (seeded working + overdue visit appear under their heads, Overdue status text), `test_one_terminal_only`,
  `test_other_port_terminal_404`, `test_needs_exports_and_page` (403 each), `test_picture_included` (with
  `override_settings(LETTERHEAD_DIR=tmp)` holding `terminals/<CODE>.png` → `xl/media/image1.png` present),
  `test_title_line`.
- [ ] Step 2: run `manage.py test operation.tests_live` → FAIL.
- [ ] Step 3: implement. Step 4: PASS. Commit `feat(operation): Live data Excel, one sheet per terminal`.

### Task 3: Front end — Live Excel button, Save and add another, Reports folder

**Files:** `sheet/templates/sheet/index.html`, `sheet/static/sheet/js/pages/opLive.js`, `js/modals/visit.js`,
`js/actions.js`, `js/tickGroups.js`, `sheet/tests_permissions.py` (if it pins the groups), `tools/ui_smoke_test.js`.

- Live data toolbar: `{% if "exports" in me.permissions %}` button `data-act="live-export"` "Excel" (icon file);
  handler downloads `/api/operation/live/export/?port=…&terminal=…` from `opLivePage.exportQuery()` (port filter +
  chosen terminal id or empty for All) through `download()`.
- Visit dialog, new visit and `can('operation.edit')`: button `btn ghost` `data-act="save-visit-another"` "Save and
  add another" before Save. `saveVisit({ again: true })`: on success reload the list and call
  `openVisitDialog(null, { terminal: <saved terminal id> })`; `openVisitDialog(id = null, { terminal } = {})`
  picks that terminal when it is in the list.
- Nav: move the `op_analysis` / `op_charts` items into the Reports folder after Calculations; Operation folder
  `{% if %}` drops them; Reports folder `{% if %}` adds them. `tickGroups.js`: move both keys to the Reports group.
- Smoke: Live data Excel button exists for admin / alex; Save and add another opens a new Add visit with the
  terminal kept (alex); Analysis reports reached from the Reports folder.

- [ ] Step 1: `tests_permissions.TickGroupsTwinTests` / `tests_page` updates first if they name the groups; run → FAIL.
- [ ] Step 2: implement; `npm run check` → green. Smoke alex / admin / viewer / suez / marine on a scratch DB.
- [ ] Step 3: docs (STATUS, CLAUDE.md Operation / Sidebar folders / xlsx, README / SECURITY counts, NEXT-CHAT);
  commit; **ask the user before merging**.

## Piece 2 — branch `feature/dashboard-money`

### Task 4: Customer filter, services per customer, OPR without money

**Files:** `sheet/dashboard.py`, `sheet/moneyaccess.py`; Test `sheet/tests_dashboard.py`, `sheet/tests_money.py`

**Produces:**
- `Filters.customer: int | str | None` (`NO_AGENT` = none); `parse` reads `customer` (digits of an existing
  Customer, or `__none__`; else `BadRequest("Unknown customer.")`).
- `_jobs(row, f)` also keeps only jobs whose `_job_customer(row, service)` equals the filter (`None` for `__none__`);
  `narrowed` becomes `agent or service or customer` set.
- `response()["filters"]["customers"] = [[id, name], …]` customers with jobs in range + port (+ OPR), by name;
  `"__none__"` not listed (the front end adds "(no customer)").
- each `customers` entry: `arrivals`, `sailings`, `by_type {type: n}`.
- `oprs` entries lose `cost_egp` / `profit_egp`; `moneyaccess.dashboard_out` no longer touches `oprs`.

- [ ] Step 1: tests `test_customer_filter_narrows_jobs`, `test_customer_none_filter`, `test_unknown_customer_400`,
  `test_customers_by_type`, `test_opr_rows_have_no_money`. Run → FAIL. Step 2: implement → PASS. Commit.

### Task 5: Money endpoint

**Files:** Create `sheet/dashmoney.py`; modify `sheet/views.py`, `sheet/urls.py`; Test create `sheet/tests_dashmoney.py`

**Interfaces — Consumes:** `dashboard.parse` (Task 4), `calculations.rows_for`, `scoped_vessels`.
**Produces:** `dashmoney.KINDS_EXTRA = ("Hotel stay", "Transfer", "Garbage & Sludge")`;
`dashmoney.response(profile, params) -> dict` as in the spec (`totals`, `by_service`, `by_customer`, `months`,
`kinds`); its own service check: `service` in `SERVICE_TYPES + KINDS_EXTRA` (so parse it before `dashboard.parse`'s
type check, or give `parse` an `extra_kinds` argument); line customer = service row `billing_party.id`, else
`vessel.ship.customer_id` (add `ship_customer_id` to `calculations._row`'s vessel dict); agent filter needs the
service's agent: add `agent` to service rows in `calculations._state`. View `dashboard_money`, route
`api/dashboard/money/` name `api_dashboard_money`: `require_page("dashboard")`, `require(profile, "money.view")`.

- [ ] Step 1: tests `test_totals_equal_calculations` (same range → same revenue / cost / profit as
  `/api/calculations/` totals), `test_by_service_includes_bookings_and_garbage`, `test_by_customer_ship_customer_for_bookings`,
  `test_customer_filter`, `test_service_filter_hotel_stay`, `test_agent_filter_drops_bookings`,
  `test_months_zero_filled`, `test_needs_money_view_403`, `test_port_user_sees_own_ports_only`. Run → FAIL.
- [ ] Step 2: implement → PASS. Commit `feat(dashboard): money figures endpoint`.

### Task 6: Dashboard front end

**Files:** `index.html` (Dashboard), `js/render/dashboard.js`, the Dashboard loader (`js/data.js` /
`actions.js` where `dash-view` lives), `js/state.js` (`dashboardFilter.customer`), `tools/ui_smoke_test.js`.

- Filter `#d-customer` ("All customers", the list, `[__none__, '(no customer)']`), sent as `customer`.
- Customers view: first panel "Services per customer" `#tbl-customer-services` (columns Arrivals / Sailings only
  without a service filter, types present, Total; Total row).
- OPR view: remove `#chart-cost` / `#chart-profit` panels and the card's cost line.
- Money tab `data-view="money"` and `<div data-dash-view="money">` only with `money.view`: `#hl-money`,
  "By service" `#chart-money-services` + `#tbl-money-services`, "By customer" `#tbl-money-customers`, "Per month
  (LE)" `#tbl-money` (moved out of Overview). Fetched from `/api/dashboard/money/` when the view is shown and on
  each filter change while shown; remembered view `money` without `money.view` → `agents`.
- Service dropdown adds `KINDS_EXTRA` while the Money view is shown; leaving it with one chosen clears the service.
- Smoke: admin sees Money with Hotel stay listed; marine (no `money.view`) has no Money tab; OPR view has no cost chart.

- [ ] Step 1: implement; `npm run check` green; smoke five roles. Step 2: docs; commit; **ask before merging**.

## Piece 3 — branch `feature/calculations-cards`

### Task 7: Calculations grouped by vessel

**Files:** `sheet/calculations.py`; Test `sheet/tests_calculations.py`, `sheet/tests_accounting.py` (callers of `rows`)

**Produces:** `calculations.VESSEL_SORTS` = date / vessel / opr / port / cost / revenue / profit (vessel sums);
`response()` returns `vessels: [{vessel, rows, cost_egp, revenue_egp, profit_egp, lines}]`, `page`, `page_size`,
`count` (vessels), `lines` (all filtered lines), `pages`, `totals`, `oprs`, `parties`; `sort=kind` → 400.
`filtered()` (export) unchanged.

- [ ] Step 1: tests `test_grouped_by_vessel`, `test_paged_by_vessel`, `test_sort_by_profit_ties_newest_first`,
  `test_kind_sort_refused`, `test_totals_cover_all_lines`; update existing tests reading `body["rows"]`. FAIL → implement → PASS. Commit.

### Task 8: Calculations cards front end

**Files:** `index.html` (Calculations), `js/pages/calculations.js`, `sheet/static/sheet/css/app.css`, `tools/ui_smoke_test.js`, `sheet/tests_page_excel.py` if it reads `COLUMNS`.

- Vessel cards like `services.js` (reuse its `sv-` classes / toggle pattern, `data-act="calc-toggle"`), line cards
  with `itemCell` / `sideCell` / `statusCell` / `accountingCell`; sort select (Date, Vessel, OPR, Port, Cost,
  Revenue, Profit + direction) replacing the table heads; open vessels kept in a `Set` across reloads.
- Keep exported `COLUMNS` (export headings) for `tests_page_excel`.
- Smoke: alex opens a vessel card, sees a line card, closes / reopens a line.

- [ ] Step 1: implement; `npm run check` green; smoke five roles. Step 2: docs; commit; **ask before merging**.
