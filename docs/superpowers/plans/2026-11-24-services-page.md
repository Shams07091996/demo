# Services Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Services" sidebar page listing services (to-do list by default: In progress) with status / missing /
date / type / agent / search / port filters, what is missing per service, a Sailed mark, a stored completed time,
and an Excel export of the filtered rows.

**Architecture:** New `sheet/services.py` (missing labels, sailed, filtering, paging, rows) behind
`GET /api/services/`; `Service.completed_at` set in the service views; a `services` sheet in `dataexport.py` (not in
All data); front end `js/pages/services.js` with the shared tick filter moved to `components.js` / `util.js`.

**Tech Stack:** Django 5.2, vanilla ES modules (dom.js), stdlib xlsx writer, Node parser tests, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-24-services-page-design.md`

## Global Constraints

- Project rules in `CLAUDE.md`: every API view `json_api`; vessels only through `access.scoped_vessels(profile,
  port)`; bad input refused (400), never fixed; money only from `finance.py`; screens only through `dom.js`; no
  `innerHTML` / inline styles; LF line endings (`write_bytes`); `npm run check` green before merge.
- Missing labels, in this order: `Agent`, `Cost`, `Revenue`, `Rate`, `Bookings`. Never for Cancelled services.
- **A typed 0 counts as filled in**; only an empty (None / absent) cost or revenue box is missing (user's decision B).
- Status filter default `in_progress`; unknown status / type → 400; page sizes like Calculations (`int_param`
  1–200, the page offers 10 / 25 / 50 / 100).
- Date range on the vessel date; when the status filter is exactly `{"completed"}`, on the completed date
  (`completed_at` Cairo date, else the vessel date). Order: vessel date, id ascending; exactly completed: completed
  moment newest first.
- `completed_at` is set only by the server: becomes completed → now; leaves completed → None; else unchanged.
- The export is `GET /api/export/services/`; the Dashboard's All data file keeps its five sheets.
- Edit roles: row click → service dialog; after save / delete from this page the dialog closes and the list reloads.
  Read-only roles: row click → the vessel dialog.
- Minimal UI text (no help paragraphs, no stat cards).

## Review Focus

1. A port user asks for `port=portsaid`: still only their port's services (scoping through `scoped_vessels`). Test:
   Task 3 `test_port_user_pinned_to_own_port`.
2. A service with cost 0 and revenue 0 typed is not missing Cost / Revenue; one with an empty box is. Multi-entry:
   one entry with an empty cost → `Cost`. Test: Task 2 `test_zero_is_filled_in_empty_is_missing`.
3. Completed-only range uses `completed_at` (and the vessel date for services completed before tracking); mixed
   statuses use the vessel date. Test: Task 3 `test_completed_range_uses_completed_date`.
4. Status flipping completed → in progress → completed: `completed_at` cleared then set again; a save that keeps
   completed keeps the time. Test: Task 1 `test_completed_at_follows_status`.
5. The list stays a fixed number of queries with many vessels / services. Test: Task 3
   `test_list_query_count_is_fixed` (`assertNumQueries` with 3 vs 12 services gives the same count).

---

### Task 1: `Service.completed_at`

**Files:**
- Modify: `sheet/models.py` (Service), `sheet/views.py` (`service_create`, `service_detail`), `sheet/serializers.py`
  (service JSON gains `completed_at` ISO or None)
- Create: `sheet/migrations/0022_service_completed_at.py` (makemigrations, then LF), `sheet/tests_services.py`

**Interfaces:**
- Produces: `Service.completed_at: DateTimeField(null=True, blank=True)`; `services.stamp_completed(service,
  old_status: str | None, now) -> None` in a new `sheet/services.py` (sets / clears / keeps per the rule).

- [ ] **Step 1: Write the failing tests** in `tests_services.py` class `CompletedAtTests(ApiTestCase)`:
  `test_new_completed_service_gets_time` (POST status completed → `completed_at` not None, within the request);
  `test_completed_at_follows_status` (in_progress → completed sets it; PUT keeping completed keeps the same value;
  → in_progress clears it; → completed again sets a new one); `test_cancelled_has_none`; `test_not_from_payload`
  (a PUT with `completed_at` in the payload is ignored: value unchanged); `test_existing_services_null_after_migration`
  is not needed (null default).
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_services` → FAIL (no field).
- [ ] **Step 3: Implement** the field, migration 0022 (`DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py
  makemigrations sheet -n service_completed_at`, convert to LF), `stamp_completed` (call in `service_create` with
  `old_status=None` and in `service_detail` with the status read before `_read_service` is applied, before
  `bump_if_changed` so the version rises with the status change only — `completed_at` changes only with status),
  serializer field.
