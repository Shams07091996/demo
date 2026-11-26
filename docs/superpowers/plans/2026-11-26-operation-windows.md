# Overdue vessels, vessel-list operator, sidebar folders, berthing windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overdue vessels stay in Live data, listed vessels carry an operator, sidebar folders stand out, and a
Berthing windows page feeds a "nearest window" hint in the visit dialog.

**Architecture:** Server-side rules in the `operation` app (`live.py`, `validators.py`, new `windows.py`), front end
with `dom.js` only, one new Operation page and dialog following the Terminals page pattern.

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-26-operation-windows-design.md`

## Global Constraints

- Branch `feature/operation-windows`; `cd tools && npm run check` green; merge only when the user agrees.
- Input refused, never fixed; all times Cairo; screens only through `dom.js`; no capitals in headings; compact text.
- The vessel-list field is labelled **Operator** (user's word), stored as `line`, values from the Shipping line lists.
- Windows: weekly, per terminal + line; same editors as Terminals (`require_master`, own ports), read with `op_vessels`.
- LF line endings; a new page column needs nothing in Excel (no export for these pages).

## Review Focus

- A window running over the week's end (Sat 20:00 → Mon 06:00) must contain an ETA on Sunday (Task 4 test).
- An ETA exactly at a window's end is outside it (half-open [start, end)) (Task 4 test).
- A port user must not read or write another port's terminal's windows (Task 4 test).
- A listed vessel whose operator is not offered at the chosen terminal leaves the visit's line alone (Task 3 smoke).
- An overdue vessel whose ETA is weeks old still shows, and a Completed one never does (Task 1 test).

---

### Task 1: Live data keeps overdue vessels

**Files:** Modify `operation/live.py`, `sheet/static/sheet/js/pages/opLive.js:29-31`; Test `operation/tests_live.py`.

**Interfaces — Produces:** each `upcoming` item gains `overdue: bool` (no ATA and ETA before today 00:00 Cairo).

- [ ] Tests in `tests_live.py`: `test_overdue_without_ata_stays_marked` (ETA 3 days ago, no ATA/ATB → in upcoming,
  `overdue True`, `arrived False`), `test_old_overdue_still_shows` (ETA 30 days ago), `test_completed_never_upcoming`
  (ATA/ATB/ATD set, ETA yesterday → not in upcoming), and update the existing order assertion
  (`[v["arrived"] …]`) if the fixture now includes more rows.
- [ ] Run `venv/Scripts/python.exe manage.py test operation.tests_live` → new tests FAIL.
- [ ] `live.py`: upcoming condition becomes `not visit.atb and (visit.ata or visit.eta < next_end)`; add `overdue`.
  Update the module docstring.
- [ ] `opLive.js`: an **Overdue** chip (class `status-chip st-planned` or the warning one already in app.css, title
  `ETA …`) like Arrived.
- [ ] Run → PASS. Commit `feat(live): vessels past their ETA stay in Next 7 days, marked Overdue`.

### Task 2: Sidebar folders (already drafted in the working tree)

**Files:** `sheet/templates/sheet/index.html` (four folder heads), `sheet/static/sheet/app.css:44-51`.

- [ ] Check `manage.py test sheet.tests_look` (icons used must be in the sprite) and ESLint → pass.
- [ ] Look at it light and dark in the browser pane. Commit `style(sidebar): folders as shaded bands with icons`.

### Task 3: Vessel list operator

**Files:** Modify `operation/models.py` (`ListedVessel.line = CharField(max_length=100, blank=True)`), new migration
`operation/migrations/0004_listed_vessel_line.py`, `operation/validators.py` (`clean_listed_vessel`),
`operation/vessel_list.py` (`listed_to_dict` adds `"line"`), `sheet/static/sheet/js/pages/vesselList.js`,
`sheet/static/sheet/js/modals/listedVessel.js`, `sheet/static/sheet/js/modals/visit.js:84-85`,
`sheet/management/commands/seed_demo.py` (listed vessels get their line), `tools/ui_smoke_test.js`;
Test `operation/tests_vessel_list.py`.

**Interfaces — Produces:** `listed_to_dict(v) -> {"id", "name", "loa", "line"}`.

- [ ] Tests: `test_new_entry_needs_operator` (no `line` → 400 "Choose the operator."), `test_operator_from_any_port_list`
  (a Port Said Shipping line value accepted; an unknown value 400), `test_saved_operator_stays_allowed` (value removed
  from Master data, PUT with the same `line` → 200), `test_existing_entry_may_keep_empty` (an entry with `line=""`
  saved with `line` "" → 200), `test_list_returns_line`.
- [ ] Run `manage.py test operation.tests_vessel_list` → FAIL.
- [ ] Model + `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations operation -n listed_vessel_line`;
  validator: `line` = `_short(…, 100, "Operator")`, must be in `Option(kind="line")` values of any port or the saved
  value; empty refused unless `existing` and its saved line is empty. Check `makemigrations --check --dry-run`.
- [ ] Run → PASS.
- [ ] Front end: Vessel list table column **Operator** after Name; dialog select **Operator** (every Shipping line
  value, sorted, keeping the saved one; "" option only when the saved one is empty); visit dialog: on a vessel-name
  match also set `shipping_line` when `[...select.options].some(o => o.value === match.line)`.
- [ ] Smoke (admin): the Vessel list shows an Operator column; picking a listed vessel in a new visit fills LOA and
  line. Commit `feat(vessel list): each vessel has its operator, filled into a new visit`.

### Task 4: Berthing windows (server)

**Files:** Modify `operation/models.py` (`BerthingWindow`), migration `0005_berthing_window`, `operation/validators.py`
(`clean_window`), `operation/apps.py` (track), `sheet/history.py` (`PORT_TYPES` + `TYPE_PAGES` "berthingwindow" →
op_vessels), `operation/urls.py`, `operation/views.py`; Create `operation/windows.py`; Test `operation/tests_windows.py`.

**Interfaces — Produces:**
- `BerthingWindow(terminal FK PROTECT related_name="windows", line CharField 100, start_day SmallInt 0–6 (Mon=0),
  start_time TimeField, end_day, end_time)`, `history_port()` = terminal's port.
- `windows.window_to_dict(w) -> {"id", "terminal", "port", "line", "start_day", "start_time": "HH:MM", "end_day",
  "end_time", "hours": float}`.
- `windows.occurrence_minutes(w) -> (start, end)` minutes from Monday 00:00, `end` may exceed 10080 (wraps).
- `windows.nearest(windows, eta_local: datetime) -> dict | None` → `{"window": window_to_dict, "start": iso local,
  "end": iso local, "position": "inside" | "before" | "after", "hours": float (1 decimal, distance from start)}`.
- Routes: `GET/POST /api/operation/windows/?port=&terminal=` (GET: `require_page op_vessels`; POST: `require_master`,
  terminal must be in scoped terminals and active), `PUT/DELETE /api/operation/windows/<id>/` (`require_master`,
  another port's → 404), `GET /api/operation/windows/nearest/?terminal=&line=&eta=` (`require_page op_vessels`;
  `{"nearest": … | None}`). Audit `window.create|update|delete`.

- [ ] Tests (`tests_windows.py`, use `tests.make_user` / ApiTestCase helpers as `tests_terminals.py` does):
  - `test_create_and_list` (Tue 06:00 → Wed 18:00 → `hours 36.0`), `test_end_equal_start_refused`,
    `test_overlap_same_terminal_line_refused` (Tue 06–Wed 18 and Wed 12–Thu 00 → 400), `test_other_line_may_overlap`,
    `test_line_must_be_terminal_line` (terminal with `lines` set: other value 400),
    `test_port_user_other_port_404_and_403` (GET list excludes, PUT 404, POST with other port's terminal 403),
    `test_needs_master_tick_to_write` (op_vessels only: POST 403, nearest 200), `test_delete`.
  - `NearestTests`: windows MSK Tue 06:00→Wed 18:00 and Fri 22:00→Sat 20:00 at one terminal: ETA Thu 08:00 →
    Fri 22:00 window, `before`, 38.0 h; ETA Wed 10:00 → `inside`; ETA Wed 18:00 → not inside (end excluded), nearest
    by start; a Sat 20:00→Mon 06:00 window and ETA Sun 12:00 → `inside`; tie (equal distance) → later; other line → None.
- [ ] Run `manage.py test operation.tests_windows` → FAIL.
- [ ] Implement model + migration, validator (`start_day`/`end_day` ints 0–6, times "HH:MM", terminal id, line;
  overlap check over the week, wrap included, excluding `existing`), `windows.py`, views, urls, history entries.
  `nearest`: for each window take the occurrences of the ETA's week, the week before and after (start/end as
  Cairo datetimes), pick the one containing the ETA, else min |start − ETA|, ties to the later start.
- [ ] Run → PASS; `makemigrations --check --dry-run` clean. Commit `feat(operation): berthing windows and the nearest window`.

### Task 5: Berthing windows page, dialog and hint (front end)

**Files:** Create `sheet/static/sheet/js/pages/windows.js`, `sheet/static/sheet/js/modals/window.js`; Modify
`sheet/templates/sheet/index.html` (nav item after Terminals, same `{% if %}`, icon `clock`; `<main id="page-op_windows">`
with port / terminal filters, `+ Add` button `data-act="window-add"`, table `#wn-tbody`, `#wn-empty`), `router.js`
(title "Berthing windows", same guard as `terminals`, load), `actions.js` (`window-add`, `window-edit`,
`window-delete`, `save-window`), `js/modals/visit.js` (hint), `app.css` (hint line), `seed_demo.py`, `tools/ui_smoke_test.js`.

