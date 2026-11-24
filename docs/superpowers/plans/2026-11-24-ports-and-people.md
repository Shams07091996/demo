# Ports and People (access rework, piece 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ports become a table Admins manage; Admin = superuser; every other account is a User with a home port
and extra ports who works fully in all of them; the Read-only role is gone.

**Architecture:** `Port` model + `ports.py` (labels, keys, validation) replaces `constants.PORTS / PORT_KEYS /
PORT_LABELS`; `Profile.role` becomes `home_port` + `ports` (JSON list); `access.py` holds every rule
(`ports_of`, `scoped_*`, `require_port`, `require_admin` = superuser) and every route moves to it; the front end
reads `ME.ports` / `ME.homePort` / `ME.isAdmin`; a Ports page and the Accounts page's port boxes.

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-24-access-rework-design.md` — section "Piece 1" (pieces 2–3 are not
part of this plan).

## Global Constraints

- Admin ⇔ `user.is_superuser`. Every Admin-only rule (`access.require_admin`) checks that, never a stored role.
- A User's `ports` always contains `home_port`; keys must exist in `Port`; a **new** record (vessel, closure, Master
  data value, garbage price) needs an **active** port; existing records keep theirs.
- A User asking for a port that isn't theirs gets **all of theirs, never wider**; writing a record into a port that
  isn't theirs → 403 `Forbidden("That port isn't one of yours.")`.
- Port key `[a-z0-9]{2,20}` (from the name, a digit added if taken), fixed forever; name 2–40 chars, unique
  ignoring case; no delete.
- Records keep their port key strings (no foreign keys); `choices=PORTS` removed from model fields.
- The app is not live: the migration may turn accounts off, but must not delete any vessel / closure / option /
  price / history row.
- No `innerHTML` etc.; no placeholders / help text; LF files; `npm run check` green; smoke passes for every role run.

## Review Focus

1. **`?port=suez` from an Alexandria + Damietta User** on every list, export, dashboard, alert and calculations
   route → their two ports only (Task 3 `test_asked_port_not_theirs_is_never_wider`, one assertion per route).
2. **Moving a vessel / closure into a port that isn't theirs** with a PUT (and creating one there) → 403, nothing
   saved (Task 3 `test_write_into_foreign_port_refused`).
3. **A turned-off port**: no new vessel / closure / option / price there (400), but existing ones still edit and
   list for its people (Task 4 `test_inactive_port_blocks_new_records_only`).
4. **Renaming a port** shows the new name on the vessel JSON, closures, receipt, data export and management Excel
   (Task 1 `test_rename_reaches_every_label`).
5. **A User with no ports** (a turned-off Read-only account turned back on) is stopped after sign-in with a plain
   page, and the API answers 403, never an error ref (Task 2 `test_user_without_ports_is_blocked`).

---

### Task 1: The Port table and port labels from it

**Files:** Create `sheet/ports.py`, `sheet/migrations/0023_port.py` (model + data step creating the four ports in
today's order, positions 0–3), `sheet/tests_ports.py`. Modify `sheet/models.py` (`Port`; remove `choices=PORTS` from
`Vessel.port`, `PortClosure.port`, `DisposalPrice.port`, in the same migration), `sheet/history.py` (`Port` in
`TRACKED`), and every `PORT_LABELS` / `PORTS` / `PORT_KEYS` user except `access.py`, `models.py` Profile and
`validators.clean_account` (Task 2): `closures.py`, `dataexport.py`, `disposal.py`, `logistics.py`, `receipt.py`,
`report.py`, `serializers.py`, `validators.py` (port checks), `views.py` (labels, `ports-data`).

**Interfaces — produces:**
- `models.Port(key CharField(20, unique), name CharField(40), active Bool=True, position PositiveInteger)`,
  ordered by `position, name`.
- `ports.labels() -> dict[key, name]` (all ports), `ports.label(key) -> str` (key itself if unknown),
  `ports.keys(active_only=False) -> list[str]` in order, `ports.exists(key, active_only=False) -> bool`,
  `ports.ordered() -> list[(key, name)]`. One query per request at most (cache per request via
  `history.current_request()` or recompute — builder's choice, tested by a query count).
- `ports.make_key(name) -> str` (lower-case a–z / 0–9 of the name, cut to 18, `2`, `3`… added if taken).
- `ports-data` json_script becomes `[{key, label, active}]`.

- [ ] **Step 1: Failing tests** in `tests_ports.py`: `test_four_ports_after_migration` (keys / names / order);
  `test_make_key` (`"Port Said"` → `portsaid`, taken → `portsaid2`, `"Abu Qir!"` → `abuqir`); `test_unknown_port_refused`
  (vessel POST with `port: "nowhere"` as admin → 400); `test_rename_reaches_every_label` (rename Alexandria to
  `"Alexandria West"` in the DB, then vessel JSON `port_label`, closure `port_label`, receipt GET `port`, the data
  export Calculations sheet port cell and the management Excel port rows all show it); `test_labels_one_query`.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_ports` → FAIL (no model).