- [ ] **Step 4: Run** the class → PASS; `manage.py makemigrations --check --dry-run` → "No changes detected".
- [ ] **Step 5: Commit** `feat(services): completed time on services`.

### Task 2: What is missing, and Sailed

**Files:**
- Modify: `sheet/services.py`; Test: `sheet/tests_services.py` class `MissingTests`

**Interfaces:**
- Produces: `services.MISSING_ORDER = ("Agent", "Cost", "Revenue", "Rate", "Bookings")`;
  `services.money_gaps(service_type: str, data: dict) -> tuple[bool, bool]` (cost missing, revenue missing);
  `services.missing(service, month_rate, incomplete_uids: set[str]) -> list[str]`;
  `services.sailed(vessel, today, now) -> bool`.
- Money boxes per type (from `validators.clean_service_data`): single types, Crew Change and Others / Remarks:
  `cost` / `revenue`; multi types (`MULTI_TYPES`): every entry's `cost` / `revenue` (no entries → both missing);
  Cash to Master: **never Cost** (it has no cost: `finance._cash_to_master` hands the rest to the master);
  Revenue missing when `amount` is empty, or `percentage` (percent mode) / `fixedRevenue` (fixed mode) is empty.
  Crew Change broken-visa amounts are not required.
- Rate: any `finance.service_lines(type, data, month_rate)` line with `rate_missing`.
- Bookings: Crew Change only; `incomplete_uids` = crew uids of this vessel's non-cancelled bookings matching
  `crewbookings._INCOMPLETE` (draft or a None money box), computed once per list (Task 3); the service is missing
  Bookings when any of its crew uids (`crewbookings._crew_uids(service)`) is in that set.
- Sailed: `vessel.sailing_at <= now`, or no `sailing_at` and `vessel.date < today`.

- [ ] **Step 1: Write the failing tests:** `test_agent_missing`; `test_zero_is_filled_in_empty_is_missing`
  (single type cost 0 / revenue 0 → []; cost None → ["Cost"]; Landing two entries, one with cost None → "Cost");
  `test_cash_to_master_boxes` (never "Cost"; amount None → "Revenue"; percent mode percentage None → "Revenue";
  fixed mode uses fixedRevenue);
  `test_rate_missing_for_usd_without_rate`; `test_crew_change_draft_booking_is_missing_bookings` (seeded through a
  Crew Change POST so `crewbookings.sync` makes drafts; saving the draft with money in the booking dialog clears it);
  `test_cancelled_never_missing`; `test_order_of_labels`; `test_sailed_rules` (sailing time past / future; none and
  date yesterday / today).
