# Edit-conflict Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A save of a vessel, service, hotel stay, transfer or port closure that someone else changed since it was opened saves nothing and shows who, when and which fields, with "Show their version" / "Save mine anyway".

**Architecture:** A `version` counter on the five models; the dialogs send the version they opened with; the update views lock the row, refuse a stale version with a 409 described from the History, and raise the version only when the save really changed something. The admin pages raise it too.

**Tech Stack:** Django 5.2, vanilla ES modules (`dom.js`), jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-21-edit-conflict-warning-design.md`

## Global Constraints

- Only person saves raise `version`; `crewbookings.sync`, the sailing-day rule and other system writes never do. Creating starts at 1.
- A save that changes nothing (booking guests included) does not raise `version` and answers 200.
- Missing / non-whole-number `version` on an update → 400 `"This page is out of date. Reload it and try again."`
- Stale `version` → 409, body `{"error": "conflict", "conflict": {"who", "same_person", "at", "fields", "version"}}`, nothing saved.
- Everyone who gets the warning sees name, time and fields (port users included); the History page stays admin-only and never shows `version`.
- Not checked: deletes, Garbage & Sludge boxes, exchange rates, disposal prices, Master data, user accounts.
- Project rules (CLAUDE.md): `json_api`, scoped queries, one transaction per write, `dom.js` only, no inline style, `data-act` buttons, LF line endings, docs updated, `npm run check` green.

## Review Focus

- A booking saved with the same guests in a new order or re-picked identically → no version change, no false warning (Task 2 test `test_booking_same_guests_no_bump`).
- A Crew Change save that makes `crewbookings.sync` rewrite draft bookings → the drafts' versions don't move, so an open draft dialog doesn't warn (Task 2 test `test_sync_does_not_bump_drafts`).
- "Save mine anyway" after a **third** save landed meanwhile → warns again, not overwrites (Task 2 test `test_force_with_old_conflict_version_warns_again`).
- A port user seeing a conflict caused by an admin → gets the name (decision), but still only for records in their port (Task 2 test `test_port_user_conflict_scoped`).
- An admin-page edit while a dialog is open → the dialog's save warns (Task 2 test `test_admin_edit_raises_version`).

---

### Task 1: The counter and the conflict description

**Files:**
- Modify: `sheet/models.py` (the five models), `sheet/errors.py`, `sheet/static/sheet/js/pages/history.js` (skip `version`)
- Create: `sheet/migrations/0018_edit_version.py`, `sheet/conflicts.py`, `sheet/tests_conflicts.py`

**Interfaces:**
- Produces:
  - `version = models.PositiveIntegerField(default=1)` on `Vessel`, `Service`, `HotelStay`, `Transfer`, `PortClosure`.
  - `errors.Conflict(ApiError)`, `status = 409`; raised as `Conflict("conflict", conflict={...})`.
  - `conflicts.sent_version(payload: dict) -> int` — the payload's `version`; `int` ≥ 1 (not `bool`), else `BadRequest(OUT_OF_DATE)`. `OUT_OF_DATE = "This page is out of date. Reload it and try again."`
  - `conflicts.snapshot(instance) -> tuple` — the instance's stored values without `id`, `created_at`, `version` (use `history._values`), plus for `HotelStay` / `Transfer` the ordered guest values (`name`, `group`, `crew_uid`, ...) without ids.
  - `conflicts.describe(instance, sent: int, user) -> dict` — `{"who", "same_person", "at", "fields", "version"}` (algorithm below).
  - `conflicts.check(instance, sent: int, user) -> None` — raises `Conflict` with `describe(...)` when `instance.version != sent`.
  - `conflicts.bump_if_changed(instance, before: tuple) -> None` — if `snapshot(fresh row) != before`: `version += 1` and `save(update_fields=["version"])` (so the History holds a `{"version": [n, n+1]}` record).

**`describe` algorithm** (the History has, per real save, the field records then one `version` record):
1. `records` = `ChangeRecord` of this `object_type` / `object_id`, oldest first.
2. Baseline = the record whose `changes["version"][1] == sent` (or, for `sent == 1`, the `create` record; none found → the start).
3. `after` = records after the baseline. `who` / `at` / `same_person` from the **last** record in `after` that has a `version` change. `at` = Cairo `"%H:%M"` if today, else `"%d/%m %H:%M"`. `same_person` = its `user_id == user.id`.
4. `fields` = the union, in first-seen order, of `changes` keys in `after` other than `version`, as labels: model field `verbose_name` capitalised (Vessel `arrival_agent` → "Arrival agent"); a `Service`'s `data` → each top-level key of `data` whose old / new value differs, camelCase split and capitalised (`onSigners` → "On signers"); `service_type` → "Type". A booking with no such field → `["Guests"]`.
5. `version` = `instance.version`.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_conflicts.py` (base `tests.ApiTestCase`; make history records by saving under `history` with a fake request as the other tests do, or through the API once Task 2 lands — here, set them up by calling `vessel.save()` + `conflicts.bump_if_changed`):
  - `test_new_records_start_at_version_one` — each of the five models created → `version == 1`.
  - `test_sent_version_refuses_missing_and_non_numbers` — `{}`, `{"version": "2"}`, `{"version": True}`, `{"version": 0}`, `{"version": 1.5}` → `BadRequest` with `OUT_OF_DATE`; `{"version": 3}` → `3`.
  - `test_bump_only_when_changed` — `bump_if_changed` after saving the same values → version stays 1; after changing `berthing_at` → 2.
  - `test_describe_names_last_person_and_all_fields` — vessel: user A changes `berthing_at` (v2), user B changes `sailing_agent` (v3); `describe(v, 1, admin)` → `who == "B"`, `fields == ["Berthing time", "Sailing agent"]` (use the actual verbose names), `version == 3`, `same_person is False`.
  - `test_describe_service_data_keys` — Service `data` `onSigners` changed → `"On signers" in fields`, `"Data" not in fields`.
  - `test_describe_booking_guests_only` — a booking whose only change was its guests → `fields == ["Guests"]`.
  - `test_history_page_hides_version` — `GET /api/history/` as admin: no change entry lists `version`. (If the API returns raw changes, filter `version` in `history.js` instead and assert in the dom/smoke test; record which as a Ruling.)
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_conflicts` → fails (no `version` / no module).
- [ ] **Step 3: Implement** the field, `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations sheet --name edit_version` (check it only adds five fields), `errors.Conflict`, `conflicts.py`, the History filter.
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet` → all pass; `venv/Scripts/python.exe -m ruff check sheet/` clean.
- [ ] **Step 5: Commit** `feat(conflicts): version counter and conflict description`

