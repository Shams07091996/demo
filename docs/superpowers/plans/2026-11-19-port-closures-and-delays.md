# Port closures, delay reason and missing-details alert: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** This adds three things:
- a Port closures page;
- a required delay reason when a vessel berths more than 2 hours after it arrives;
- a "Missing details" alert for past vessels.

**Architecture:**
- A new `PortClosure` model sits in its own module, `sheet/closures.py`, which holds the list, save and dict code.
  It is scoped by its own `port` through `access.scoped_closures`.
- `Vessel.delay_reason` is checked in `validators.clean_vessel`.
- `listing.missing_agents` becomes `listing.missing_details`.
- The front end gets one page module and one dialog, both built with `dom.js`.

**Tech Stack:** Django 5.2, vanilla ES modules (no build), jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-19-port-closures-and-delays-design.md`

## Global Constraints

- Branch `feature/port-closures-delays`. One commit per task, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Files use LF line endings.
- Input is refused, never silently fixed. List values must be in Master data for the record's port or All ports, and
  a value already saved stays allowed (`validators.listed`).
- Delayed means `berthing_at - arrival_at > timedelta(hours=2)`, with both times set. Exactly 2:00 is not delayed.
- Refusal copy, verbatim:
  - "Choose a delay reason (berthed more than 2 hours after arrival)."
  - "Not delayed (berthed within 2 hours): clear the delay reason."
  - "Choose a closure reason."
  - "Reopened cannot be before closed from."
- Option kinds: `("delay", "Delay reason")` and `("closure", "Closure reason")`.
- The alert key is `missing`. The group title is "Missing details". The banner head reads "· N missing details".
- Missing labels, in order: the 5 `TIME_LABELS` (Arrived, Berthed, Ops started, Ops finished, Sailed), then
  "Delay reason", then "Arrival agent", "Sailing agent", then "<Service type> agent" in SERVICE_TYPES order.
- Screens are built only with `dom.js`. No innerHTML, no inline `style=` attributes, no emoji. Icons come from the
  sprite and `ICONS` only. Lean screens: no help text, no placeholders.
- Never touch the user's PostgreSQL `marine_sheet` database or `db.sqlite3`. The smoke test runs on a scratch
  SQLite database.

## Review Focus

1. **A PUT of an old delayed vessel with no reason** is refused. The admin must be able to fix it in the form,
   because the dropdown shows whenever the inputs show a delay. Owned by Task 2 (server) and Task 6 (form).
2. **A port user sends `port` for another port** on a closure create or edit, or a closure id from another port. The
   port is ignored, and the other port's closure gives 404. Owned by Task 4.
3. **A closure with no "Reopened"** must still show in every later range ("Still closed"). Owned by Task 4
   (`test_open_closure_overlaps_any_later_range`).
4. **An admin changes a vessel's port** while a delay reason is set: the reason must exist for the new port or All
   ports, or be the saved value. Already covered by `listed`; pinned by
   `test_delay_reason_from_other_port_refused` (Task 2).
5. **Fewer missing labels than before**: the smoke test and `tests_agents` expect "Sailing" and "Landing". These must
   become "Sailing agent" and "Landing agent", or they break silently. Owned by Tasks 3 and 8.

---

### Task 1: Data model, option kinds, history

**Files:**
- Modify: `sheet/constants.py` (OPTION_KINDS, new `DELAY_LIMIT`)
- Modify: `sheet/models.py` (`Vessel.delay_reason`, new `PortClosure`)
- Create: `sheet/migrations/0013_port_closures_and_delays.py` (makemigrations, then check its name)
- Modify: `sheet/history.py` (`TRACKED` gets `PortClosure`)
- Modify: `sheet/admin.py` (read-only registration, as for the other tracked models)
- Test: `sheet/tests_closures.py` (new)

**Interfaces:**
- Produces:
  - `constants.DELAY_LIMIT: timedelta(hours=2)`.
  - `models.PortClosure(port, start_at, end_at|None, reason, notes, created_at)`, ordering `["-start_at", "-id"]`.
  - `Vessel.delay_reason: str`.
  - `constants.is_delayed(arrival_at, berthing_at) -> bool`: both set and the gap is more than DELAY_LIMIT. It is
    pure, and later tasks use it.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_closures.py` (`ClosureModelTests(TestCase)`):
  - `test_closure_saved_with_open_end`: create one with `end_at=None` → refresh → `end_at is None`, `notes == ""`.
  - `test_closure_changes_are_in_history`: create, update reason, delete → `ChangeRecord` rows with
    object_type "portclosure" and actions create / update / delete.
  - `test_is_delayed`:
    - 2:00 → False;
    - 2:01 → True;
    - arrival None → False;
    - berthing None → False.
  - `test_option_kinds_include_delay_and_closure`: "delay" and "closure" are in `OPTION_KIND_KEYS`.
  - `test_vessel_delay_reason_defaults_to_empty`.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_closures`. Expected: ImportError / FAIL.
- [ ] **Step 3: Implement.**
  - Add the constants and the models (`delay_reason = CharField("Delay reason", max_length=100, blank=True)`).
  - Write `PortClosure` with:
    - `port` (PORTS choices, db_index);
    - `start_at` (DateTimeField);
    - `end_at` (null / blank);
    - `reason` (CharField 100);
    - `notes` (CharField 500, blank);
    - `created_at` (auto_now_add).
  - Give `PortClosure` a `__str__`.
  - Run `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations sheet -n port_closures_and_delays`.
  - Add the model to TRACKED and to admin.
- [ ] **Step 4: Run** the tests again, plus `manage.py test sheet.tests_history`. Expected: PASS. Also run
  `makemigrations --check --dry-run` → "No changes detected".
- [ ] **Step 5: Commit** "feat(closures): PortClosure model, delay_reason field, delay / closure option kinds".

### Task 2: Delay reason rule on vessels

**Files:**
- Modify: `sheet/validators.py` (`clean_vessel`)
- Modify: `sheet/serializers.py` (`vessel_to_dict` adds `delay_reason`)
- Modify: `sheet/views.py` (CSV column "Delay reason" right after the time columns, near line 351)
- Modify: `sheet/listing.py` (the search also matches `delay_reason`)
- Test: `sheet/tests_delays.py` (new, `ApiTestCase`)

**Interfaces:**
- Consumes: `constants.is_delayed`, `validators.listed`.
- Produces: `clean_vessel(...)` returns the extra key `delay_reason`. The vessel JSON has `delay_reason`.

- [ ] **Step 1: Write the failing tests.** Helper: POST / PUT a vessel as `alex` with `arrival_at="2026-11-13T08:00"`,
  and `allow("delay", "WEATHER")` in setUp. The tests:
  - `test_delayed_vessel_without_reason_refused`: berthing 10:01 → 400 with the exact message.
  - `test_exactly_two_hours_is_not_delayed`: berthing 10:00, no reason → 201, `delay_reason == ""`.
  - `test_delayed_vessel_with_listed_reason_saved`: berthing 10:01 with "WEATHER" → 201, the value comes back.
  - `test_unlisted_delay_reason_refused`: "NOPE" → 400.
  - `test_delay_reason_from_other_port_refused`: `allow("delay", "SUEZ ONLY", port="suez")` → alex 400.
  - `test_reason_when_not_delayed_refused`: berthing 09:00 with "WEATHER" → 400 with the exact message.
  - `test_saved_reason_kept_when_list_value_removed`: save with WEATHER, delete the Option, PUT the same → 200.
  - `test_absent_key_keeps_stored_reason`: PUT without a `delay_reason` key on a delayed vessel that has one →
    200, reason unchanged.
  - `test_old_delayed_vessel_needs_reason_on_edit`: `Vessel.objects.update(...)` times 8:00 / 12:00 with an empty
    reason; a PUT of the name only → 400.
  - `test_csv_has_delay_reason_column`.
  - `test_search_matches_delay_reason`: `/api/vessels/?q=weather&from=…&to=…` finds it.
- [ ] **Step 2: Run** `manage.py test sheet.tests_delays`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `clean_vessel`, after `_check_time_order(times)`:
  - `sent = data["delay_reason"] if "delay_reason" in data else getattr(existing, "delay_reason", "")`.
  - If `is_delayed(...)`: `reason = listed("delay", sent, port, existing reason)`; if it is empty, raise the message.
  - Else, if `_text(sent)` is non-empty, raise the other message.
  - Else `""`.
- [ ] **Step 4: Run** `manage.py test sheet.tests_delays sheet.tests sheet.tests_input_rules`. Expected: PASS.
- [ ] **Step 5: Commit** "feat(delays): delay reason required when berthing is more than 2 hours after arrival".

### Task 3: Missing details alert (server)

**Files:**
- Modify: `sheet/listing.py`. Rename `missing_agents` → `missing_details(profile, port, today)`; `alerts_response`
  returns key `missing`.
- Modify: `sheet/tests_agents.py`. Update the key and labels ("Arrival agent", "Sailing agent", "Landing agent", and
  so on). The query-count test stays.
- Test: `sheet/tests_alerts_details.py` (new)

**Interfaces:**
- Consumes: `TIME_FIELDS`, `is_delayed`, `SERVICE_TYPES`.
- Produces: `/api/vessels/alerts/` → `{"today", "tomorrow", "missing": [{"id", "name", "date", "missing": [str]}]}`.

- [ ] **Step 1: Write the failing tests.** Patch `timezone.localdate` as `tests_agents` does. The tests:
  - `test_missing_times_listed_in_order`: a past vessel with all agents and no times → `["Arrived", "Berthed",
    "Ops started", "Ops finished", "Sailed"]`.
  - `test_complete_past_vessel_not_listed`: 5 times, both agents, no services, not delayed → `[]`.
  - `test_todays_vessel_not_listed`.
  - `test_old_delayed_vessel_without_reason_listed`: times with a 3h gap, empty reason → `"Delay reason"` sits
    between "Sailed" (if missing) and the agents.
  - `test_full_order`: no ops times, delayed with no reason, no sailing agent, a Landing and a Crew Change with no
    agent → `["Ops started", "Ops finished", "Delay reason", "Sailing agent", "Crew Change agent", "Landing agent"]`.
  - `test_port_user_sees_own_port_only`.
- [ ] **Step 2: Run** `manage.py test sheet.tests_alerts_details sheet.tests_agents`. Expected: FAIL.
- [ ] **Step 3: Implement.** The database filter is `Q(any time __isnull=True) | agent gaps | Q(arrival_at__isnull=False,
  berthing_at__isnull=False, delay_reason="")`. Add the time and delay fields to `.only(...)`. Check delay in Python.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** "feat(alerts): missing details — times, delay reason and agents of past vessels".

### Task 4: Closures API

**Files:**
- Modify: `sheet/access.py` (`scoped_closures`)
- Modify: `sheet/validators.py` (`clean_closure`)
- Create: `sheet/closures.py` (`list_response`, `closure_to_dict`, `save_closure`)
- Modify: `sheet/views.py` (`closures`, `closure_detail`), `sheet/urls.py`
- Test: `sheet/tests_closures.py` (`ClosureApiTests(ApiTestCase)`)

**Interfaces:**
- Produces:
  - `access.scoped_closures(profile, port=None) -> QuerySet[PortClosure]`.
  - `validators.clean_closure(data, profile, existing=None) -> dict(port, start_at, end_at, reason, notes)`.
  - `closures.closure_to_dict(c, profile) -> {id, port, port_label, start_at, end_at, hours, reason, notes, can_edit}`.
    The times use `serializers.local_iso`; `hours` is `round(h, 1)` or None.
  - `closures.list_response(profile, params) -> {"closures": [...]}`: `from` / `to` are ISO dates (Cairo); the
    overlap filter is `start_at < start of (to + 1 day)` and (`end_at` null or `end_at >= start of from`).
  - Routes: `GET/POST /api/closures/` (name `api_closures`) and `PUT/DELETE /api/closures/<pk>/` (name `api_closure`),
    both `@json_api`, audited `closure.create|update|delete`.

- [ ] **Step 1: Write the failing tests.** setUp: `allow("closure", "WEATHER")`. The tests:
  - `test_port_user_creates_closure_for_own_port_whatever_port_sent`: alex posts port "suez" → 201, port
    "alexandria".
  - `test_admin_creates_closure_for_any_port`.
  - `test_admin_unknown_port_refused`.
  - `test_viewer_cannot_write`: POST → 403. The viewer's GET lists every port.
  - `test_port_user_cannot_see_or_edit_other_port`: the suez closure id → 404 for alex on PUT / DELETE, and absent
    from alex's GET even with `?port=suez`.
  - `test_reason_required_and_listed`: empty → "Choose a closure reason."; "NOPE" → 400; a suez-only value for alex →
    400.
  - `test_reopened_before_closed_refused`.
  - `test_start_required`.
  - `test_notes_too_long_refused` (501 chars).
  - `test_range_overlap_filter`: a closure Nov 10 → Nov 12 is found by from=Nov 12, to=Nov 30, and not by from=Nov 13.
  - `test_open_closure_overlaps_any_later_range`.
  - `test_hours_and_local_times_in_json`: 06:00 → 14:00 gives `hours == 8.0` and `start_at == "…T06:00"`.
  - `test_edit_and_delete_recorded_in_history_and_audit`.
- [ ] **Step 2: Run** `manage.py test sheet.tests_closures`. Expected: FAIL.
- [ ] **Step 3: Implement**, mirroring `logistics` / `booking_detail`. The labels for `_local_datetime` are
  "Closed from" and "Reopened". An empty start gives "Closed from is required."
- [ ] **Step 4: Run** `manage.py test sheet`. Expected: all PASS.
- [ ] **Step 5: Commit** "feat(closures): port closures API, port-scoped, reasons from Master data".

### Task 5: Master data counts for the new lists

**Files:**
- Modify: `sheet/views.py` (`_usage_counts`). "delay" counts vessels by `delay_reason`; "closure" counts
  `scoped_closures(profile)` by `reason`. Exclude both from the generic loop (which uses kind == field).
- Modify: `sheet/static/sheet/js/pages/master.js` (`usageUnit`: closure → "closure(s)", else as now)
- Test: `sheet/tests_options.py`

- [ ] **Step 1: Write the failing tests.**
  - `test_delay_and_closure_values_can_be_added`.
  - `test_delay_usage_counts_vessels`.
  - `test_closure_usage_counts_closures_in_scope`: alex doesn't count suez closures.
- [ ] **Step 2: Run** `manage.py test sheet.tests_options`. Expected: FAIL (KeyError / wrong count).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** "feat(master data): Delay reason and Closure reason lists with usage counts".

### Task 6: Front end, delay reason in the vessel form, and the Missing details alert

**Files:**
- Modify: `sheet/static/sheet/js/modals/vessel.js`. Add a `delay_reason` select under the times (wrapped in an
  element with `hidden`). It is shown when `isDelayed(arrival, berthing)` holds for the inputs, or when the vessel
  has a reason. It is re-evaluated on `input` of either time and on "Now". It follows a port change, like
  `FORM_LISTS`.
- Modify: `sheet/static/sheet/js/calc.js` or `util.js`: `isDelayed(arrivalLocal, berthingLocal) -> boolean` (more
  than 2h, pure). Unit test it in `tools/parsing_test.js`.
- Modify: the vessel-payload code in `actions.js` / `vessel.js` so that it always sends `delay_reason` (the select's
  value, hidden or not).
- Modify: `sheet/static/sheet/js/modals/summary.js` shows "Delay reason: X" when set.
- Modify: `data.js`, `state.js` and `render/notifications.js`: the key is `missing`; the titles are "Missing
  details" and "· N missing details".

- [ ] **Step 1: Write the failing tests** in `tools/parsing_test.js`:
  - `isDelayed('2026-11-13T08:00', '2026-11-13T10:00') === false`;
  - `'…T10:01'` → true;
  - an empty value → false.
- [ ] **Step 2: Run** `cd tools && npm run test:parsing`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm run test:parsing` and `manage.py test sheet.tests_frontend_safety sheet.tests_look`.
  Expected: PASS.