- [ ] **Step 2: Run** `manage.py test sheet.tests_services.MissingTests` → FAIL.
- [ ] **Step 3: Implement** the four functions.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(services): what a service is missing`.

### Task 3: `GET /api/services/`

**Files:**
- Modify: `sheet/services.py` (`list_response(profile, params, today, now) -> dict`), `sheet/views.py`
  (`services_list`, GET only, `json_api`), `sheet/urls.py` (`path("api/services/", …)` **before**
  `api/services/<int:pk>/`)
- Test: `sheet/tests_services.py` class `ServiceListTests`

**Interfaces:**
- Consumes: Task 2 functions; `calculations._choice_list`-style parsing (copy the helper or import it);
  `listing`'s `int_param`, the Cairo `today` used by `listing.alerts_response`.
- Produces: `services.filtered(profile, params, today, now) -> (rows: list[dict], agents: list[str])` (every
  matching row, unpaged; reused by the export) and `list_response` adding `count`, `page`, `page_size`, `pages`,
  `agents`. Row: `{id, vessel {id, name, date, port}, type, agent, status, cancel_reason, completed_at (ISO|None),
  completed_guess (bool: completed with no completed_at), sailed (bool, only True while in progress), missing
  [labels], billing, billing_party {id, name}|None}`.
- Params: `status` (comma list, default `in_progress`, unknown → 400 "Unknown status."), `missing=1`, `from`, `to`
  (ISO, bad → 400), `type` (SERVICE_TYPES, else 400 "Unknown service type."), `agent` (exact; `__none__` empty),
  `q`, `port`, `page`, `page_size`. `agents`: the distinct non-empty agents of the rows before the agent filter,
  sorted.

- [ ] **Step 1: Write the failing tests:** `test_defaults_to_in_progress_oldest_first`; `test_status_list_and_junk`;
  `test_missing_only`; `test_type_agent_none_and_search`; `test_vessel_date_range`;
  `test_completed_range_uses_completed_date` (one completed_at inside, one null with vessel date inside, one outside);
  `test_completed_only_newest_first`; `test_port_user_pinned_to_own_port`; `test_viewer_reads`;
  `test_paging_and_agents`; `test_list_query_count_is_fixed`.
- [ ] **Step 2: Run** → FAIL (404).
- [ ] **Step 3: Implement**: database narrows by port (scoped), status, type, agent and — unless completed-only — the
  vessel date; `select_related("vessel", "billing_party")`; month rates fetched once (as `calculations` does);
  incomplete crew uids for the candidate vessels in one query per booking kind (`Guest.crew_uid` via
  `guests__crew_uid`); then missing / completed-date / search filters, sort, page in Python.
- [ ] **Step 4: Run** → PASS; run the whole suite `manage.py test sheet` → OK.
- [ ] **Step 5: Commit** `feat(services): services list API`.

### Task 4: Excel export of the list

**Files:**
- Modify: `sheet/dataexport.py` (`TITLES["services"] = "Services"`, builder `_services`; **`ALL_PAGES`** = the five
  existing pages, used by `all_file`, so All data is unchanged; `PAGES` includes services for `views.data_export`)
- Test: `sheet/tests_dataexport.py` (or `tests_services.py` class `ServiceExportTests`)

**Interfaces:**
- Consumes: `services.filtered(profile, params, today, now)` (Task 3).
- Columns exactly: `Service id, Vessel id, Vessel, Port, Vessel date, Service, Agent, Status, Cancellation reason,
  Completed, Sailed, Missing, Billing party, Billing`. Completed: `xlsx.Moment` of `completed_at`, or for a guess
  `xlsx.Day` of the vessel date, empty otherwise. Sailed: "Yes" / "No". Missing: labels joined ", ".

- [ ] **Step 1: Write the failing tests:** `test_services_export_header_and_rows` (filters followed, every page, port
  user only their port); `test_all_data_still_five_sheets`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** those tests and `sheet.tests_dataexport` → PASS.
- [ ] **Step 5: Commit** `feat(services): Excel export of the services list`.

### Task 5: Shared tick filter

**Files:**
- Modify: `sheet/static/sheet/js/util.js` (export `tickSummary(title, labels, ticked)` moved from
  `pages/calculations.js`), `sheet/static/sheet/js/components.js` (export `tickFilterEl(id, name, title, labels,
  ticked)`), `pages/calculations.js` (uses them; ids stay `c-<name>-filter`), `tools/parsing_test.js`

- [ ] **Step 1: Write the failing parser tests:** `tickSummary('Status', SERVICE_LABELS, all)` → "Status: All";
  one left of three → "Status: All except Completed"; two ticked of three → "Status: In progress, Cancelled";
  one of two → "Billing: Cash".
- [ ] **Step 2: Run** `cd tools && npm run test:parsing` → FAIL (not exported).
- [ ] **Step 3: Move** the code; Calculations unchanged in behaviour.
- [ ] **Step 4: Run** parser tests → PASS.
- [ ] **Step 5: Commit** `refactor(ui): shared tick filter`.

### Task 6: The Services page

**Files:**
- Create: `sheet/static/sheet/js/pages/services.js` (`servicesPage = { load(), exportQuery(), open(id) }`)
- Modify: `templates/sheet/index.html` (nav item `data-page="services"` after Vessels with an existing sprite icon,
  `#page-services` with `#sv-ticks`, `#sv-missing`, `#sv-from`, `#sv-to`, `#sv-type`, `#sv-agent`, `#sv-q`, `#sv-port`
  (admins and readonly), Excel `data-act="page-export" data-page="services"`, `#sv-head`, `#sv-tbody`, `#sv-empty`,
  `#sv-pager`), `js/router.js` (title "Services", load), `js/actions.js` (`service-row` → open; `page-export` map
  gains `services`; `saveService` / `deleteService`: when `state.ctx.from === 'services'` → `closeModal()` then
  `servicesPage.load()` instead of `openVessel`), `js/modals/service.js` (`openServiceForm(type, service, {from})`
  keeps `from` in `state.ctx`; `reloadServiceForm` keeps it), `app.css` (row marks, missing labels).
