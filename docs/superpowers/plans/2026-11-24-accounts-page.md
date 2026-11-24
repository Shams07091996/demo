# Accounts Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Accounts page, for superusers only, to add a person, change their name / role, and turn them off or on.

**Architecture:** A rules module `sheet/accounts.py` (row dict, create, update, two-step state) fed by a new
`validators.clean_account`; three routes in `views.py` behind `access.require_superuser`; a page module
`js/pages/accounts.js` and a dialog `js/modals/account.js` wired through `actions.js` / `router.js`, rendered in the
template only for superusers. History and must-change-password come from the existing signals.

**Tech Stack:** Django 5.2, django-otp, vanilla ES modules (`dom.js` `h()`), jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-24-accounts-page-design.md`

## Global Constraints

- Only superusers (`request.user.is_superuser`) may call `/api/accounts/…`; everyone else gets 403 (`Forbidden`).
- Superuser and staff accounts are read-only on the page; the page never sets `is_staff` / `is_superuser`.
- Username: 3–30 characters, `^[A-Za-z0-9._-]+$`, unique ignoring case, not editable after creation.
- First / last name: optional, at most 150 characters each, refused (not cut) when longer.
- Role: one of `constants.ROLES` keys; Read-only preselected in the dialog.
- Password: Django's `validate_password(password, user)` (settings: 12+ characters, not common, not all digits, not
  like the username / names); never returned, logged, audited or put in the History.
- Turn off = `is_active=False` + delete that user's `RememberedComputer` rows; nothing else touched.
- Role Admin on a profile with `two_step_exempt` refused with `models.EXEMPT_REFUSED`.
- Every write through `api.json_api` (one transaction, rate limited) and `api.audit(request, "account.create" |
  "account.update", id=…)`.
- No `innerHTML` etc.; screens built with `dom.js`; no placeholders or help text (the user strips them).
- Files LF; `npm run check` green; the smoke test passes for alex / admin / viewer / suez.

## Review Focus

1. **A username differing from an existing one only in capitals or surrounding spaces** (`" Alex "`, `ALEX`) → refused
   as taken; never a second account. (Task 1 test `test_username_unique_ignoring_case_and_spaces`.)
2. **A PUT / POST carrying extra keys** (`is_superuser`, `is_staff`, `password` on PUT, `username` on PUT) → ignored;
   nothing but the whitelisted fields changes. (Task 1 `test_extra_keys_ignored`.)
3. **A turned-off person with a browser already open** → their next API call is 401, the page sends them to sign-in.
   (Task 2 `test_turned_off_session_stops_at_once`.)
4. **A PUT aimed at a superuser's or staff user's id** (including the caller's own) → refused, nothing saved.
   (Task 1 `test_superuser_and_staff_read_only`.)
5. **An old user with no Profile row** → the list shows them (role Admin if superuser, else Read-only) and the GET
   writes nothing; a PUT creates the profile with the chosen role. (Task 1 `test_user_without_profile`.)

---

### Task 1: Account rules (`sheet/accounts.py`, `validators.clean_account`)

**Files:**
- Create: `sheet/accounts.py`
- Modify: `sheet/validators.py` (add `clean_account`)
- Test: `sheet/tests_accounts.py` (class `AccountRulesTests(ApiTestCase)`)

**Interfaces:**
- Produces:
  - `validators.clean_account(data, existing=None) -> dict` with keys among `username`, `first_name`, `last_name`,
    `role`, `password` (create) / `first_name`, `last_name`, `role`, `active` (update; absent keys absent).
  - `accounts.account_to_dict(user, now=None) -> dict` keys `id, username, first_name, last_name, role, superuser,
    staff, active, two_step ("set_up"|"waiting"|"expired"|"exempt"), setup_until, last_login` (times via
    `serializers.local_iso`).
  - `accounts.list_response() -> {"accounts": [...], "roles": [[key, label], ...]}` — on first, then username.
  - `accounts.create_account(payload) -> User`; `accounts.update_account(user, payload) -> User`.
  - Messages: `accounts.TAKEN = "That username is already used."`, `accounts.LOCKED_ACCOUNT = "Superuser and staff
    accounts are changed in the admin pages."`.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_accounts.py`:
  - `test_create_sets_role` — `create_account({"username": "newbie", "first_name": "Nora", "role": "damietta",
    "password": "Long-enough-pass-42"})` → `user.profile.role == "damietta"`, `user.is_active`, not `is_staff`, not
    `is_superuser`, `user.check_password("Long-enough-pass-42")`, `profile.setup_until` set (must-change is checked
    through the API in Task 2).
  - `test_username_rules` — `""`, `"ab"`, 31 chars, `"a b"`, `"ali@x"` each raise `BadRequest`; `"a.b_c-1"` ok.
  - `test_username_unique_ignoring_case_and_spaces` — with `alex` existing, `"ALEX"` and `" alex "` raise
    `BadRequest(TAKEN)`.
  - `test_password_rules` — `"short"`, `"123456789012345"`, `"password1234"`, `"newbie-newbie"` (username
    `newbie`) each raise `BadRequest`; error text is Django's message, not the password.
  - `test_name_too_long_refused` — 151 chars → `BadRequest`.
  - `test_unknown_role_refused` — `"captain"` → `BadRequest`.
  - `test_update_role_names_and_active` — `update_account(alex, {"role": "suez", "first_name": "A"})` → profile
    role suez; `{"active": False}` → `is_active False` and the user's `RememberedComputer` rows deleted; `{"active":
    True}` → on again; absent keys keep values.
  - `test_extra_keys_ignored` — create with `is_superuser: True, is_staff: True` → both False; update with
    `password`, `username`, `is_superuser` → none changed.
  - `test_superuser_and_staff_read_only` — a superuser and a staff user: `update_account` raises
    `BadRequest(LOCKED_ACCOUNT)` and nothing changes.
  - `test_admin_role_refused_when_exempt` — profile `two_step_exempt=True`, update role admin → `BadRequest`
    (`EXEMPT_REFUSED`).
  - `test_two_step_states` — confirmed TOTPDevice → `set_up`; no device, `setup_until` future → `waiting`; past or
    None → `expired`; `two_step_exempt` → `exempt`.
  - `test_list_order_and_roles` — on accounts before off ones, then username; `roles == [list(r) for r in ROLES]`.
  - `test_user_without_profile` — a `User` with no Profile appears with role readonly (superuser: admin) and
    `Profile.objects.count()` unchanged after `list_response()`; `update_account(user, {"role": "suez"})` creates it.

- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_accounts` — Expected: ImportError / FAIL.

