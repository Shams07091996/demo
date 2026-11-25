# Sidebar scroll, Services by vessel, Dashboard views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tidy sidebar scrollbar, a Services page of vessel cards that open to their services, and a Dashboard that
shows one view at a time (Agent jobs / OPR / Customers / Overview) with a donut and a heat table.

**Architecture:** Server keeps doing the work: `services.list_response` groups its filtered rows by vessel and pages
vessels; `dashboard.response` gains a `customers` block. The front end only lays out (`dom.js`, no library).

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-26-sidebar-services-dashboard-design.md`

## Global Constraints

- Branch `feature/services-dashboard-views`; `cd tools && npm run check` green before merge; merge only when the user agrees.
- Screens only through `dom.js` `h()`; no `innerHTML`, no inline `style=` attributes in templates, no emoji; colours only as `var(--…)` tokens (new tokens in light, dark and print blocks).
- Compact text: no help lines, no stat cards (user's taste).
- No change to permissions, money rules, or any Excel file's contents. Money tags only with `money.view` (already done by `moneyaccess.tags_out`).
- LF line endings.

## Review Focus

- A vessel with services both matching and not matching the filters: only the matching ones show inside its card (Task 2 test).
- Paging counts vessels, not services; a page past the end clamps as today (Task 2 test).
- A service whose billing party differs from its ship's customer counts for the billing party (Task 4 test).
- A vessel without a ship (old vessels) and empty POC: "No customer" / empty POC, not a crash (Task 4 test).
- Only Completed ticked: vessels newest first by completed date (Task 2 test).

---

### Task 1: Sidebar scrollbar

**Files:** Modify `sheet/static/sheet/app.css:37` (`.nav`).

- [ ] Add to `.nav`: `scrollbar-width:thin; scrollbar-color:var(--side-active) transparent`, plus
  `.nav::-webkit-scrollbar{width:6px}`, `.nav::-webkit-scrollbar-thumb{background:var(--side-active);border-radius:3px}`,
  `.nav::-webkit-scrollbar-track{background:transparent}`.
- [ ] Run `venv/Scripts/python.exe manage.py test sheet.tests_look` → OK.
- [ ] Check in the browser pane on a scratch server (seed_demo), all folders open, light and dark: thin navy-toned bar, no white track.
- [ ] Commit `style(sidebar): thin scrollbar in the sidebar colours`.

### Task 2: Services list grouped by vessel (server)

**Files:** Modify `sheet/services.py` (`_row`, `list_response`, new `grouped`); Test `sheet/tests_services.py` (`ServiceListTests`).

**Interfaces — Produces:** `GET /api/services/` →
`{"vessels": [{"vessel": {id, name, date, port, opr, terminal, berth}, "services": [row, …]}], "count": <vessels>,
"services_count": <services>, "page", "page_size", "pages", "agents"}`. Each `row` as today (its `vessel` gains
`opr`, `terminal`, `berth`). `services.grouped(rows) -> list[dict]` keeps the rows' order: vessels in order of their
first row. `filtered()` unchanged (the export uses it).

- [ ] Update `ServiceListTests.ids()` to flatten `[r["id"] for g in body["vessels"] for r in g["services"]]`; existing tests must then pass unchanged.
- [ ] New tests:
  - `test_grouped_by_vessel_matching_only`: alex_vessel has an in_progress and a completed service, `old` one in_progress → `[g["vessel"]["name"] for g in vessels] == ["OLD ONE", alex_vessel.name]`, alex group has only the in_progress id, `count == 2`, `services_count == 2`.
  - `test_pages_count_vessels`: 3 vessels × 2 services, `page_size=2` → `count == 3`, `pages == 2`, page 1 has 2 vessels / 4 services.
  - `test_only_completed_newest_vessel_first`: two vessels each with a completed service, completed_at different → newer vessel first.
  - `test_vessel_carries_opr_terminal_berth`.
- [ ] Run `venv/Scripts/python.exe manage.py test sheet.tests_services` → new tests FAIL.
- [ ] Implement `grouped` and the new `list_response` (page the groups).
- [ ] Run → PASS. Commit `feat(services): the list comes grouped by vessel, paged by vessel`.

### Task 3: Services page as vessel cards (front end)

**Files:** Modify `sheet/static/sheet/js/pages/services.js`, `sheet/templates/sheet/index.html:~245-255` (replace the
table with `<div id="sv-cards"></div>`, keep `#sv-empty`, `#sv-pager`), `sheet/static/sheet/app.css`,
`sheet/tests_page_excel.py` only if the heads lookup moves, `tools/ui_smoke_test.js:466-505`.

