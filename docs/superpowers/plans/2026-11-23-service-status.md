# Service Status and Accounting Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operations mark each service In progress / Completed / Cancelled; accounting (read-only accounts) mark each
Calculations row Open / Closed; a Closed row is locked; counts on Dashboard and Excel.

**Architecture:** New fields on `Service` (status, reason, closed) and `acct_closed` on `HotelStay`, `Transfer`,
`VesselDisposal`; a new module `sheet/accounting.py` owns the accounting endpoint, the lock and the counts; existing
modules (crewbookings, listing, calculations, dashboard, report) learn to skip cancelled services and to carry /
filter the two statuses; the front end shows labels, a switch and tick-box filters.

**Tech Stack:** Django 5.2, vanilla ES modules (`dom.js`), Django test runner, `tools/ui_smoke_test.js`.

**Spec:** `docs/superpowers/specs/2026-11-23-service-status-design.md`

## Global Constraints

- Branch `feature/service-status` from `main`; commit per task (Conventional Commits, Co-Authored-By line).
- Values: status `in_progress` | `completed` | `cancelled`; labels "In progress" / "Completed" / "Cancelled";
  accounting "Open" / "Closed". Reason max 500 characters, required when Cancelled, refused otherwise.
- Lock message exactly: "Accounting has closed this. Ask accounting to reopen it first." (400, every role).
- Accounting writes: admins and role `readonly` only; scoped through `access.scoped_vessels`; rate limited; one
  transaction; audited; never raise `version`; `acct_closed` is never written by operations saves.
- Input refused, never silently fixed; money rules (`finance.py`, `logistics.booking_line`, `disposal`) unchanged.
- Front end only through `dom.js`; colours only from tokens (`--warning`, `--success`, `--muted`); no inline styles;
  no new library.
- LF line endings; README / SECURITY test counts, STATUS, CLAUDE, DEPLOYMENT updated in the last task.

## Review Focus

1. A stale operations dialog (opened before accounting closed the row) saves: must get the lock 400, not overwrite.
   Test: Task 2 `test_stale_service_save_after_close_is_refused`.
2. Deleting a vessel whose garbage / sludge only (no services) is Closed: refused. Test: Task 2 `test_vessel_delete_refused_when_disposal_closed`.
3. A port user posts to `/api/accounting/` for another port's row, or a read-only user for any row: 403 / 404 vs 200.
   Test: Task 2 `test_accounting_rights_and_scope`.
4. A cancelled Crew Change whose draft booking accounting had Closed (a draft with money): the draft is kept, not
   deleted. Test: Task 3 `test_cancel_keeps_closed_drafts`.
5. Calculations `status=` / `accounting=` with junk (`status=done`, `accounting=`, repeated commas): 400 for unknown
   values, empty items ignored. Test: Task 4 `test_filter_values_refused`.

---

### Task 1: Status fields, validation, API shape

**Files:**
- Modify: `sheet/models.py`, `sheet/constants.py`, `sheet/validators.py`, `sheet/views.py` (`_read_service`, `service_create`, `service_detail`), `sheet/serializers.py` (`service_to_dict`), `sheet/conflicts.py` (`UNTRACKED`), `sheet/logistics.py` (`booking_to_dict`), `sheet/disposal.py` (`row`)
- Create: `sheet/migrations/0019_service_status.py`, `sheet/tests_service_status.py`

**Interfaces:**
- Produces: `constants.SERVICE_STATUSES = {"in_progress": "In progress", "completed": "Completed", "cancelled": "Cancelled"}`;
  `Service.status` (CharField 12, default `"in_progress"`), `Service.cancel_reason` (CharField 500, blank),
  `acct_closed` BooleanField default False on Service, HotelStay, Transfer, VesselDisposal;
  `validators.clean_service_status(payload) -> (status, reason)`; service JSON gains `status`, `cancel_reason`,
  `closed`; booking and disposal row JSON gain `closed`. `"acct_closed"` added to `conflicts.UNTRACKED`.
- Migration: add fields with default `in_progress`, then a data step setting every existing service to `completed`.

