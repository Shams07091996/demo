# Permissions and pages (access rework, piece 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every User gets 16 switchable permissions and a set of pages, filled in from templates on the Accounts
page; the server refuses (403) anything not ticked, and the screens hide it.

**Architecture:** Two JSON lists on `Profile` (`permissions`, `pages`), checked against fixed lists in
`constants.py` by `Profile.can()` / `Profile.sees()`; `access.require()` / `access.require_page()` replace
`require_edit` in every view. Templates are constants sent to the Accounts dialog, which only fill in the ticks.
`ME.permissions` / `ME.pages` drive the front end (`config.can()` / `config.sees()`).

**Tech stack:** Django 5.2, vanilla ES modules (no build), jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-24-access-rework-design.md`, section "Piece 2" (approved). Money hiding
(what `money.view` / `money.edit` strip from answers) is piece 3 and **not** in this plan; here `money.view` only
gates the Calculations / Exchange rates / History pages and `money.edit` only gates customers' agreed rates.

## Global constraints

- Branch `feature/permissions-and-pages`; `cd tools && npm run check` green before asking to merge.
- Admins (`user.is_superuser`) have every permission and every page, whatever is stored.
- Without a permission: 403 `"You don't have permission: <label>."`; without a page: 403
  `"You don't have access to <page name>."` (one `Forbidden` each, logged by `json_api` as today).
- Input refused, never silently fixed (CLAUDE.md), except the two derived pages below.
- Screens built with `dom.js` only; no help text, placeholders or stat cards (user's rule).
- Never touch `db.sqlite3`, `.env.example` or `marine_sheet.zip`; smoke tests on a scratch database.
- LF line endings.

## Decisions taken in this plan (builder's calls, from "Left to the builder")

- **Vessels** is always in a User's stored `pages` (added by the cleaner). **History** is never ticked on its own:
  the cleaner stores it exactly when `history.view` is ticked (whatever `pages` says about it). The dialog shows the
  History page tick disabled, mirroring `history.view`.
- Dependencies are **refused** when saving (`Calculations` / `Exchange rates` page without `money.view`;
  `history.view` without `money.view`; `accounting.close` without the Calculations page) **and** re-applied when
  checking (`can` / `sees`), so a stored list can never give more than its dependencies allow.
- Deleting ships and customers stays Admin-only. Moving Master-data values (PATCH), exchange-rate and garbage-price
  writes, Ports and Accounts stay Admin-only.
- Page sections stay in `index.html` (they are empty shells); the nav item is left out and the router lands on
  Vessels. The server refuses the page's routes.
- `PortClosure` records start carrying their port in the History (`history.port_of`), so closure changes reach a
  User's History from now on (older ones have no port and stay Admin-only).
- Model default for both lists is `[]` (least privilege); migration 0025 gives every existing Profile all 16
  permissions and all pages; `tests.make_user` gives all unless told otherwise.

## Route → check map (Task 2 / 3 implement exactly this)

| Route | Check |
|---|---|
| `POST /api/vessels/`, `PUT/PATCH /api/vessels/<id>/` | `vessels.edit` |
| `DELETE /api/vessels/<id>/` | `vessels.delete` |
| `POST /api/vessels/<id>/services/`, `PUT/PATCH/DELETE /api/services/<id>/` | `services.edit` + status rule |
| service PUT with non-empty `cancel_bookings` | also `bookings.edit` |
| `GET /api/services/<id>/bookings/` | `services.cancel` |
| `GET /api/services/` | page `services` |
| LOG letter, receipt GET / POST | `documents` |
| `POST /api/options/`, `DELETE /api/options/<id>/` | `master.edit` (PATCH stays `require_admin`) |
| `POST /api/ships/`, `PUT /api/ships/<id>/` | `customers.edit` (DELETE stays Admin) |
| `POST /api/customers/`, `PUT /api/customers/<id>/` | `customers.edit`; rates that differ from stored also `money.edit` (DELETE stays Admin) |
| `/api/closures/…` any method | page `closures`; writes also `closures.edit` |
| `/api/hotels/…` / `/api/transfers/…` any method | page `hotels` / `transport`; writes also `bookings.edit` |
| `GET /api/vessels/<id>/crew/` | page `hotels` or `transport` |
| `GET /api/disposal/`, `PUT /api/disposal/<id>/` | page `disposal`; PUT also `disposal.edit` |
| `GET /api/rates/`, `GET /api/disposal-prices/` | page `rates` (writes stay Admin) |
| `GET /api/calculations/` | page `calculations` |
| `POST /api/accounting/` | `accounting.close` (replaces `require_accounting`) |
| `GET /api/dashboard/`, `/api/dashboard/jobs/` | page `dashboard` |
| `GET /api/dashboard/export/` | page `dashboard` + `exports`; sheets `closures` / `disposal` only with those pages |
| `GET /api/export/<page>/` | that page (`transfers` → `transport`) + `exports` |
| `GET /api/export/all/` | page `dashboard` + `exports`; only the sheets of pages the person has; none → 403 |
| `GET /export.csv` | `exports` (403 plain text like its other errors) |
| `GET /api/history/` | `history.view` (Admins: everything; Users: see Task 4) |
| alerts `missing` | `Hotel: …` lines only with page `hotels`, `Transport: …` only with `transport` |

## Review focus

1. A User with `services.edit` but not `services.cancel` editing an already-Cancelled service without changing its
   status: allowed. → `test_unchanged_cancelled_status_needs_only_services_edit` (Task 2).
2. Creating a service already Completed without `services.complete`: refused. →
   `test_create_completed_needs_services_complete` (Task 2).
3. A User's History must never show Profile / User / device records, although Profile records carry the home port.
   → `test_user_history_hides_people_records` (Task 4).
4. Turn off / Turn on on the Accounts page sends only `{active}`: permissions and pages must stay. →
   `test_update_without_lists_keeps_them` (Task 5).
5. A stored list edited by hand (admin pages / old data) with `accounting.close` but no Calculations page, or the
   Calculations page without `money.view`: still refused. → `test_dependencies_apply_when_checking` (Task 1).

---

### Task 1: Permission lists, Profile fields, checks

**Files:**
- Modify: `sheet/constants.py`, `sheet/models.py` (Profile), `sheet/access.py`, `sheet/tests.py` (`make_user`)
- Create: `sheet/migrations/0025_profile_permissions.py`, `sheet/tests_permissions.py`

**Interfaces:**
- Produces: `constants.PERMISSIONS` (tuple of `(key, label)` in the spec's order), `PERMISSION_KEYS`,
  `constants.PAGES` (`(key, label)`: vessels Vessels, services Services, hotels Hotels, transport Transport, closures
  Port closures, disposal Garbage & Sludge, calculations Calculations, dashboard Dashboard, ships Ships, customers
  Customers, master Master data, rates Exchange rates, history History), `PAGE_KEYS`, `PAGE_NEEDS = {"calculations":
  "money.view", "rates": "money.view"}`, `TEMPLATES` (tuple of `(key, label, permissions tuple, pages tuple)`:
  `marine`, `operations`, `manager`, `accounts` per the spec's table; every template's pages include `vessels`, and
  `history` exactly when `history.view` is in it).
- `Profile.permissions`, `Profile.pages`: `JSONField(default=list, blank=True)`.
- `Profile.can(key) -> bool`, `Profile.sees(page) -> bool` (rules in "Decisions").
- `access.require(profile, key)`, `access.require_page(profile, page)`; `require_edit` / `Profile.can_edit` /
  `require_accounting` are deleted at the end of Task 2 once nothing uses them.
- `tests.make_user(username, ports, permissions=None, pages=None)`: None = all keys.

- [ ] **Step 1: Failing tests** in `tests_permissions.py`, class `PermissionModelTests(TestCase)`:
  - `test_admin_has_everything` — superuser with empty lists: `can` every key, `sees` every page.
  - `test_user_has_only_ticked` — `permissions=["vessels.edit"]`, `pages=["vessels","services"]`: `can("vessels.edit")`,
    not `can("vessels.delete")`; `sees("services")`, not `sees("hotels")`; `sees("vessels")` with `pages=[]`.
  - `test_dependencies_apply_when_checking` — `pages=["calculations","rates","history"]`,
    `permissions=["accounting.close","history.view"]` (no `money.view`): none of `sees("calculations")`,
    `sees("rates")`, `sees("history")`, `can("history.view")`, `can("accounting.close")`; adding `money.view` makes
    all five true.
  - `test_unknown_keys_are_false` — `can("nope")`, `sees("nope")` false for a User.
  - `test_templates_are_consistent` — every template's keys are in the fixed lists; `manager` has all 16 and all
    pages; `accounts` permissions == `{"money.view","exports","history.view","accounting.close"}`; operations =
    marine + `services.cancel`, `customers.edit`, `bookings.edit`.
  - `test_migration_gives_existing_profiles_everything` — use `MigrationExecutor`: migrate to 0024, make a Profile,
    migrate to 0025, both lists equal all keys.
- [ ] **Step 2:** `DJANGO_DEBUG=1 python manage.py test sheet.tests_permissions` → fails (no fields).
- [ ] **Step 3:** Implement constants, fields, `can` / `sees`, `require` / `require_page` (messages from Global
  constraints, labels from the fixed lists), migration 0025 (AddField ×2 + RunPython forward filling all keys,
  noop reverse), `make_user` defaults.
- [ ] **Step 4:** `python manage.py test sheet` → all pass (756 + new); `makemigrations --check --dry-run` clean.
- [ ] **Step 5:** Commit `feat(access): permission and page lists on each person`.

### Task 2: Writes need their permission

**Files:**
- Modify: `sheet/views.py`, `sheet/services.py`, `sheet/customers.py`, `sheet/access.py`, `sheet/models.py`
- Test: `sheet/tests_permissions.py` (class `WritePermissionTests(ApiTestCase)`)

**Interfaces:**
- Consumes: `access.require`, `make_user(..., permissions=[...])`.
- Produces: `services.status_permissions(old: str, new: str) -> list[str]` (empty when equal; `services.cancel` if
  either is `cancelled`, `services.complete` if either is `completed`, in that order); create uses
  `old="in_progress"`. `customers.save_customer(payload, existing=None, may_change_rates=True)` raising
  `Forbidden` when the cleaned rates differ from the stored ones (new customer: any rate) and
  `may_change_rates` is False.

- [ ] **Step 1: Failing tests.** One user per test made with all permissions minus the one under test, same port as
  the fixture vessel; each asserts 403 and that nothing changed, then that a user with the permission gets 2xx:
  - `test_vessel_create_and_update_need_vessels_edit`, `test_vessel_delete_needs_vessels_delete`
  - `test_service_writes_need_services_edit` (create, PUT, DELETE)
  - `test_cancel_needs_services_cancel` (to Cancelled and back to In progress), `test_complete_needs_services_complete`
    (to and from), `test_cancelled_to_completed_needs_both`
  - `test_unchanged_cancelled_status_needs_only_services_edit`, `test_create_completed_needs_services_complete`
  - `test_cancel_bookings_needs_bookings_edit`, `test_service_bookings_list_needs_services_cancel`
  - `test_documents_need_documents` (LOG GET, receipt GET and POST)
  - `test_master_values_need_master_edit` (POST, DELETE)
  - `test_ships_need_customers_edit` (POST, PUT), `test_customers_need_customers_edit` (POST, PUT),
    `test_customer_rates_need_money_edit` (changing a rate: 403; same rates, new name: 200), `test_deletes_stay_admin`
    (ship / customer DELETE by a User with every permission: 403)
  - `test_closure_writes_need_closures_edit`, `test_booking_writes_need_bookings_edit` (hotel + transfer, POST / PUT /
    DELETE), `test_disposal_needs_disposal_edit`
  - `test_accounting_needs_accounting_close` (a User with it and the Calculations page closes a line: 200 — the
    switch is given back to Users)
- [ ] **Step 2:** Run → the new tests fail.
- [ ] **Step 3:** Apply the route map's write rows in `views.py`; status rule in `service_create` (`fields["status"]`)
  and `service_detail` (`old_status` vs new, before saving); delete `require_edit`, `Profile.can_edit`,
  `require_accounting` and their imports.
- [ ] **Step 4:** Full backend suite passes (update tests that asserted the old "Only an admin" message for customers
  / accounting).
- [ ] **Step 5:** Commit `feat(access): every write needs its permission`.

### Task 3: Pages, exports and alerts follow the ticks

**Files:**
- Modify: `sheet/views.py`, `sheet/listing.py` (`missing_details`), `sheet/report.py` (`data` / `workbook`),
  `sheet/dataexport.py` (`all_file`)
- Test: `sheet/tests_permissions.py` (class `PageTests(ApiTestCase)`)

**Interfaces:**
- Produces: `dataexport.EXPORT_PAGE = {"hotels": "hotels", "transfers": "transport", "closures": "closures",
  "disposal": "disposal", "calculations": "calculations", "services": "services"}`;
  `dataexport.all_file(profile, date_from, date_to, port)` builds only sheets whose page `profile.sees`;
  `report.data` leaves out `closures` / `disposal` keys unless seen.

- [ ] **Step 1: Failing tests** (user with every permission and every page but the one under test):
  - `test_page_reads_need_the_page` — table over (page, url): services `/api/services/`, hotels `/api/hotels/`,
    transport `/api/transfers/`, closures `/api/closures/`, disposal `/api/disposal/`, calculations
    `/api/calculations/`, dashboard `/api/dashboard/` and `/api/dashboard/jobs/`, rates `/api/rates/` and
    `/api/disposal-prices/` → 403 each; with the page → 200.
  - `test_shared_lists_stay_readable` — user with `pages=["vessels"]`, no permissions: 200 on `/api/vessels/`,
    `/api/vessels/alerts/`, `/api/options/`, `/api/ships/`, `/api/customers/`.
  - `test_crew_picker_needs_a_booking_page`
  - `test_page_export_needs_page_and_exports` (each of the six; and `exports` missing → 403), `test_csv_needs_exports`
  - `test_all_data_leaves_out_pages_not_had` (open the xlsx with `zipfile`, sheet names from `xl/workbook.xml`: no
    "Hotels" without hotels; with no page of the five → 403)
  - `test_management_excel_leaves_out_closures_and_disposal`
  - `test_booking_alert_lines_follow_pages` (sailed vessel with a draft transfer and hotel: `Transport: …` gone
    without transport, `Hotel: …` gone without hotels)
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement the route map's read rows; `missing_details` filters gap labels by
  `profile.sees(...)`.
- [ ] **Step 4:** Full suite passes.
- [ ] **Step 5:** Commit `feat(access): pages, exports and alerts follow each person's ticks`.

