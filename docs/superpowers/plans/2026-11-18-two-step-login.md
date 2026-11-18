# Two-step login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every sign-in needs password + a six-digit Authenticator code (TOTP), with exceptions for non-admins,
30-day remembered computers, forced password change, 72-hour setup windows and superuser resets.

**Architecture:** `django-otp` (`otp_totp`) holds the device and checks codes; `segno` draws the QR. Our own
`sheet/twostep.py` keeps the session state, the remembered computers and the rules; `TwoStepMiddleware` is the one
gate for every request; plain server pages (`sheet/views_twostep.py`, templates in the login-card look) do the steps.

**Tech Stack:** Django 5.2, django-otp 1.7.5, segno 1.6.6, jsdom smoke test (Node `crypto` for codes).

**Spec:** `docs/superpowers/specs/2026-11-17-two-step-login-design.md`

## Global Constraints

- Codes: 6 digits, 30-second steps, SHA-1, tolerance 1 step; a code is never accepted twice.
- Remembered computer: 30 days; cookie `remember` (`__Host-remember` when not DEBUG), HttpOnly, SameSite=Lax,
  Secure when not DEBUG; only the SHA-256 of the token is stored.
- Setup window: 72 hours (`SETUP_WINDOW = timedelta(hours=72)`).
- No inline scripts / styles, no `innerHTML`; CSP unchanged. QR as `<img src="data:image/svg+xml;base64,…">`.
- The TOTP key never in history, logs, API answers or admin pages; only on the setup screen before confirmation.
- Unverified `/api/…` → 401 `{"error": "Please log in again."}`.
- New packages in `requirements.in`, re-locked with hashes; `npm run check` green; LF line endings.
- Lean screens: no help paragraphs beyond the setup steps.

## Review Focus

1. Same code sent twice at once (double click / two tabs): only one succeeds → `select_for_update` on the device
   (Task 3 test `test_code_cannot_be_used_twice`).
2. A remembered-computer cookie copied to another user's sign-in is refused (Task 3
   `test_remembered_cookie_of_other_user_is_ignored`).
3. Signing in through `/admin/login/` with only the password gives no admin page (Task 2
   `test_admin_pages_redirect_until_verified`).
4. Password changed by another person (admin page) forces a change; own change clears it (Task 4).
5. A staff (non-superuser) admin user cannot edit two-step fields or reset (Task 5).

---

### Task 1: Packages, settings, models, migration, history

**Files:** `requirements.in`, `requirements.txt`, `config/settings.py`, `sheet/models.py`,
`sheet/migrations/0012_two_step_login.py`, `sheet/history.py`, test `sheet/tests_twostep.py`.

**Produces:**
- `Profile.two_step_exempt: bool`, `Profile.must_change_password: bool`, `Profile.setup_until: datetime|None`
  (default `now + 72h` on create); `Profile.clean()/save()` raise `ValidationError("Remove the two-step exception
  first.")` when exempt and (role admin or user.is_superuser or user.is_staff).
- `RememberedComputer(user FK, token_hash char64 unique, created_at, expires_at, last_used_at null, ip, agent)`.
- History tracks `TOTPDevice` and `RememberedComputer`; per-model hidden fields
  `HIDDEN_FIELDS = {TOTPDevice: {key, drift, last_t, throttling_failure_count, throttling_failure_timestamp,
  last_used_at}, RememberedComputer: {token_hash, last_used_at}}`; an update that only touches hidden fields writes
  no record.
- Settings: `django_otp`, `django_otp.plugins.otp_totp` before `sheet`; `OTP_TOTP_ISSUER = "Marine Service Sheet"`.

- [ ] Tests (fail first): `test_exempt_refused_for_admin_superuser_staff`, `test_new_profile_gets_setup_window`,
  `test_device_history_has_no_key`, `test_wrong_code_writes_no_history`, `test_remembered_history_has_no_hash`.
- [ ] Implement; migration 0012 (fields + model; data step: `setup_until = now + 72h` for existing profiles).
- [ ] `pip-compile --generate-hashes --strip-extras requirements.in -o requirements.txt`; supply-chain tests pass.
- [ ] Commit.

### Task 2: Gate and sign-in state

**Files:** `sheet/twostep.py`, `sheet/middleware.py` (`TwoStepMiddleware`), `config/settings.py`,
`sheet/signals.py`, `sheet/tests.py` (`ApiTestCase.login` passes the step), tests in `sheet/tests_twostep.py`.

**Produces (`sheet/twostep.py`):**
- `SESSION_KEY = "two_step"`; `mark_passed(request, how: str)` ("code" | "remembered" | "exempt"; cycles the
  session key); `has_passed(request) -> bool`.