- [ ] **Step 5: Commit** "feat(ui): delay reason in the vessel form, Missing details alert".

### Task 7: Front end, Port closures page

**Files:**
- Modify: `sheet/templates/sheet/icons.svg`: a new `i-ban` icon (a circle with a slash, the same stroke style).
- Modify: `dom.js` `ICONS` (add 'ban').
- Modify: `sheet/templates/sheet/index.html`:
  - a nav item `data-page="closures"` between Transport and Calculations;
  - a `<main class="page" id="page-closures" hidden>` with a filter bar (from / to date inputs, a port select for
    non-port users) and the `#closures-body` table;
  - **+ Add** when `me.canEdit`.
- Create: `sheet/static/sheet/js/pages/closures.js` (`closuresPage = { load() }`), with:
  - the default range from `state.defaultRange`;
  - the columns Port (when not a port user), Closed from, Reopened (or "Still closed"), Hours, Reason, Notes;
  - a row click → open the dialog when `can_edit`;
  - a trash button → confirm → DELETE.
- Create: `sheet/static/sheet/js/modals/closure.js` (`openClosureDialog(id|null)`), with:
  - Port (admins);
  - Closed from and Reopened (datetime-local + Now);
  - Reason (`optionChoices('closure', current, port)`);
  - Notes (maxlength 500);
  - Save / Delete.