- [ ] **Step 3: Implement**; `constants.PORTS` / `PORT_LABELS` stay only for the migration's seed and Task 2's
  conversion (delete them in Task 2 once nothing imports them). `report.py`'s loops over `PORTS` use
  `ports.ordered()`.
- [ ] **Step 4: Run** `manage.py test sheet` → all OK (no behaviour change except the labels' source).
- [ ] **Step 5: Commit** `feat(ports): port table`.

### Task 2: Admin = superuser, Users with ports, Read-only gone

**Files:** Modify `sheet/models.py` (Profile: `home_port CharField(20, blank=True)`, `ports JSONField(default=list)`;
remove `role`; `is_admin` → `self.user.is_superuser`; `port` property kept **for this task only** = `home_port` when
`ports == [home_port]` else None — removed in Task 3; `can_edit` → `is_admin or bool(ports)`; `may_be_exempt` →
not superuser / staff), migration `0024_profile_ports.py` (add fields → data step → remove `role`), `sheet/access.py`
(`profile_of` defaults no ports; `require_accounting` → admin only; `require_admin` uses superuser), `sheet/twostep.py`
(`next_step` → `"no_port"` for a non-admin with empty ports after the password step), `sheet/views_twostep.py` +
template (the blocked page "Your account has no port yet. Ask an admin."), `sheet/middleware.py` (API 403 for that
step), `sheet/admin.py` (ProfileInline shows `home_port`, `ports`), `sheet/tests.py` (`make_user`: role `"admin"` →
`create_superuser` + Profile with no ports; a port role → `home_port=role, ports=[role]`; **`viewer` becomes a User
with ports alexandria + portsaid + damietta, home alexandria**), `sheet/management/commands/seed_demo.py` (same:
`viewer` → those three ports; `admin` superuser), `config.js` `IS_ACCOUNTING` → `ME.isAdmin`, and every test that
relied on the Read-only role.

**Data step (exact):** port role → `home_port = ports = [role]`; `admin` role and not superuser → `ports` = the four
keys, home `alexandria`; `readonly` → `user.is_active = False`, no ports; superuser → no ports; any non-superuser with
`is_staff` → `is_staff = False`.

**Interfaces — produces:** `Profile.home_port`, `Profile.ports`, `Profile.is_admin` (superuser),
`twostep.NO_PORT_STEP = "no_port"`.

- [ ] **Step 1: Failing tests** (`tests_ports.py` class `PeopleTests`): `test_migration_converts_accounts` (use
  `MigrationExecutor` like other migration tests in the repo, or call the data step function directly: assert the five
  rules above); `test_admin_is_superuser` (a non-superuser can't reach `/api/rates/` POST, `/api/history/`,
  `/api/accounting/`; a superuser can); `test_user_without_ports_is_blocked` (signed-in, two-step passed, no ports →
  `GET /` redirects to the no-port page, `GET /api/vessels/` → 403 JSON without `ref`); `test_exempt_rule_uses_superuser`.
- [ ] **Step 2: Run** `manage.py test sheet.tests_ports` → FAIL.
- [ ] **Step 3: Implement.** Then run the whole suite and fix each test that assumed Read-only: a test that checked
  "read-only can't write" is rewritten against the new rules (e.g. accounting → only admin; "can't write" → a port
  user writing outside their ports, Task 3 adds the full set) or deleted if the behaviour is gone; ledger each group
  of such changes as one Ruling. `accounts.py` / `clean_account`: `role` → `home_port` + `ports` (Task 5 adds the UI;
  here: the API accepts `{home_port, ports}`, `list_response()` returns `ports` per account and `"ports": [[key, name,
  active]]` instead of `roles`; Admin rows unchanged read-only).
- [ ] **Step 4: Run** `manage.py test sheet` → OK.
- [ ] **Step 5: Commit** `feat(access): admins are superusers, users have ports`.

### Task 3: Several ports per User, on every server route

**Files:** `sheet/access.py` (`ports_of(profile) -> list | None` (None = Admin, no limit); `scoped_vessels(profile,
port)` / `scoped_closures` → `port__in` their ports, narrowed to `port` only when it is one of theirs (Admins: any
existing port); `require_port(profile, key, new=False)`), and every reader of `profile.port`: `validators.clean_vessel`
(port from payload or existing or home port; must pass `require_port`; ship OPR `listed` against the chosen port),
`clean_closure`, `closures.py` (`can_edit` = admin or port in theirs), `disposal.py` (prices `port__in`),
`serializers.option_to_dict` (`editable` = admin or `option.port in ports`), `views._options_json` (`port__in ["",
*ports]`), `views.options` POST (non-admin: `port` must be one of theirs, default home; `""` refused), option DELETE,
`views` line ~204 CSV port; `dashboard.py`, `listing.py` alerts, `calculations.py`, `services.py`, `logistics.py`,
`dataexport.py`, `report.py`, `views.history_list` (unchanged: admin-only) — wherever a port param is read, through
`access`. Remove the `Profile.port` compatibility property.

- [ ] **Step 1: Failing tests** (`tests_ports.py` class `MultiPortTests`, user `viewer` = alexandria + portsaid +
  damietta, vessels in all four ports): `test_lists_cover_all_their_ports` (vessels, services, hotels, transfers,
  closures, disposal, calculations, dashboard, alerts, CSV, data export, management Excel: alexandria + portsaid +
  damietta rows, no suez); `test_asked_port_not_theirs_is_never_wider` (each of those with `port=suez` → same as no
  port); `test_asked_port_narrows` (`port=portsaid` → only Port Said); `test_write_into_foreign_port_refused` (vessel
  POST / PUT moving to suez, closure POST suez, option POST suez → 403, nothing saved); `test_works_fully_in_extra_port`
  (vessel, service, booking, closure, option, disposal quantities in Damietta → 200); `test_option_all_ports_admin_only`;
  `test_new_vessel_defaults_to_home_port`.
- [ ] **Step 2: Run** `manage.py test sheet.tests_ports.MultiPortTests` → FAIL.
- [ ] **Step 3: Implement.** `grep -n "profile.port\b" sheet/*.py` must return nothing outside tests at the end.
- [ ] **Step 4: Run** `manage.py test sheet` → OK.
- [ ] **Step 5: Commit** `feat(access): users work in all their ports`.

### Task 4: Ports page (API and UI)

**Files:** `sheet/ports.py` (`port_to_dict`, `list_response`, `save_port(payload, existing=None)`), 
`validators.clean_port` (name 2–40 refused when longer / empty, unique ignoring case; `active` bool),
`views.ports_list` (GET / POST) and `views.port_detail` (PUT, by key), `urls.py` (`api/ports/`, `api/ports/<key>/`),
`require_admin` on all three (GET too), `audit` `port.create` / `port.update`; template nav item **Ports** (Admins
only, after Accounts, icon `i-anchor`) and `#page-ports`; `js/pages/ports.js`, `js/modals/port.js`, `actions.js`,
`router.js`; `ME`'s port list refreshed after a save (`refreshPorts()` re-fetches `/api/ports/` for admins and updates
`PORTS` / `PORT_LABEL` in `config.js`, which become `let` exports with an updater, or the page reloads — builder's
choice, tested in the smoke run).