- Test: `tools/ui_smoke_test.js` (Task 7)

**Interfaces:**
- Consumes: `GET /api/services/` (Task 3), `tickFilterEl` / `tickSummary` (Task 5), `ensureVessel`,
  `openServiceForm`, `openVessel`, `download`.
- Filters saved in `localStorage` key `services-filter` (try/catch on read and write).
- Row click: `ME.canEdit` → `ensureVessel(row.vessel.id)` then `openServiceForm(type, service, {from: 'services'})`;
  else `openVessel(row.vessel.id)` after `ensureVessel`.

- [ ] **Step 1:** Build the page (columns: Vessel, Date, Service, Agent, Status, Completed (only while Completed is
  ticked; a guess shown as "≈ dd.mm.yyyy"), Missing (labels), Sailed mark; pager 10 / 25 / 50 / 100).
- [ ] **Step 2:** `cd tools && npm run check` → green (ESLint, frontend safety tests, `tests_look` icon rules,
  `tests_speed` module list).
- [ ] **Step 3: Commit** `feat(ui): services page`.

### Task 7: Smoke test and docs

**Files:**
- Modify: `tools/ui_smoke_test.js` (nav count +1 and order `vessels,services,…`; Services page for every role:
  opens with In progress ticked and lists MSC AURORA's Crew Change with "Bookings" missing; Missing only shows
  SEA BREEZE's Landing with "Agent"; ticking only Completed + range shows completed ones with the Completed column;
  an editor's row click opens the service dialog and a save returns to the list; viewer's click opens the vessel
  dialog; Excel downloads `/api/export/services/` with the page's filters), `docs/STATUS.md`, `CLAUDE.md`
  (Services page architecture + migration 0022), `README.md` / `SECURITY.md` test counts, `docs/DEPLOYMENT.md`
  (migration 0022 note).
- [ ] **Step 1:** Extend the smoke test.
- [ ] **Step 2:** Run it on a fresh scratch DB for alex, admin, viewer, suez (`DJANGO_RATE_LIMIT_WRITES_PER_USER=300`)
  → ALL PASSED each.
- [ ] **Step 3:** Update the docs; `cd tools && npm run check` → green.
- [ ] **Step 4: Commit** `docs: services page`.