### Task 2: The five update views and the admin pages

**Files:**
- Modify: `sheet/views.py` (`vessel_detail`, `service_detail`, `closure_detail`, `booking_detail`), `sheet/serializers.py` (`vessel_to_dict`, `service_to_dict`), `sheet/logistics.py` (`booking_to_dict`), `sheet/closures.py` (`closure_to_dict`), `sheet/admin.py`, the API test helpers that send updates (existing tests must send `version`)
- Create: `sheet/tests_conflicts_api.py`

**Interfaces:**
- Consumes: Task 1's `sent_version`, `snapshot`, `check`, `bump_if_changed`.
- Produces: every dict above has `"version"`; each update view, for `PUT` / `PATCH`, inside the request transaction: `locked = Model.objects.select_for_update().get(pk=obj.pk)`, `sent = sent_version(payload)`, `check(locked, sent, request.user)`, `before = snapshot(locked)`, the existing save on `locked`, `bump_if_changed(locked, before)`, response as today (now with the new `version`). Read the JSON body once and pass it on (the views currently call `read_json` inside helpers: pass the parsed payload, or read the version from `read_json(request)` — Django caches `request.body`).
- Admin: `version` read-only on the four admin classes and `ServiceInline`; `VesselAdmin` / `HotelStayAdmin` / `TransferAdmin` / `PortClosureAdmin` `save_model`: when `change and form.has_changed()` → `obj.version += 1` before saving; `save_formset`: a changed / added / deleted guest form → the booking's `version += 1` (once per save); a changed `ServiceInline` form → that service's `version += 1`.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_conflicts_api.py` (sign in with `self.login(...)`, update through the API):
  - `test_update_returns_new_version` — PUT vessel with its `version` 1 and a change → 200, `version == 2`.
  - `test_stale_version_refused_nothing_saved` — two PUTs both with version 1, the second changing `name` → second 409, `body["error"] == "conflict"`, `body["conflict"]["who"] == "admin"` (the first saver), `"Name"` or the changed field in `fields`; the vessel keeps the first save's values.
  - `test_missing_version_is_out_of_date` — PUT without `version` → 400 with `OUT_OF_DATE`, nothing saved. Same for service, hotel, transfer, closure (one subTest each).
  - `test_same_values_no_bump` — PUT with no change → 200, `version` unchanged; then a PUT with the old version and a change → 200 (no false alarm).
  - `test_booking_same_guests_no_bump` — PUT a hotel stay with exactly its guests → version unchanged.
  - `test_sync_does_not_bump_drafts` — a Crew Change with a Needs-hotel member makes draft bookings; edit the crew member's flight → the drafts' `version` stays 1.
  - `test_force_with_old_conflict_version_warns_again` — 409 gives `version` 2; a third save makes it 3; resending with 2 → 409 again; resending with 3 → 200.
  - `test_same_person_flag` — the same user saves twice with version 1 → 409 with `same_person` true.
  - `test_port_user_conflict_scoped` — admin changes an Alexandria vessel; `alex` saving the old version → 409 naming `admin`; `alex` PUT on a Suez vessel → 404 as today.
  - `test_admin_edit_raises_version` — change a PortClosure through the admin change form (POST to its admin URL as a superuser who passed two-step) → its `version == 2`; editing a hotel stay's guest inline → the stay's `version == 2`.
  - `test_service_version_in_vessel_json` — `GET /api/vessels/<id>/` → each service has `version`.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_conflicts_api` → fail.