- [ ] **Step 1: Failing tests** (`tests_ports.py` class `PortsApiTests`): `test_admin_only` (viewer / alex 403 on GET,
  POST, PUT); `test_add_rename_turn_off` (POST `{"name": "Dekheila"}` → 201 key `dekheila`, active; PUT name / active);
  `test_name_rules` (empty, 41 chars, `"alexandria"` duplicate ignoring case → 400); `test_key_never_changes_on_rename`;
  `test_inactive_port_blocks_new_records_only` (turn Damietta off: new vessel / closure / option / price there → 400
  "That port is turned off.", existing Damietta vessel PUT → 200, still listed for viewer); `test_no_delete` (DELETE →
  405); a History record exists for each change.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** The Ports list shows Name, Key, On / Off, Vessels count, Users
  count; **+ Add port**; a row opens rename + Turn off / on.
- [ ] **Step 4: Run** `manage.py test sheet.tests_ports` → OK.
- [ ] **Step 5: Commit** `feat(ports): ports page`.

### Task 5: Accounts page with ports

**Files:** `js/pages/accounts.js`, `js/modals/account.js` (Role select → **Home port** select of active ports +
**Extra ports** ticks; the home port's tick is checked and disabled), `accounts.py` / `clean_account` (already take
`home_port` / `ports` from Task 2: here make sure a new account needs a home port, extra ports must exist and be
active **unless already on the account**, the home port is always added to `ports`), the list's **Ports** column
("Alexandria (home), Damietta"; Admin rows "Admin · all ports").