- [ ] **Step 1: Write the failing tests** (`ApiTestCase`):
  - `test_new_service_starts_in_progress` (POST without status → `"in_progress"`, `closed` False).
  - `test_status_saved_and_returned` (PUT `status: "completed"` → saved).
  - `test_cancel_needs_reason` (`cancelled` without reason → 400; with "Weather" → saved with reason).
  - `test_reason_refused_unless_cancelled` (`completed` + reason → 400).
  - `test_unknown_status_refused` (`"done"` → 400); `test_reason_too_long_refused` (501 chars → 400).
  - `test_status_change_raises_version` (version +1; History record names `status`).
  - `test_existing_services_become_completed` (migration test via `MigrationExecutor` 0018 → 0019, like other migration tests in the project).
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_service_status` → fail.
- [ ] **Step 3: Implement** the fields, migration, constant, `clean_service_status` (missing key on PUT keeps the current status / reason, like the delay-reason rule), wiring in the views and serializers.
- [ ] **Step 4: Run** `manage.py test sheet` → all pass; `DJANGO_DEBUG=1 manage.py makemigrations --check --dry-run` → no changes.
- [ ] **Step 5: Commit** `feat(services): operations status with cancellation reason`.

### Task 2: Accounting switch and the lock

**Files:**
- Create: `sheet/accounting.py`, `sheet/tests_accounting.py`
- Modify: `sheet/access.py`, `sheet/urls.py`, `sheet/views.py` (`accounting_set` view; lock calls in `service_detail`, `booking_detail`, `disposal_update`, `vessel_detail` DELETE), `sheet/crewbookings.py` (`sync` never changes or deletes an `acct_closed` booking)

**Interfaces:**
- Produces: `access.require_accounting(profile)` (admin or role `readonly`, else `Forbidden("Only accounting can change this.")`);
  `accounting.KINDS = {"service": Service, "hotel": HotelStay, "transfer": Transfer, "disposal": VesselDisposal}`;
  `accounting.set_closed(profile, kind, pk, closed) -> obj` (scoped get, 404 outside scope, `save(update_fields=["acct_closed"])`);
  `accounting.require_open(obj)`; `accounting.require_vessel_open(vessel)` (any Closed service / booking / disposal);
  `LOCKED = "Accounting has closed this. Ask accounting to reopen it first."`;
  `POST /api/accounting/` body `{"kind", "id", "closed"}` → `{"ok": true, "closed": bool}`; audit `accounting.close` / `accounting.open`.

- [ ] **Step 1: Write the failing tests**:
  - `test_readonly_and_admin_can_close`, `test_port_user_cannot_close` (403), `test_accounting_rights_and_scope` (unknown kind / id → 400 / 404).
  - `test_close_does_not_raise_version` and records History (`acct_closed` False → True).
  - `test_closed_service_edit_and_delete_refused` (PUT and DELETE → 400 with `LOCKED`, for admin too); `test_reopened_service_can_be_edited`.
  - `test_stale_service_save_after_close_is_refused`.
  - `test_closed_booking_edit_and_delete_refused`; `test_closed_disposal_change_refused` (quantities and `hidden`).
  - `test_vessel_delete_refused_when_service_closed`, `test_vessel_delete_refused_when_disposal_closed`; `test_vessel_times_edit_allowed_when_closed`.
  - `test_sync_never_touches_closed_booking` (closed draft keeps its fields when the member changes or goes away).
  - `test_accounting_is_rate_limited` (counts as a write, like other writes in `tests_ratelimit`).
- [ ] **Step 2: Run** `manage.py test sheet.tests_accounting` → fail.
- [ ] **Step 3: Implement**; lock checks run after `conflicts.locked` re-reads the row (so a stale dialog sees the fresh flag).
- [ ] **Step 4: Run** `manage.py test sheet` → all pass.
- [ ] **Step 5: Commit** `feat(accounting): open / closed switch and the lock`.

### Task 3: What Cancelled does outside the money

**Files:**
- Modify: `sheet/crewbookings.py` (`crew_members` skips cancelled services; `early_arrivals` excludes them), `sheet/listing.py` (`missing_details` ignores cancelled services' agents)
- Test: `sheet/tests_service_status.py`

**Interfaces:**
- Consumes: `Service.status` (Task 1), the closed-booking rule (Task 2).

- [ ] **Step 1: Write the failing tests**:
  - `test_cancel_deletes_drafts_keeps_saved` (two drafts + one saved booking; cancel → drafts gone, saved kept).
  - `test_uncancel_brings_drafts_back`.
  - `test_cancel_keeps_closed_drafts`.
  - `test_cancelled_service_raises_no_alerts` (no `early`, no "<type> agent" in `missing`).
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `manage.py test sheet` → pass.
- [ ] **Step 5: Commit** `feat(services): cancelled services drop drafts and alerts`.

### Task 4: Calculations rows, filters and counts

**Files:**
- Modify: `sheet/calculations.py`
- Test: `sheet/tests_calculations.py`

**Interfaces:**
- Produces: each row gains `status` (str or None), `cancel_reason`, `closed` (bool), `ref` `{"kind", "id"}` (disposal: vessel's `VesselDisposal` id; a row whose disposal does not exist yet cannot be closed: `ref` None);
  params `status` / `accounting` (comma lists; unknown → `BadRequest`; when `status` is given, rows with `status` None are left out);
  totals gain `open`, `closed` (row counts after filters). `calculations.rows_for` unchanged in signature.

- [ ] **Step 1: Write the failing tests**: `test_rows_carry_status_and_closed`, `test_status_filter_all_except_completed`, `test_status_filter_drops_bookings`, `test_accounting_filter_open`, `test_totals_follow_filters_with_counts`, `test_filter_values_refused`, `test_multi_entry_service_rows_share_closed`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `manage.py test sheet` → pass.
- [ ] **Step 5: Commit** `feat(calculations): status and accounting columns and filters`.

### Task 5: Counts on the Dashboard and the management Excel

**Files:**
- Modify: `sheet/dashboard.py` (`response` gains `"status"`), `sheet/report.py` (new sheet "Service status")
- Test: `sheet/tests_dashboard.py`, `sheet/tests_xlsx.py`

**Interfaces:**
- Produces: `response()["status"] = {"months": [{"month": "YYYY-MM", "in_progress", "completed", "cancelled", "open", "closed"}], "totals": {same keys}}` — service counts from the services the dashboard counts (agent / service filters narrow them), open / closed from `calculations.rows_for` of the same vessels; months zero-filled like `months`. Workbook: ten sheets, "Service status" table head `["Month", "In progress", "Completed", "Cancelled", "Open", "Closed"]` with a total row.

- [ ] **Step 1: Write the failing tests**: `test_status_counts_per_month`, `test_status_counts_follow_agent_filter`, `test_workbook_has_service_status_sheet`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `manage.py test sheet` → pass (update any test that counted nine sheets).
- [ ] **Step 5: Commit** `feat(dashboard): service and accounting status counts`.

### Task 6: Screens

**Files:**
- Modify: `sheet/static/sheet/js/modals/service.js` (Status select beside Agent, `#svc-reason` field shown only for Cancelled, zero money inputs on choosing Cancelled, send `status` / `cancel_reason`), `js/modals/vessel.js` (label + reason + "Closed by accounting" on the card), `js/render/list.js` and `js/modals/summary.js` (amber "N in progress" tag), `js/pages/bookings.js` and `js/pages/disposal.js` ("Closed by accounting" note), `js/pages/calculations.js` (Status and Accounting columns; switch posts `/api/accounting/` for `ME.isAdmin || ME.role === 'readonly'`, plain label otherwise; tick-box filters as `<details>` with checkboxes, sent as `status=` / `accounting=`; totals "Open N · Closed N"), `js/render/dashboard.js` (Service status table), `js/actions.js` (new `data-act` names), `sheet/static/sheet/app.css` (`.svc-status`, `.st-progress`, `.st-done`, `.st-cancel`, `.acct-switch`, `.tick-filter`), `templates/sheet/index.html` (filter slots on Calculations, table slot on Dashboard), `tools/ui_smoke_test.js`
- Test: `sheet/tests_frontend_safety.py` (unchanged, must pass), `tools/ui_smoke_test.js`