### Task 4: History for Users

**Files:**
- Modify: `sheet/views.py` (`history_list`), `sheet/history.py` (`port_of` handles `PortClosure`)
- Test: `sheet/tests_permissions.py` (class `HistoryTests(ApiTestCase)`)

**Interfaces:**
- Produces: `history.PORT_TYPES = ("vessel", "service", "hotelstay", "transfer", "guest", "option", "portclosure")`.
  A User's rows: `object_type in PORT_TYPES`, `port in ports_of(profile)` (so `port=""` never matches).

- [ ] **Step 1: Failing tests:**
  - `test_history_needs_history_view` (403 without; Admin 200 as today)
  - `test_user_history_shows_only_their_ports` (a vessel change in Alexandria seen by alex; a Suez one not)
  - `test_user_history_hides_people_records` (change alex's Profile and an All-ports option, a ship, an exchange rate:
    none in alex's History)
  - `test_closure_changes_carry_their_port`
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Replace `require_admin` with `require(profile, "history.view")`; filter for Users; `port_of` returns
  `instance.port` for `PortClosure`.
- [ ] **Step 4:** Full suite passes.
- [ ] **Step 5:** Commit `feat(history): Users see their ports' history with history.view`.

### Task 5: Accounts API carries ticks and templates

**Files:**
- Modify: `sheet/validators.py` (`clean_account`), `sheet/accounts.py`
- Test: `sheet/tests_accounts.py` (new class `AccountPermissionTests`)

**Interfaces:**
- Produces: `validators._account_ticks(data, existing) -> {"permissions": [...], "pages": [...]}` (fixed order,
  duplicates dropped, unknown → 400 "Unknown permission." / "Unknown page.", not a list of strings → same 400;
  `vessels` added; `history` set from `history.view`; dependency refusals: "Calculations and Exchange rates need
  See money.", "History needs See money.", "Close / reopen lines needs the Calculations page."). New account: absent
  lists = `[]` (+ vessels). Existing: absent keys keep the stored lists.
- `account_to_dict` adds `permissions`, `pages`; `list_response` adds `"permissions": [[key, label]]`,
  `"pages": [[key, label]]`, `"templates": [[key, label, [perms], [pages]]]`.

- [ ] **Step 1: Failing tests:** `test_create_with_ticks`, `test_unknown_keys_refused`, `test_dependencies_refused`
  (each of the three messages), `test_vessels_always_and_history_follows_permission`,
  `test_update_without_lists_keeps_them`, `test_list_has_templates`, `test_tick_changes_are_in_history` (a
  ChangeRecord on the profile with `permissions` old → new).
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement; `update_account` saves the profile when ports **or** ticks changed (one save).
- [ ] **Step 4:** Full suite passes.
- [ ] **Step 5:** Commit `feat(accounts): permissions and pages on the Accounts page API`.

### Task 6: Front end follows the ticks

**Files:**
- Modify: `sheet/views.py` (`index`: `me.permissions`, `me.pages` = effective lists from `can` / `sees`; drop
  `canEdit`), `templates/sheet/index.html` (nav items `{% if "<page>" in me.pages %}`; Excel buttons, `+ Ship`,
  `+ Customer`, `+ Add closure` by permission), `js/config.js` (`can(key)`, `sees(page)`), `js/router.js`
  (unseen page → vessels), every `ME.canEdit` / `ME.isAdmin`-for-editing use listed by
  `grep -rn "canEdit" sheet/static/sheet/js` (vessel → `vessels.edit` / `vessels.delete`, add / open service →
  `services.edit`, LOG and Receipt → `documents`, bookings → `bookings.edit`, closures → `closures.edit`, disposal →
  `disposal.edit`, master → `master.edit`, ships → `customers.edit`, customers → `customers.edit` with rate boxes
  disabled without `money.edit`, accounting switch → `accounting.close`, Excel buttons → `exports`),
  `js/modals/service.js` (a status option is disabled unless it is the current one or
  `services.status_permissions`' JS twin `statusNeeds(old, new)` in `js/util.js` is all held)
- Test: `sheet/tests_permissions.py` (`IndexTests`: a Marine user's page has no `data-page="hotels"` nav item and
  `me-data` lists their keys; Admin's has all), `tools/parsing_test.js` (`statusNeeds` cases matching the Python
  rule)

- [ ] **Step 1:** Failing `IndexTests` and `statusNeeds` tests.
- [ ] **Step 2:** Run backend test and `cd tools && npm run test:parsing` → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Both pass; `grep -rn "canEdit" sheet/` finds nothing.
- [ ] **Step 5:** Commit `feat(ui): screens follow each person's permissions and pages`.

### Task 7: Accounts dialog with template, pages and permissions

**Files:**
- Modify: `js/modals/account.js`, `js/pages/accounts.js` (column "Can": `"8 of 16"`, Admins "All"),
  `templates/sheet/index.html` (column head)

- [ ] **Step 1:** Dialog (not for locked accounts): **Template** select (`Custom` first, then the four; choosing one
  replaces every Page / Can tick with the template's; it is not saved), **Pages** ticks (Vessels on and disabled,
  History disabled and following the `history.view` tick), **Can** ticks (16, labels from the list response);
  dependency ticks disabled while their need is off and unticked when it goes off (Calculations / Exchange rates ←
  `money.view`; `history.view` ← `money.view`; `accounting.close` ← Calculations). Save sends `permissions` and
  `pages`; Turn off / on still sends only `{active}`.
- [ ] **Step 2:** Smoke test `checkAccounts` (Task 8) covers it; `npm run check` lint passes.
- [ ] **Step 3:** Commit `feat(ui): template, pages and permission ticks in the account dialog`.

### Task 8: Demo users, smoke test, docs

**Files:**
- Modify: `sheet/management/commands/seed_demo.py` (new user `marine`, Alexandria, Marine template),
  `tools/ui_smoke_test.js`, `CLAUDE.md`, `docs/STATUS.md`, `docs/DEPLOYMENT.md`, `README.md`, `SECURITY.md`,
  `docs/NEXT-CHAT.md`

- [ ] **Step 1:** Smoke: a short `marine` run (sidebar is exactly Vessels + Services; no Delete vessel button; no
  Excel buttons; `/api/calculations/` 403; service status select has Completed enabled, Cancelled disabled);
  `checkAccounts` (admin) opens an account, picks "Accounts employee", checks the ticks, saves, reopens and sees
  them; replace the old read-only assertions for `viewer` (lines ~516, ~1105, ~1111) with ones that fit a full User.
- [ ] **Step 2:** Run the smoke test for alex, admin, viewer, suez, marine on a fresh scratch database (CLAUDE.md
  recipe, `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) → all pass.
- [ ] **Step 3:** Docs: permissions / pages / templates in CLAUDE.md Architecture (Accounts page, access), STATUS
  (piece 2 built, migration 0025 needed), DEPLOYMENT (creating accounts with a template), README / SECURITY (roles,
  test count).
- [ ] **Step 4:** `cd tools && npm run check` green.
- [ ] **Step 5:** Commit `docs: permissions and pages`; then one fresh review (opus) of the branch; ask the user
  before merging.