- [ ] **Step 1: Failing tests** (`tests_accounts.py`): `test_home_port_required`, `test_ports_must_exist_and_be_active`
  (an inactive port already on the account may stay), `test_home_port_always_in_ports`, `test_list_shows_ports`;
  existing account tests updated from `role` to ports.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `manage.py test sheet.tests_accounts` → OK.
- [ ] **Step 5: Commit** `feat(accounts): ports on the accounts page`.

### Task 6: Front end for several ports, seed and smoke

**Files:** `views.index` `me` (`ports`: their port keys, or every key for Admins; `homePort`; `isAdmin`; drop `role`,
`port`, `seesAll`; `multiPort` = admin or more than one port), `config.js` (`MY_PORTS` = active ports of `ME.ports`
with labels; `IS_ACCOUNTING` removed in favour of `ME.isAdmin`), every `ME.port` / `ME.seesAll` / `ME.role` reader
(`main.js` role label → "Admin" or the port names; `modals/closure.js`, `modals/ship.js`, `modals/vessel.js`,
`quickAdd.js`, `render/list.js`: default `ME.homePort`, port select of `MY_PORTS` whenever more than one;
`pages/bookings.js`, `calculations.js`, `closures.js`, `disposal.js`, `services.js`: port filter / Port column when
`ME.multiPort`, its options only `MY_PORTS` (+ "All my ports"); `pages/master.js`: the add box's port select lists the
User's ports, Admins also "All ports"), the template's `me.canEdit` / `me.isAdmin` uses, `tools/ui_smoke_test.js`.

- [ ] **Step 1: Failing smoke expectations** in `tools/ui_smoke_test.js`: the `viewer` run is now the **three-port
  User** — replace its read-only checks with: sidebar has no History / Accounts / Ports; the vessel list port filter
  offers exactly Alexandria / Port Said / Damietta; quick add and the vessel form offer those three, default Alexandria;
  a vessel saved in Damietta appears; no Suez vessel anywhere; Calculations has no Open / Closed buttons. `admin` run:
  the Ports page lists four ports, adds `Smoke<timestamp>` port, renames it, turns it off, and the Accounts dialog
  shows Home port + Extra ports. `alex` / `suez` runs: one port, no port filter. Template test in `tests_ports.py`:
  `test_nav_ports_admin_only`.
- [ ] **Step 2: Run** the smoke script on a fresh DB (CLAUDE.md) → the new checks FAIL.
- [ ] **Step 3: Implement.** `grep -rn "ME\.port\b\|seesAll\|ME\.role\|IS_ACCOUNTING" sheet/static/sheet/js` → nothing.
- [ ] **Step 4: Run** `cd tools && npm run check` and the smoke script for alex / admin / viewer / suez → all pass.
- [ ] **Step 5: Commit** `feat(ui): several ports per user, ports page`.

### Task 7: Docs

`DEPLOYMENT.md` (8.1 Admins = superusers; 8.2 roles table → Admin / User with ports; 8.3 the Accounts page with home
and extra ports; a Ports section; migrations 0023 / 0024 notes: Read-only accounts are turned off, non-superuser
staff lose staff, admin-role non-superusers become Users with every port), `CLAUDE.md` (the roles sentence, Accounts
paragraph, a Ports paragraph, `access.ports_of` / `require_port`, `ports.py` labels, smoke roles: viewer = three-port
User), `STATUS.md` (where things stand, table row, decisions, Next = piece 2), `README.md` / `SECURITY.md` (roles, A01,
test counts).

- [ ] **Step 1:** Edit. **Step 2: Run** `cd tools && npm run check` → "All checks passed." **Step 3: Commit** `docs: ports and people`.