**Interfaces — Consumes:** Task 4 routes and dict shape.

- [ ] Page: rows Terminal (`name`, + port label when `ME.multiPort`), Line, Window (`Tue 06:00 → Wed 18:00`), Length
  (`36 h`), edit (pencil) and `deleteBtn('window-delete', {id})`. Days `['Mon','Tue','Wed','Thu','Fri','Sat','Sun']`.
- [ ] Dialog: terminal select (active, own ports), line select (`terminalLines` from `operation/shared.js`), start
  day select + `type=time`, end day select + time; Save → POST/PUT, errors shown like the terminal dialog.
- [ ] Visit dialog: `<div class="visit-window" id="visit-window">` under Line; on open and on change of terminal / line
  / eta, fetch `nearest` (drop out-of-order answers with a counter) and show
  `Window: Fri 27.11 22:00 → Sat 28.11 20:00 · ETA 14 h before` / `· ETA inside the window` / `· ETA 3 h after the start`;
  nothing when `nearest` is null or a field is empty.
- [ ] `seed_demo`: MSK windows at an Alexandria terminal (Tue 06:00→Wed 18:00, Fri 22:00→Sat 20:00) and one window at
  PSD EAST; listed vessels get a line.
- [ ] Smoke (admin): Berthing windows page lists the seeded windows; add one and delete it; a new visit with that
  terminal, MSK and an ETA shows a "Window:" hint. alex: page visible (Branch template has the tick); viewer: no
  nav item. ESLint, `tests_frontend_safety`, `tests_look`, all five smoke runs on a fresh DB.
- [ ] Browser look (light / dark). Commit `feat(operation): Berthing windows page and the nearest window in the visit dialog`.

### Task 6: Docs and final check

- [ ] `docs/STATUS.md` (new round, migrations `operation 0004`, `0005` needed), `CLAUDE.md` (Operation: overdue,
  operator, windows; sidebar), `README.md` / `SECURITY.md` test counts, `docs/DEPLOYMENT.md` only if roles change (they don't).
- [ ] `cd tools && npm run check` → green. Commit `docs: operation windows round`. Self-review the branch; ask about merging.
