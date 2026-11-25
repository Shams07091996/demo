# Operation App (Port Berthing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new Django app `operation` with four pages (Vessel Data, Live data, Analysis reports, Report charts) in a
new sidebar folder **Operation**, plus an Admin-only Terminals page, replacing the user's berthing workbook.

**Architecture:** `operation/` owns its models, migrations, API (`/api/operation/...`) and tests, and reuses `sheet`'s
plumbing (`api.json_api`, `access`, `history`, `conflicts`, `ports`, `validators` helpers, `xlsx`). Every figure is
worked out in one module (`operation/figures.py`); Analysis and Charts share one response. The front end stays in
`sheet/static/sheet/js/` (one page, `dom.js`, strict CSP), so the existing safety tests cover it.

**Tech Stack:** Django 5.2, SQLite (dev) / PostgreSQL, vanilla ES modules, no new libraries.

**Spec:** `docs/superpowers/specs/2026-11-25-operation-app-design.md` (read it with this plan).

## Global Constraints

- Branch `feature/operation-app` from `main`; merged only when the user agrees. LF line endings.
- No new third-party library. No money anywhere in this part.
- Input is refused, never silently fixed (`BadRequest` with a plain message); unknown keys are ignored only where the
  `sheet` validators already do so — here every payload is read key by key from a fixed list.