- Modify: `router.js` (TITLES `closures: 'Port closures'`, load) and `actions.js` (`closure-new`, `closure-open`,
  `closure-save`, `closure-del`, `closure-now`).
- Modify: `sheet/static/sheet/css/app.css` only if needed (reuse the bookings classes).
- Test: `sheet/tests_look.py` (the sprite equals ICONS, already generic); the smoke test in Task 8.

- [ ] **Step 1: Write the failing test.** In `sheet/tests_closures.py` add
  `test_page_has_closures_nav_and_page`: GET "/" as alex contains `data-page="closures"` and `id="page-closures"`.
  The viewer's page has no `data-act="closure-new"`.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `manage.py test sheet` and `cd tools && npx eslint` (through `npm run check` later). Expected:
  PASS.
- [ ] **Step 5: Commit** "feat(ui): Port closures page".

### Task 8: Demo data and smoke test

**Files:**
- Modify: `sheet/management/commands/seed_demo.py`, adding:
  - All-ports delay reasons: WAITING FOR BERTH, PORT CLOSED, WEATHER, PILOT DELAY, OTHER;
  - closure reasons: WEATHER, FOG, STRIKE, OTHER (use the case the other seeded lists use);
  - an Alexandria closure from yesterday 06:00 to 14:00 (WEATHER);
  - an open Port Said closure (FOG).