**Interfaces:**
- Consumes: the JSON of Tasks 1, 2, 4, 5; `config.js` `ME` (add `role` if missing).

- [ ] **Step 1: Extend the smoke test** (alex: set a service Cancelled with a reason → card shows "Cancelled" and the reason; Calculations shows the Status column and an Open switch is not clickable; viewer: Calculations switch closes a row, Open filter hides it, alex's edit of that service then shows the lock message; admin: Dashboard shows the Service status table) — run it, see it fail.
- [ ] **Step 2: Implement** the screens.
- [ ] **Step 3: Run** `cd tools && npm run check` → green; smoke test (fresh database, `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) for alex, admin, viewer, suez → ALL PASSED.
- [ ] **Step 4: Commit** `feat(ui): status labels, accounting switch and filters`.

### Task 7: Docs, show the user, finish

**Files:** `docs/STATUS.md`, `CLAUDE.md` (services, accounting, Calculations, Dashboard paragraphs), `README.md` / `SECURITY.md` (test count; read-only now has the accounting write), `docs/DEPLOYMENT.md` (read-only accounts = accounting; migration 0019)

- [ ] **Step 1:** Update the docs. **Step 2:** `npm run check` → green. **Step 3:** Show the user the running app (service dialog, card, Calculations as viewer and alex, Dashboard). **Step 4:** Commit `docs: service and accounting status`; fresh whole-branch review; merge only when the user agrees.