- Every query of visits / terminals goes through `operation.access.scoped_visits` / `scoped_terminals`.
- Writes: one `transaction.atomic` per request (`json_api` does it), `api.audit(...)` on every write.
- Front end: `dom.js` only, no `innerHTML` / inline `style=`, icons from the sprite, colours from tokens, no help
  text / placeholders (the user's preference: compact screens).
- Page keys: `op_vessels`, `op_live`, `op_analysis`, `op_charts`; hash = page key (`#op_vessels`). Admin page:
  `terminals`. Permissions: `operation.edit` "Add / edit vessel data", `operation.delete` "Delete vessel data".
- Times: Cairo local strings in and out (`validators._local_datetime`, `serializers.local_iso`).
- Hours and moves/hr: rounded to 1 decimal with Python `round(x, 1)`.
- `npm run check` (in `tools/`) green before asking to merge; update STATUS / CLAUDE / README / SECURITY /
  DEPLOYMENT with the work.

## Review Focus

1. **A berth removed from a terminal's list** while visits use it: editing such a visit without touching the berth
   must still save (saved value stays allowed) — test in Task 5.
2. **An Admin moves a terminal to another port**: its visits follow (scoping is through `terminal.port`), a User of
   the old port no longer sees them — test in Task 4.
3. **A User changes a visit's terminal to one in a port that isn't theirs**: 403, nothing saved — test in Task 5.
4. **Filters that match no visit** (Analysis / Charts): figures are `null` ("—"), no division by zero; From after To
   is 400 — test in Task 7.
5. **A turned-off terminal**: no new visit on it (400 "That terminal is turned off."), existing visits stay editable
   and listed; Live data drops it — tests in Tasks 5 and 6.

---

### Task 1: The app, its models and the Shipping line list

**Files:**
- Create: `operation/__init__.py`, `operation/apps.py`, `operation/models.py`, `operation/admin.py`,
  `operation/migrations/0001_initial.py`, `operation/tests_models.py`
- Create: `sheet/migrations/0030_option_line.py` (choices only)
- Modify: `config/settings.py` (`INSTALLED_APPS`: `"operation"` right after `"sheet"`), `sheet/constants.py`
  (`OPTION_KINDS` + `("line", "Shipping line")`), `sheet/history.py` (`TRACKED` + `Terminal`, `Visit`)

**Interfaces:**
- Produces: `operation.models.Terminal(name, code, port, quay_length, cranes, berths: list[str], active, position)`
  ordered by `position, name`; `operation.models.Visit(terminal FK PROTECT related_name="visits", vessel_name,
  shipping_line, loa Decimal(5,1) null, eta, ata, etb, etc, atb, atd (DateTime, eta not null), planned_berth,
  actual_berth (CharField 10 blank), cranes PositiveSmallInteger null, discharge, loading PositiveInteger null,
  version PositiveInteger default 1, created_at)`. `port` is not stored on Visit.

- [ ] **Step 1: Write failing tests** in `operation/tests_models.py`:
  `test_terminal_and_visit_saved` (create a terminal with `berths=["40/1","40/2"]` and a visit; reload; equal);
  `test_changes_are_in_history` (update a visit's `vessel_name` → a `ChangeRecord` with `object_type="visit"` and the
  old → new value); `test_line_is_a_master_data_kind` (`"line" in OPTION_KIND_KEYS`);
  `test_terminal_in_use_cannot_be_deleted` (`ProtectedError`).
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test operation.tests_models` → fails (no app).
- [ ] **Step 3: Implement** the app, models, read-only admin (as `sheet.admin`), `makemigrations operation` and
  `makemigrations sheet --name option_line` (with `DJANGO_DEBUG=1`), the `TRACKED` entries. Import `Terminal` /
  `Visit` into `sheet/history.py` inside `connect()` if a module-level import would be circular.
- [ ] **Step 4: Run** `manage.py test operation sheet.tests_migrations` → pass; `makemigrations --check --dry-run`
  → "No changes detected".
- [ ] **Step 5: Commit** `feat(operation): app, terminals, visits, shipping line list`.

### Task 2: Pages and permissions

**Files:**
- Modify: `sheet/constants.py` (`PERMISSIONS` + the two keys after `accounting.close`; `PAGES` + the four pages
  after `dashboard`; `PERMISSION_NEEDS` + `"operation.edit": ("page", "op_vessels")`, `"operation.delete": ("page",
  "op_vessels")`), `sheet/static/sheet/js/pages/accounts.js` if the "x of 16" text is hard-coded
- Test: `operation/tests_access.py`

**Interfaces:**
- Produces: `profile.sees("op_live")` etc. and `profile.can("operation.edit")` work through the existing
  `Profile.sees` / `can`.

- [ ] **Step 1: Failing tests:** `test_new_pages_and_permissions_exist` (keys in `PAGE_KEYS` / `PERMISSION_KEYS`,
  `len(PERMISSION_KEYS) == 18`); `test_existing_profile_does_not_get_them` (a Profile saved with the old 16 / 13
  lists → `sees("op_vessels")` False, `can("operation.edit")` False); `test_branch_manager_template_has_them`;
  `test_edit_needs_vessel_data_page` (permission ticked, page not → `can` False; `clean_account` refuses the
  combination with 400); `test_accounts_list_counts_18`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** the constants. No migration (JSON lists; nobody gets the new keys — the user's decision).
- [ ] **Step 4: Run** `manage.py test operation sheet.tests_permissions sheet.tests_accounts` → pass (fix any
  existing test that counted 16).
- [ ] **Step 5: Commit** `feat(operation): Operation pages and permissions (off for existing accounts)`.

### Task 3: Figures

**Files:**
- Create: `operation/figures.py`, `operation/tests_figures.py`

**Interfaces:**
- Produces: `status(visit) -> "Planned"|"Working"|"Completed"`; `hours(start, end) -> float|None`;
  `figures(visit) -> {"status", "waiting", "operation", "port_stay", "total_moves", "productivity"}`;
  `live_rate(visit, now) -> float|None`; `report_date(visit) -> date` (Cairo date of ATA else ETA);
  `average(values) -> float|None` (skips None, 1 decimal).

- [ ] **Step 1: Failing tests** (`SimpleTestCase`, unsaved `Visit` objects, Cairo-aware datetimes). The Excel's
  ALLEGRI: ATA 2026-11-20 07:00, ATB 11:00, ATD 2026-11-21 22:00, discharge 700, loading 800 → waiting 4.0,
  operation 35.0, port stay 39.0, total 1500, productivity 42.9, status Completed. No ATB → Planned; ATB without ATD
  → Working; only loading 500 → total 500; neither → total None; operation 0 hours → productivity None.
  `live_rate`: ATB 10:00, now 14:00, moves 400 → 100.0; no moves → None; now − ATB under 0.1 h → None.
  `report_date`: ATA wins over ETA; ETA used when ATA empty. `average([None, 2, 3]) == 2.5`, `average([]) is None`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(operation): visit figures`.

### Task 4: Terminals API and scoping

**Files:**
- Create: `operation/access.py`, `operation/validators.py`, `operation/terminals.py`, `operation/views.py`,
  `operation/urls.py`, `operation/tests_terminals.py`
- Modify: `config/urls.py` (`path("", include("operation.urls"))` after sheet's)

**Interfaces:**
- Produces: `operation.access.ops_reader(profile)` (403 unless Admin or `sees` any of the four pages);
  `scoped_terminals(profile, port=None) -> QuerySet` (`port__in` the User's ports, narrowed by `access.asked_port`);
  `scoped_visits(profile, port=None) -> QuerySet` (`terminal__port__in`, `select_related("terminal")`);
  `validators.clean_terminal(data, existing=None) -> dict`; `terminals.terminal_to_dict(t) -> {id, name, code, port,
  port_label, quay_length, cranes, berths, active}`. Routes: `GET/POST /api/operation/terminals/`,
  `PUT /api/operation/terminals/<int:pk>/`.

- [ ] **Step 1: Failing tests** (`ApiTestCase`; create terminals in `alexandria` and `portsaid`, one turned off):
  `alex` with `op_live` sees only the Alexandria ones (incl. turned-off, flagged `active: false`); `viewer` sees both
  ports; a User with no Operation page → 403; Admin POST creates (name unique ignoring case → 400 "That terminal
  already exists."; berths duplicated → 400; 0 or 31 berths → 400; berth over 10 characters → 400; quay 0 → 400;
  cranes 51 → 400; turned-off port for a new terminal → 400); `alex` POST / PUT → 403; Admin PUT moves the terminal
  to `portsaid` → `alex` no longer sees its visits (Review Focus 2); there is no DELETE route (405).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.** Writes: `access.require_admin`; code upper-cased; port through
  `access.require_port(profile, key, new=<new or moved>)`; `audit(request, "terminal.create"|"terminal.update")`.
- [ ] **Step 4: Run** `manage.py test operation` → pass. **Step 5: Commit** `feat(operation): terminals API`.

### Task 5: Visits API

**Files:**
- Create: `operation/visits.py`, `operation/tests_visits.py`
- Modify: `operation/validators.py` (`clean_visit`), `operation/views.py`, `operation/urls.py`,
  `sheet/history.py` (`PORT_TYPES` + `"visit"`, `TYPE_PAGES["visit"] = ("op_vessels",)`, `port_of` for a Visit =
  `visit.terminal.port`), `sheet/tests.py` (`VERSIONED_URL` and `VERSIONED_MODELS` learn `operation/visits`)

**Interfaces:**
- Produces: `clean_visit(data, profile, existing=None) -> dict` (fields of `Visit`); `visit_to_dict(v, profile)` =
  stored fields (times as `local_iso`) + `figures(v)` + `terminal_name`, `port`, `port_label`, `report_date`,
  `can_edit`, `can_delete`; `visits.filtered(profile, params) -> list[Visit]` (also the export);
  `visits.list_response(profile, params) -> {"visits", "total", "page", "pages", "lines"}`. Routes
  `GET/POST /api/operation/visits/`, `PUT/DELETE /api/operation/visits/<int:pk>/`.

- [ ] **Step 1: Failing tests:**
  - create with every field → 201, name upper-cased, figures in the response; missing vessel name / terminal / line /
    ETA → 400 each with its message; LOA 0 or 500.1 → 400; cranes 0 → 400; discharge −1 → 400;
  - order rules: ATB without ATA, ATD without ATB, ATB before ATA, ATD equal to ATB, ETC before ETB → 400 each;
  - berth not in the terminal's list → 400; a berth removed from the list but saved on the visit → PUT without
    changing it → 200 (Review Focus 1); shipping line not in the Master data list → 400; saved one kept → 200;
  - `alex` POST on a Port Said terminal → 403; PUT changing the terminal to a Port Said one → 403, nothing saved
    (Review Focus 3); new visit on a turned-off terminal → 400 "That terminal is turned off."; editing an existing
    visit on it → 200 (Review Focus 5);
  - without `operation.edit` POST / PUT → 403, GET → 200; DELETE needs `operation.delete`; without `op_vessels` →
    403 for all;
  - PUT with an old `version` → 409 (the `conflicts` shape);
  - list: `status=Working,Completed`, `terminal=<id>`, `line=ARKAS`, `q=allE` (literal, case-insensitive), `from` /
    `to` on the report date, `port` narrowing only; default sort newest ETA first; `sort=waiting&dir=asc` sorts
    with blanks last; `page_size=2` paging; `lines` = the shipping lines used in scope;
  - History: a User with `history.view` and `op_vessels` sees the visit records of their ports only.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** like `sheet/closures.py` (`save_visit` with `conflicts.snapshot` /
  `bump_if_changed`, view with `conflicts.locked`); sort keys: `id, vessel_name, shipping_line, terminal, eta, ata,
  atb, atd, status, waiting, operation, port_stay, total_moves, productivity`; page size default 50, max 200.
  Audit `visit.create|update|delete`.
- [ ] **Step 4: Run** `manage.py test operation sheet.tests_history sheet.tests_conflicts_api` → pass.
- [ ] **Step 5: Commit** `feat(operation): vessel visits API`.

### Task 6: Live data API

**Files:**
- Create: `operation/live.py`, `operation/tests_live.py`; Modify: `operation/views.py`, `operation/urls.py`

**Interfaces:**
- Produces: `live.response(profile, port, now) -> {"terminals": [{**terminal_to_dict, "calls_7d", "working": [...],
  "upcoming": [...]}]}`; route `GET /api/operation/live/?port=` (needs `op_live`).

- [ ] **Step 1: Failing tests** (fixed `now`): only active terminals in scope, in terminal order; `working` = ATB
  and no ATD, ordered by ATB, each with `live_rate`; `upcoming` = no ATB, ETA in `[now, now + 7 days)`, ordered by
  ETA (ETA yesterday or in 8 days left out); `calls_7d` = ETA from Cairo today − 6 days to the end of today; a turned-off
  terminal is absent (Review Focus 5); Port Said visits not shown to `alex`; without `op_live` → 403.
- [ ] **Step 2–4:** run → fail, implement, run → pass.
- [ ] **Step 5: Commit** `feat(operation): live data`.

### Task 7: Analysis API (shared by Analysis reports and Report charts)

**Files:**
- Create: `operation/analysis.py`, `operation/tests_analysis.py`; Modify: `operation/views.py`, `operation/urls.py`

**Interfaces:**
- Produces: `analysis.response(profile, params) -> {"headline": {"calls", "waiting", "operation", "port_stay",
  "productivity", "per_week", "per_month", "per_year"}, "terminals": [row], "lines": [row], "line_choices": [...],
  "berth_choices": [...]}`; `row = {"name", "calls", "waiting", "operation", "port_stay", "loa", "cranes",
  "productivity", "total_moves", "berthed"}`. Route `GET /api/operation/analysis/?port=&terminal=&berth=&from=&to=&line=`
  (needs `op_analysis` or `op_charts`).

- [ ] **Step 1: Failing tests** with the Excel's seven visits seeded (values from `Analysis & Reports`): all
  terminals → calls 7, waiting 5.0, operation 26.6, port stay 31.6, productivity 44.5; terminal rows ACCHCO - ALX
  calls 2 / waiting 9.5 / operation 21.0 / stay 30.5 / LOA 200.0 / cranes 1.5 / productivity 64.3 / moves 2100 /
  berthed 2, AICT - DKH 3 / 2.7 / 33.7 / 36.3 / 150.0 / 2.0 / 26.9 / 1850 / 3; a terminal with no visit → calls 0,
  averages `None` (Review Focus 4); `lines` one row per line ordered by calls then name; `berth` filter matches
  actual berth else planned berth; `line=MCL` narrows both tables; `from`/`to` on report date; `from > to` → 400;
  `per_week` only with both dates: 7 calls over 14 days → 3.5, per_month = 7 ÷ (14 ÷ 30.44) → 15.2, per_year →
  182.6; only `from` → all three `None`; scoping for `alex`.
- [ ] **Step 2–4:** run → fail, implement (`terminals` rows = every terminal in scope, active or not, that matches
  the terminal filter), run → pass.
- [ ] **Step 5: Commit** `feat(operation): analysis figures`.

### Task 8: Vessel Data Excel export

**Files:**
- Modify: `operation/views.py`, `operation/urls.py`; Test: `operation/tests_export.py`

**Interfaces:**
- Produces: `GET /api/operation/visits/export/?<list query>` → `.xlsx` (`sheet.xlsx`, plain table like
  `dataexport`: one header row, `xlsx.Moment` times, numbers as numbers), filename `vessel-data.xlsx`; needs
  `exports` + `op_vessels`; rate limited with the exports (as `views.data_export`); audit `operation.export`.

- [ ] **Step 1: Failing tests:** 200 with the xlsx content type; the header row has the 22 columns of the spec's
  Vessel Data table; filtered rows only; without `exports` → 403; `alex` file has no Port Said visit.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(operation): vessel data export`.

### Task 9: Demo data

**Files:**
- Modify: `sheet/management/commands/seed_demo.py`; Test: `sheet/tests_management.py` (one new test)

- [ ] **Step 1: Failing test:** after `seed_demo`, 5 Alexandria terminals with the spec's codes / quays / cranes /
  berths, one Port Said terminal (`PSD EAST`, berths 1/2, 600 m, 3 cranes), the six lines for All ports, at least
  one Working visit and one Planned visit with ETA in the next 7 days, 7 Completed ones; demo Users except `marine`
  have the four pages and both permissions, `viewer` has the pages without `operation.edit` / `operation.delete`.
- [ ] **Step 2–4.** Times relative to `timezone.now()` so the smoke test always has live rows.
- [ ] **Step 5: Commit** `feat(operation): demo terminals and visits`.

### Task 10: Sidebar folder, router and the Terminals page

**Files:**
- Modify: `sheet/templates/sheet/index.html` (Operation folder after Marine: four `nav-item`s each behind
  `{% if "op_…" in me.pages %}`, folder not rendered with none; Terminals item in Master data behind
  `me.isAdmin`; `<main class="page" id="page-op_vessels|op_live|op_analysis|op_charts|terminals" hidden>`),
  `js/router.js` (`TITLES` + the five; `terminals` Admin-only like `ports`), `js/navGroups.js` if folders are listed,
  `js/actions.js`
- Create: `js/pages/terminals.js`, `js/modals/terminal.js`, `js/operation/api.js` (fetch helpers for
  `/api/operation/...`), `js/operation/format.js` (pure: `hoursText`, `statusClass`)
- Test: `sheet/tests_look.py` / `tests_frontend_safety.py` run unchanged; add `operation/tests_page.py`
  (rendered `/` for a User with no op pages has no `data-group="operation"`; with `op_live` only, one item;
  Admin has the Terminals item)

- [ ] Steps: failing page test → implement → `manage.py test operation sheet.tests_look sheet.tests_frontend_safety`
  → `npm run check` (ESLint) → commit `feat(operation): sidebar folder and terminals page`.
- Terminals page: table Name, Code, Port, Quay (m), Cranes, Berths, Active; **+ Add terminal**; row opens the
  dialog (name, code, port select `formPorts`, quay, cranes, berths as a list of small inputs with + / remove,
  active tick).

### Task 11: Vessel Data page and visit dialog

**Files:**
- Create: `js/pages/opVessels.js`, `js/modals/visit.js`; Modify: `index.html`, `js/router.js`, `js/actions.js`

- [ ] Filters (port when `ME.multiPort`, terminal, status ticks via `components.tickFilterEl`, line, search,
  From–To) kept in `localStorage` key `sheet.opVessels.filter`; table with the spec's columns, status pill, sortable
  heads, pager (`render/pager.js`); **+ Add visit** only with `can('operation.edit')`; Excel button with
  `can('exports')`. Dialog: terminal select first, berth selects rebuilt from the chosen terminal's berths (keep a
  saved berth not in the list), line from `optionChoices('line', current, port)`, date-time inputs, figures shown
  read-only (worked out by the server after save; the dialog shows the saved ones), Delete with
  `can('operation.delete')`, 409 through `mutate(..., onConflict)`.
- [ ] Verify: `npm run check`; smoke step in Task 14. Commit `feat(operation): vessel data page`.

### Task 12: Live data page

**Files:** Create `js/pages/opLive.js`; Modify `index.html`, `js/router.js`, `js/actions.js`, `app.css`

- [ ] One `.panel` card per terminal: header line "NAME (CODE)", "Quay 500 m · Berths 23 / 24 / 25 · Cranes 4 ·
  Calls 7 days N"; two tables side by side on wide screens, stacked on phones ("Under operation", "Next 7 days")
  with the spec's columns; empty table → one muted row "None". Port filter for multi-port people; Refresh button
  (`data-act="op-live-refresh"`). Commit `feat(operation): live data page`.

### Task 13: Analysis reports and Report charts pages

**Files:** Create `js/pages/opAnalysis.js`, `js/pages/opCharts.js`; Modify `index.html`, `js/router.js`,
`js/state.js` (`state.operationFilter`), `js/actions.js`, `app.css`

- [ ] Analysis: filter row (port, terminal, berth from `berth_choices`, From, To, line from `line_choices`); five
  headline tiles plus Calls per week / month / year when present; the two tables; `null` → "—". Charts: same filter
  row and request; "Vessel calls by terminal" bars and "Average waiting vs operation" paired bars built like
  `render/dashboard.js` `renderBars` (classes, no inline style; bar heights through the same mechanism it uses),
  colours `--c1` / `--c2`, a small legend. Commit `feat(operation): analysis and charts pages`.

### Task 14: Smoke test, docs, full check

**Files:** Modify `tools/ui_smoke_test.js`, `docs/STATUS.md`, `CLAUDE.md` (an **Operation** section under
Architecture), `README.md`, `SECURITY.md` (test count), `docs/DEPLOYMENT.md` (migrations `operation 0001`,
`sheet 0030`; new pages off for everyone until ticked)

- [ ] Smoke (`admin`): open the four pages and Terminals, add a terminal named `Smoke…` in Alexandria; (`alex`): add
  a visit, open it, change ATD, see it Completed; Live data shows the seeded Working vessel; Analysis shows a
  number of calls; Charts draws bars. (`marine`): no Operation folder.
- [ ] Run the full `npm run check` and the smoke runs for alex / admin / viewer / suez / marine on a fresh
  database (CLAUDE.md "Browser smoke test"); all green.
- [ ] Commit `docs: operation app`. Then a fresh whole-branch review before asking the user to merge.