- Modify: `tools/ui_smoke_test.js`:
  - the "Missing details" text and labels ("Sailing agent", "Landing agent", "Berthed");
  - the Port closures page:
    - alex sees the Alexandria closure, not the Port Said one; alex adds, edits and deletes one;
    - the admin sees both;
    - the viewer sees both, with no + Add;
    - the suez run sees neither the Alexandria nor the Port Said closure.
  - the vessel form: set arrival 08:00 / berthing 11:00 → the delay select appears → save without a reason → the
    error is shown → pick one → saved.

- [ ] **Step 1: Update the test and seed**, then run `manage.py test sheet.tests.SeedCommandTests`. Expected: PASS.
- [ ] **Step 2: Run the smoke test** on a scratch database (see CLAUDE.md) for alex, admin, viewer and suez, at least
  30 s apart. Expected: every check passes.
- [ ] **Step 3: Commit** "test(smoke): port closures, delay reason, missing details".

### Task 9: Docs and the full check

**Files:** `docs/STATUS.md`, `README.md` and `SECURITY.md` (test count; SECURITY A01 mentions closure scoping),
and `CLAUDE.md` (an architecture paragraph for closures, plus the missing-details alert).

- [ ] **Step 1: Run** `cd tools && npm run check`. Expected: everything green; note the backend test count.
- [ ] **Step 2: Update the docs** with that count and the new migration `0013` (to apply on the user's database).
- [ ] **Step 3: Commit** "docs: port closures, delay reason, missing details".
- [ ] **Step 4: Fresh review** of the whole branch (`superpowers:requesting-code-review`, most capable model). Fix
  the important findings test-first; list the rest in STATUS "Left open". Then ask the user before merging.