- [ ] **Step 3: Implement** `clean_account` (uses `_short`, regex `^[A-Za-z0-9._-]{3,30}$` after strip, role in
  `dict(ROLES)`, `_flag` for `active`) and `accounts.py`. Uniqueness: `User.objects.filter(username__iexact=…)`.
  Password: `django.contrib.auth.password_validation.validate_password(password, User(username=…, first_name=…,
  last_name=…))`, `ValidationError` → `BadRequest(" ".join(e.messages))`. Create: `User.objects.create_user(username,
  password=…, first_name=…, last_name=…)` then `Profile.objects.create(user=user, role=role)` (the signal's
  `on_commit` sets must-change afterwards). Update: refuse if `is_superuser or is_staff`; profile via
  `access.profile_of`; set role through `profile.save()` (its `clean()` raises `ValidationError` for an exempt
  admin → `BadRequest(EXEMPT_REFUSED)`); `active False` also deletes `RememberedComputer.objects.filter(user=user)`
  one by one (`row.delete()`, so History signals fire, as `twostep` does). List: `select_related("profile")`, no
  `profile_of` (no writes on GET); devices in one query (`TOTPDevice.objects.filter(confirmed=True).values_list(
  "user_id")`).

- [ ] **Step 4: Run** the same command — Expected: OK.

- [ ] **Step 5: Commit** `git add sheet/accounts.py sheet/validators.py sheet/tests_accounts.py && git commit -m
  "feat(accounts): account rules"`.

### Task 2: Accounts API

**Files:**
- Modify: `sheet/access.py` (add `require_superuser(request)`), `sheet/views.py` (`accounts_list`,
  `account_detail`), `sheet/urls.py`
- Test: `sheet/tests_accounts.py` (class `AccountApiTests(ApiTestCase)`; a superuser `boss` made in
  `setUpTestData` with `is_superuser=is_staff=True`, role admin)

**Interfaces:**
- Consumes: Task 1's `accounts.*`.
- Produces: `GET/POST /api/accounts/` (name `api_accounts`), `PUT /api/accounts/<int:pk>/` (`api_account`);
  `access.require_superuser(request)` raising `Forbidden("Only a superuser can manage accounts.")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_only_superusers` — `admin`, `viewer`, `alex` get 403 on GET, POST and PUT; `boss` gets 200 on GET.
  - `test_create_via_api` — POST → 201, body has no `password` key; `Profile.must_change_password` True after the
    request (wrap the POST in `self.captureOnCommitCallbacks(execute=True)`, as `tests_twostep` does); a `ChangeRecord` for the new User exists and no record
    holds the password text.
  - `test_update_via_api` — PUT role / names / active → 200 with the new values; PUT on `boss` itself → 400
    `LOCKED_ACCOUNT`; PUT on an unknown id → 404.
  - `test_turned_off_session_stops_at_once` — sign `alex` in (`self.login`), boss PUTs `{"active": false}`, alex's
    next `GET /api/vessels/` → 401.
  - `test_role_change_applies_next_request` — alex reads only Alexandria; boss sets role suez; alex's next
    `GET /api/vessels/` lists only Suez vessels.

- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_accounts.AccountApiTests` — Expected: FAIL
  (404 routes).

- [ ] **Step 3: Implement** the views (`@json_api`, `@require_http_methods`, `require_superuser(request)` first,
  `read_json`, `get_object_or_404(User, pk=pk)`, `audit(request, "account.create"/"account.update", id=…)`, JSON from
  `account_to_dict`) and the two URLs.

- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet.tests_accounts` — Expected: OK.

- [ ] **Step 5: Commit** `git commit -m "feat(accounts): accounts API"` (with the three files and the test).

### Task 3: Accounts page and dialog

**Files:**
- Create: `sheet/static/sheet/js/pages/accounts.js`, `sheet/static/sheet/js/modals/account.js`
- Modify: `sheet/views.py` (`me.isSuperuser`), `sheet/static/sheet/js/config.js` (if `ME` fields are listed),
  `sheet/templates/sheet/index.html` (nav item after History `{% if me.isSuperuser %}`, icon `i-key`; `<main
  id="page-accounts" hidden>` with toolbar button `data-act="account-new"` "+ Add account", `#ac-head`,
  `#ac-tbody`, `#ac-empty`), `js/actions.js` (`account-new`, `account-open`, `account-save`, `account-toggle`),
  `js/router.js` (`accounts: 'Accounts'`, load), `app.css` only if a turned-off row needs the existing `.inactive`
  look (reuse it), `tools/ui_smoke_test.js`, `sheet/tests_look.py` only if it counts nav items.
- Test: `tools/ui_smoke_test.js`; a template test in `sheet/tests_accounts.py`.

**Interfaces:**
- Consumes: Task 2's routes and JSON.
- Produces: `accountsPage.load()`, `accountsPage.open(id)`, `openAccountDialog(account, roles, onDone)`,
  `saveAccountDialog()`, `toggleAccount()`.

- [ ] **Step 1: Write the failing tests:**
  - `sheet/tests_accounts.py` `test_nav_only_for_superusers` — `GET /` as `boss` contains `data-page="accounts"`;
    as `admin`, `alex`, `viewer` it does not, nor `id="page-accounts"`.
  - Smoke (`tools/ui_smoke_test.js`, admin run — seed_demo's `admin` is a superuser): the Accounts page lists `alex`;
    "+ Add account" with a unique username (`smoke` + `Date.now()` base36), role Damietta, a 16+ char password →
    the row appears with role Damietta and two-step "Waiting"; open it, set role Suez → row shows Suez; Turn off →
    row greyed / Off; Turn on → On. alex / viewer runs: no Accounts nav item and `GET /api/accounts/` → 403. Update
    the nav-count line (admin 14, others 12) and `pageOrder`.

- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_accounts` — Expected: FAIL on the nav test.

- [ ] **Step 3: Implement.** Columns: Username, Name, Role (`Admin · Superuser` / `· Staff`), Two-step (`Set up` /
  `Waiting — until <fmtStamp>` / `Setup expired` / `Exception`), Last sign-in (`fmtStamp` or `—`), State (On / Off;
  row class `inactive` when off). Dialog: new → Username, First name, Last name, Role (select from `roles`, default
  `readonly`), Temporary password (`type=password`, `autocomplete=new-password`, with a Show tick); existing →
  username as text, names, role, Turn off / Turn on button (`data-act="account-toggle"`), no password; superuser /
  staff → the fields disabled, no Save / toggle, one line "Changed in the admin pages." Errors via `mutate` (shows
  the server's message). Saving / toggling reloads the list. If `dom.js` refuses an attribute you need, add it to its
  allow-list (and keep `tests_frontend_safety` green).

- [ ] **Step 4: Run** the backend test, `cd tools && npm run test:parsing`, and the smoke script for alex / admin /
  viewer / suez on a fresh scratch DB (see CLAUDE.md) — Expected: all pass.

- [ ] **Step 5: Commit** `git commit -m "feat(ui): accounts page"`.

### Task 4: Docs

**Files:** `docs/DEPLOYMENT.md` (8.3: accounts are made on the **Accounts** page by a superuser; 8.5 rows: Someone
leaves → Turn off on the Accounts page; Change what someone may do → Accounts page; resets / exception stay in the
admin pages), `CLAUDE.md` (an **Accounts** paragraph: `accounts.py`, routes, `require_superuser`, the read-only rule
for superuser / staff, no writes on GET, History via signals), `docs/STATUS.md` (where things stand, table row,
decisions: superusers only (A), turn off not delete, username fixed, last save wins, access rework next), README /
SECURITY test counts and SECURITY's who-manages-accounts line.

- [ ] **Step 1:** Edit the docs.
- [ ] **Step 2: Run** `cd tools && npm run check` — Expected: "All checks passed."
- [ ] **Step 3: Commit** `git commit -m "docs: accounts page"`.