- `next_step(request) -> str | None`: URL name of the step the user must do, or None; order: not passed → (exempt
  → mark "exempt"; valid remembered cookie → mark "remembered"; confirmed device → `two_step_code`); then
  `must_change_password` → `password_change`; not passed and no device → `two_step_setup` if
  `now < setup_until` else `two_step_blocked`.
- `user_logged_in` receiver pops `SESSION_KEY`.
- Middleware allows while a step is due: the step URLs, `password_change` (only when that is the step, or after the
  code), `logout`, admin logout, static. `/api/` and `/export.csv` → 401 JSON; others → redirect to the step.

- [ ] Tests: `test_api_is_401_until_code`, `test_index_redirects_to_code`, `test_export_401_until_code`,
  `test_admin_pages_redirect_until_verified`, `test_logout_always_works`, `test_password_sign_in_clears_pass`,
  `test_exempt_user_goes_straight_in`, `test_exempt_flag_ignored_for_superuser` (set via update(), bypassing save).
- [ ] `ApiTestCase.login` and the other `client.login` calls go through a helper `pass_two_step(client)` that sets the
  session value (tests only); full suite green.
- [ ] Commit.

### Task 3: Code, setup, blocked and forget screens; remembered computers

**Files:** `sheet/views_twostep.py`, `sheet/urls.py`, templates `two_step_code.html`, `two_step_setup.html`,
`two_step_blocked.html`, `sheet/templates/sheet/index.html` (Forget this computer), `icons.svg` + `dom.js` ICONS
(`phone`), `app.css` (QR box, only tokens), tests in `sheet/tests_twostep.py`.

**Produces:** `twostep.check_code(user, code) -> bool` (atomic, `select_for_update`, wrong → `throttle.record_failure`
+ `security_log`), `twostep.remember(response, request)`, `twostep.remembered_user_ok(request) -> bool`,
`twostep.forget(request, response)`, `twostep.qr_data_url(device) -> str`. URLs `/login/code/` (`two_step_code`),
`/login/setup/` (`two_step_setup`), `/login/blocked/` (`two_step_blocked`), `/login/forget/` (`two_step_forget`,
POST only). Code POST also refused while `throttle.is_blocked(ip, username)` (locked page, 429).

- [ ] Tests: `test_right_code_passes`, `test_wrong_code_refused_and_counted`, `test_code_cannot_be_used_twice`,
  `test_five_wrong_codes_lock`, `test_remember_skips_code_for_30_days`, `test_remember_expires`,
  `test_remembered_cookie_of_other_user_is_ignored`, `test_forget_removes_row_and_cookie`,
  `test_setup_shows_qr_and_confirms`, `test_setup_same_secret_on_reload`, `test_setup_refused_after_window`,
  `test_setup_refused_while_device_confirmed`, `test_secret_not_in_logs_or_history`, `test_screens_csp_safe`.
- [ ] Commit.

### Task 4: Forced password change and password side effects

**Files:** `sheet/twostep.py` (signal on User password change), `sheet/history.py` hook or `sheet/signals.py`,
`password_change.html` (no Cancel while forced), tests.

- [ ] Tests: `test_password_set_by_other_forces_change`, `test_own_change_clears_flag`,
  `test_forced_change_blocks_everything_else`, `test_remembered_removed_on_password_change`,
  `test_command_password_does_not_force` (createsuperuser / set_password without request),
  `test_code_before_forced_change` (device exists: code first, then password page).
- [ ] Commit.

### Task 5: Admin pages, reset, command, deploy check

**Files:** `sheet/admin.py`, `sheet/management/commands/reset_two_step.py`, `sheet/checks.py`, tests.

**Produces:** `twostep.reset(user)` (delete devices + remembered rows, `setup_until = now + 72h`); admin action
`reset_two_step` (superusers only); TOTPDevice admin replaced by read-only `user, name, confirmed, created_at`;
RememberedComputer admin (list + delete; no add / change); Profile two-step fields read-only for non-superusers;
User form refuses making an exempt person staff / superuser; removing the exception opens a new window; deploy
warning `sheet.W002`.

- [ ] Tests: `test_reset_action_superuser_only`, `test_reset_command`, `test_device_admin_hides_key`,
  `test_staff_cannot_edit_two_step_fields`, `test_removing_exception_opens_window`,
  `test_make_exempt_superuser_refused`, `test_deploy_warning_fewer_than_two_superusers`.
- [ ] Commit.

### Task 6: seed_demo, smoke test, docs

**Files:** `sheet/management/commands/seed_demo.py` (`--two-step-key`), `tools/ui_smoke_test.js`
(`UI_TEST_TOTP_KEY`, code step, Forget this computer present), `CLAUDE.md`, `README.md`, `SECURITY.md`,
`docs/STATUS.md`.

- [ ] Test `test_seed_demo_two_step_key`; smoke test alex / admin / viewer / suez on a throwaway database.
- [ ] `npm run check` green; docs (test count, MFA gap closed); commit.