**Interfaces — Consumes:** Task 2's response.

- [ ] Keep the export headings in services.js as a top-level `const heads = ['Vessel', 'Date', 'Service', 'Agent', 'Status', 'Completed', 'Missing'];` — whatever form `tests_page_excel.heads_statement` must still read and equal `dataexport.COLUMNS["services"]` (check it, adjust the constant's shape to match what is there today, the `withCompleted` part included).
- [ ] Card (`vesselCardEl(group)`): `article.sv-vessel` with a head button `data-act="sv-toggle" data-id=<vessel id>`: name, port label (only `ME.multiPort`), terminal / berth, `dmy(date)`, OPR, "N services" (`1 service`), a `missing-tag` "Missing" when any service has `missing.length`, arrow icon (`icon('chevron')` or the existing one used by nav groups). Body (`hidden` unless open): one `div.sv-svc` per service, `data-act="service-row" data-id=<service id>` (so the existing open-handler keeps working): type, `serviceStatusEl`, Sailed tag, agent or "—", completed cell when Completed is ticked, missing tags.
- [ ] Open set: module `Set` of vessel ids, kept across reloads of the page, cleared of ids no longer listed; register `sv-toggle` in `actions.js`.
- [ ] Pager noun `vessels`; `byId` still maps service ids → rows.
- [ ] CSS: `.sv-vessel` card (10 px corners, `--card-shadow`, like `.panel`), head grid, `.sv-svc` small cards in a wrap grid; phone width stacks.
- [ ] Smoke test: `svRow(vessel, type)` finds `.sv-svc` inside the card whose name matches (open the card first by clicking its `sv-toggle`); "ticking Completed adds the Completed column" becomes "… shows the completed date" on the service card; add `services: a vessel card opens to its services`.
- [ ] Run `cd tools && npm run check` (incl. dom tests) and the smoke test for alex, admin, viewer, marine on a fresh scratch DB → all pass.
- [ ] Commit `feat(services): vessels as cards that open to their services`.

### Task 4: Dashboard customers block (server)

**Files:** Modify `sheet/dashboard.py` (`response`, new `_customers(vessels)`); Test `sheet/tests_dashboard.py` (new class `DashboardCustomerTests`).

**Interfaces — Produces:** `response()["customers"]` = list sorted by jobs desc then name, "No customer" last:
`{"id": int|None, "name": str ("No customer" when None), "jobs": int, "places": [{"poc": str, "port": str (key), "jobs": int}]}`
(places sorted by jobs desc, then poc, port). A job counts once: service job → `service["billing_party"]["id"]` if set,
else `row["ship"]["customer_id"]`; arrival / sailing → `row["ship"]["customer_id"]`; `row["ship"]` None → None. Uses the
same filtered `vessels` / jobs as the agent figures (OPR, agent, service filters apply). Names: one
`Customer.objects.filter(id__in=…)` query. Counts only.

- [ ] Tests (make Customers A and B, a Ship of A linked to V1 with POC "P1"; V1's Fresh Water billed to B):
  - `test_jobs_go_to_billing_party_else_ship_customer`: A gets arrival + sailing + Crew Change = 3, B gets 1.
  - `test_places_by_poc_and_port`: A's places `[{"poc": "P1", "port": "alexandria", "jobs": 3}]`.
  - `test_vessel_without_ship_is_no_customer_last`: V2 (no ship) → last entry `{"id": None, "name": "No customer", "jobs": 1, …}` with poc "".
  - `test_service_filter_narrows_customers`: `&service=Fresh Water` → only B with 1.
  - `test_port_user_sees_own_port_only` (a Port Said vessel's customer absent for `alex`).
- [ ] Run → FAIL; implement; run `manage.py test sheet.tests_dashboard` → PASS.
- [ ] Commit `feat(dashboard): jobs per customer by POC and port`.

### Task 5: Dashboard views (front end)

**Files:** Modify `sheet/templates/sheet/index.html:436-470` (page-dashboard), `sheet/static/sheet/js/render/dashboard.js`,
`sheet/static/sheet/js/actions.js`, `sheet/static/sheet/app.css`, `tools/ui_smoke_test.js`.

**Interfaces — Consumes:** Task 4's `customers`; existing `state.dashboard`.

- [ ] Template: under the toolbar a `div.view-tabs` with four buttons `data-act="dash-view" data-view="agents|opr|customers|overview"`
  (Agent jobs · OPR · Customers · Overview); wrap panels in `<div data-dash-view="…">`: agents = Jobs per agent; opr =
  `#chart-vessels` (now the donut) + new `#tbl-opr` + `#opr-cards` (Services / cost / profit per OPR bars stay here too);
  customers = new `#tbl-customers` and `#heat-customers`; overview = Services per month, Money per month, Service status.
  Each view starts with `<div class="dash-headline" id="hl-…"></div>`.
- [ ] `dashView` in render/dashboard.js: read/write `localStorage['sheet.dashboard.view']` in try/catch, default `agents`;
  `showView(view)` sets `hidden` on the other `[data-dash-view]`, `aria-pressed` on the tab, and hides filters not used
  (`#d-agent` hidden on customers; `#d-opr` hidden on opr). Changing view does not reload data.
- [ ] Headlines (one line, `fmt` numbers): agents "N jobs · N agents · busiest: X"; opr "N vessels · N services · N OPRs";
  customers "N jobs · N customers"; overview "N services".
- [ ] `donutEl(items: [{label, value}], {act})` → SVG via `document.createElementNS` in a small new `js/render/svgChart.js`
  (circle segments with `stroke-dasharray`, colours `CHART_COLORS`, more than 8 → top 7 + "Other"), plus a legend list
  `label — value (pct%)`; clicking a slice / legend item keeps `data-act="opr-summary"`. Must pass `tests_frontend_safety`
  (attributes set with `setAttribute`, no strings of markup).
- [ ] `#tbl-opr`: `figTable(['OPR', 'Vessels', 'Services'], …)`.
- [ ] `#tbl-customers`: `figTable(['Customer', 'Jobs'], …)`. `#heat-customers`: rows = customer + POC (`(no POC)` for ""),
  columns = ports present (port labels via `PORT_LABEL`; a single column "Jobs" when not `ME.multiPort`), cell text = jobs,
  class `heat-1`…`heat-5` by jobs ÷ max (CSS tokens `--heat-1…5` mixing `--accent` into the card colour, light / dark / print).
- [ ] Smoke test (admin and alex): the four tabs show; clicking Customers shows `#tbl-customers` with "Blue Owners" (seed_demo ship customer) and hides `#chart-agents`; reload keeps Customers; OPR shows an `svg` in `#chart-vessels`.
- [ ] Run `cd tools && npm run check` and the smoke runs (alex, admin, viewer, suez, marine) on a fresh scratch DB → pass.
- [ ] Look at it in the browser pane, light and dark, desktop and phone width.
- [ ] Commit `feat(dashboard): one view at a time, OPR donut, customers by POC and port`.

### Task 6: Docs and final check

- [ ] Update `docs/STATUS.md` (what was built, the calls made: billing party first; customer × POC rows), `CLAUDE.md`
  (**Services page**: grouped response; **Dashboard**: views + `customers`), `README.md` / `SECURITY.md` test counts.
- [ ] `cd tools && npm run check` → green. Commit `docs: services by vessel, dashboard views`.
- [ ] Fresh whole-branch review, then ask the user about merging.