- [ ] **Step 3: Implement** the views, serializers and admin hooks; update existing tests' update payloads to send the current `version` (helper: read it from the GET or the model).
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet` → all pass; ruff clean.
- [ ] **Step 5: Commit** `feat(conflicts): stale saves refused on vessels, services, bookings and closures`

### Task 3: The warning in the dialogs

**Files:**
- Modify: `sheet/static/sheet/js/api.js` (errors carry `status` and `data`), `sheet/static/sheet/js/modals/vessel.js`, `modals/service.js`, `modals/booking.js`, `modals/closure.js`, `sheet/static/sheet/js/actions.js`, `sheet/static/sheet/app.css` (panel, tokens only), `tools/ui_smoke_test.js`
- Create: `sheet/static/sheet/js/conflict.js`

**Interfaces:**
- Consumes: Task 2's `version` in every dict and the 409 body.
- Produces:
  - `api()` throws an `Error` with `.status` and `.data` (the JSON body); message unchanged.
  - Each dialog keeps the opened record's `version` (vessel form, service form: in `state.ctx.version`; booking and closure: in their own module state), sends it as `version` with every update, and replaces it with the response's `version` after a successful save.
  - `conflict.js`: `showConflict(conflict, noun, { reload, force })` puts a panel (`#conflict-panel`, built with `h`) at the top of the open dialog with the text below and two buttons `data-act="conflict-reload"` ("Show their version") and `data-act="conflict-force"` ("Save mine anyway"); `conflictAction(name)` runs the stored callback; `clearConflict()` removes the panel. `force` resends the dialog's save with `conflict.version`; `reload` reopens the dialog from the server.
  - Text: other person — `"{who} changed this {noun} at {at} while you had it open."` / `"They changed: {fields joined by ", "}. Nothing of yours was saved."`; same person — `"You changed this {noun} at {at} in another window."` / `"Changed: {fields}. Nothing of yours was saved."`. Nouns: `vessel`, `service`, `hotel stay`, `transfer`, `port closure`. Status line: `setStatus('error', 'Not saved')`.
  - The save path: `mutate` shows its usual error for every failure **except** `status === 409`, which goes to `showConflict` instead (no generic error box).

- [ ] **Step 1: Write the failing smoke checks** (`tools/ui_smoke_test.js`, admin and alex runs, after the existing vessel-form checks): open a vessel's form; change its POC via a direct `w.fetch` PUT (with the version from `GET /api/vessels/<id>/` and the CSRF token from the page's meta tag); change the form's name and Save → `#conflict-panel` shows `"changed this vessel"` and `"POC"`, the form still holds the typed name, the vessel's name on the server is unchanged; click **Save mine anyway** → saved (status `Saved`, server has the new name); repeat the setup and click **Show their version** → the form shows the other POC and no panel. Same person: the fetch is the same user → text contains `"in another window"`. One closure check: same flow on the closure dialog with "Save mine anyway".
- [ ] **Step 2: Run** the smoke test for alex (fresh database, `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) → new checks fail.
- [ ] **Step 3: Implement** `api.js`, `conflict.js`, the four dialogs, actions, CSS.
- [ ] **Step 4: Run** `cd tools && npm run check` → green; smoke test alex, admin, viewer, suez → ALL PASSED.
- [ ] **Step 5: Commit** `feat(conflicts): warning panel with Show their version / Save mine anyway`

### Task 4: Docs, review, finish

- [ ] **Step 1:** Update `docs/STATUS.md` (where things stand: branch, **migration 0018 needed**; built table; decisions: option 2, approach A, names shown to everyone; remove "last save wins" from Left open), `CLAUDE.md` (replace the "no edit-conflict check" sentence with a short **Edit conflicts** paragraph: `version`, `conflicts.py`, 409, admin hooks, `conflict.js`), `docs/DEPLOYMENT.md` §11 "two people edit", `README.md` / `SECURITY.md` test counts.
- [ ] **Step 2:** `cd tools && npm run check` green; fresh reviewer (most capable model) on the whole branch; Critical / Important fixed test-first; minors to STATUS "Left open".
- [ ] **Step 3: Commit** `docs: edit-conflict warning` — merge into `main` only when the user agrees.
