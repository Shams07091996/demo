# Two-step login (Microsoft Authenticator)

Date: 2026-11-17, updated 2026-11-18 for the new look, agents and dashboards · Size: project · Status: draft for approval

## Why
The user is selling the app to their company and security comes first. This is piece 3 of 3 of the security push
(1 = safe page building, 2 = OWASP 2025, both done). With only a password, anyone who learns a password gets straight
in. That includes a read-only password, which shows all the money for every port. The company uses Microsoft 365,
but the user can't get access to Entra ID, so "Sign in with Microsoft" is out. Codes from an authenticator app
(TOTP, the standard six-digit codes) need nothing from the company's IT.

## Goals (user decisions)
- **Everyone** signs in with password + a six-digit code from **Microsoft Authenticator**. Any TOTP app works, since
  the codes are standard, but Authenticator is the one the company will use.
- **Exceptions:** the superuser can mark a person as an exception, and they sign in with their password only.
  **Admin accounts can never be exceptions** (app role `admin`, and Django superusers). Granting or removing an
  exception is recorded in the change history.
- **Remember this computer for 30 days:** after a correct code, that browser is not asked for a code for 30 days,
  for that one user.
- **No backup codes.** A lost phone means the superuser resets that person's two-step setup.
- **The Django admin pages** (`/admin/`) are behind the same two-step login, with no way around it.
- **Every login is one person** (user's answer): one person, one phone, one Authenticator setup per login. No shared
  logins; if a team needs access, each person gets their own login.
- **Every user sets up their own Authenticator** (user's answer), under the setup guards below.
- **Several superusers:** the user will create 2–3 more superusers, so superusers can reset each other's two-step
  setup. The server command stays as the last resort.

## Proposals the user accepted in conversation (my proposals, not their words)
- **Forced password change:** when a password is set by someone else (the superuser in the admin pages, including
  for a new account), that person must choose their own at their next sign-in before doing anything else.
- **Lost phone:** a superuser resets that person's two-step setup in the admin pages; they scan a new QR code at
  their next sign-in. A superuser's own phone is reset by another superuser, or as a last resort by the server
  command `manage.py reset_two_step <username>`.
- **Setup guards (from the builder check; my proposal, the user answered "every user" sets up their own):**
  - **New password first:** a person whose password was set by someone else changes it *before* the setup screen,
    so only they know the password when the QR code appears.
  - **72-hour setup window:** setup is only possible within 72 hours after a superuser creates the account or resets
    its two-step setup (and, for accounts that exist when this is installed, within 72 hours of the update). After
    that, signing in shows "Ask an administrator to reset your two-step login" and needs a new reset. A password
    stolen later can't be used to set up a new phone.
- **Remember-this-computer rules:** the 30 days end early when the password changes, when the two-step setup is reset,
  or when the person clicks **Forget this computer**. The mark is bound to one browser and one user and can't be
  reused by anyone else.

## Non-goals
Backup codes; SMS or e-mail codes; Microsoft Entra ID / SSO; passkeys / security keys (WebAuthn); a self-service
"forgot password"; a user-management page inside the sheet (users stay in the Django admin pages). **The online
demo** (PythonAnywhere): nothing special is planned for it (user's answer 2026-11-18: "no need for the demo right
now"); updating it stays out of scope until the user asks.

## Anti-goals
- A way around the code: any page, API call or admin page usable after the password alone by someone who isn't an
  exception.
- Locking the superuser out with no way back in.
- The TOTP secret (the shared key behind the codes) appearing in the change history, logs, API answers or anywhere
  after setup, except the one setup screen.
- Breaking the page-safety rules (no inline scripts or styles, no HTML strings; CSP unchanged except where stated).

## Constraints
- Django 5.2, existing login at `/login/` (`auth_views.LoginView`, `sheet/login.html`), login lock-out
  (`throttle.py`, `LoginThrottleMiddleware`, also on `/admin/login/`), 60-minute idle sessions, `__Host-` cookies in
  production, CSP `img-src 'self' data:`.
- New Python packages go into `requirements.in` and the hash-locked `requirements.txt`; `pip-audit` must stay clean.
- Change history (`history.py`) records every tracked model. Profile is tracked; the new device model must be
  tracked **without its secret**.
- Tests first; `npm run check` green; the smoke test keeps working for alex / admin / viewer / suez.

## Approaches
| | What | Trade-off |
|---|---|---|
| **A. `django-otp` for the codes + `segno` for the QR, our own screens (chosen by the user)** | `django-otp` (with its TOTP plugin) checks codes, refuses reuse and slows guessing; `segno` (pure Python, no dependencies) draws the QR; screens and remember-this-computer are ours | Well-tested crypto, our look and safety rules; two new dependencies |
| B. `django-two-factor-auth` | Every flow ready-made | More dependencies and features the user said no to (backup codes, phone); screens need restyling and CSP checking; remember-device still extra work |
| C. Write TOTP ourselves | No code library | Home-made security code; a QR library still needed |

## How it works

### Sign-in
1. **Password** at `/login/`, as today (lock-out unchanged). After a correct password the person is signed in to
   Django but **not yet verified** (django-otp's model: `request.user.is_verified()`).
2. Then one of:
   - **Exception** (and not an admin): verified straight away.
   - **A valid remember-this-computer mark** for this user: verified straight away.
   - **Has a confirmed Authenticator setup:** the **Enter code** screen.
   - **Password set by someone else:** first `/password/` (forced password change), nothing else until it's changed.
   - **No setup yet, inside the 72-hour window:** the **Set up Authenticator** screen.
   - **No setup yet, window over:** a "Ask an administrator to reset your two-step login" screen; only Log out works.
3. Order when several apply: code (if a setup exists) → new password → setup. A remembered computer or an exception
   still never skips the forced password change.
4. Until verified (and, where needed, the password is changed), every other page redirects to the right step, and
   every `/api/` call answers **401** `{"error": "Please log in again."}` (the front end already sends people to
   `/login/` on 401), and `/admin/` pages redirect to the code step. Logging out always works.

### Screens (plain server pages like `login.html`, same look, no scripts)
- **Set up Authenticator:** short steps ("Open Microsoft Authenticator → + → Other account → scan"), the QR code as an
  `<img>` with an SVG `data:` URL drawn by `segno`, the secret as text for typing in by hand, and a code box to
  confirm. The setup is only active once a correct code is entered.
- **Enter code:** a six-digit box, a **Remember this computer for 30 days** tick box (ticked by default), Sign in.
- **Forget this computer:** a sidebar item next to Change password, for signed-in users with a remembered mark.

### The codes
Standard TOTP as Authenticator expects: 6 digits, 30-second steps, SHA-1, one step of tolerance either side for clock
drift. A code can't be used twice. Wrong codes are slowed down by django-otp's built-in throttling, logged to
`sheet.security`, and count towards the `login_lockout` alert kind (a burst of wrong codes is someone with a stolen
password).

### Remember this computer (my call after the builder check: kept on the server too)
Each remembered computer is a **row on the server** (user, a long random token stored only as its hash, created,
expires after 30 days, last used, address, browser name) plus an HttpOnly, Secure, SameSite=Lax cookie holding the
token (`__Host-` prefixed in production like the other cookies). It's checked at sign-in only, so it never skips the
password. It stops working when it expires, when the password changes, or when the two-step setup is reset (all
that person's remembered computers are removed). **Forget this computer** deletes the row and the cookie. Superusers
see each person's remembered computers in the admin pages and can remove any of them (a stolen laptop). Remembered
computers are recorded in the change history without the token. Admin accounts may use it too (the user chose
30-day remembering for everyone).

### Exceptions
A new Profile field (`two_step_exempt`, default off), set by the superuser on the user's page in the admin pages.
An exception never applies to role `admin` or a superuser: the model refuses it, and the sign-in check ignores it
anyway. It's recorded by the change history like any Profile change, and each exempt sign-in is logged.

### Forced password change
A new Profile field (`must_change_password`), switched on when the admin pages set someone's password (the
password-reset form and adding a user) and switched off when that person changes their own on `/password/`.

### Reset and lock-out safety
- **Reset (superusers only):** a reset action on the user in the admin pages deletes their Authenticator device and
  remembered computers and opens a new 72-hour setup window. Their next sign-in starts at setup.
- Superusers reset each other; the user plans 3–4 superusers in all.
- **`manage.py reset_two_step <username>`** does the same from the server, the last resort.
- A `check --deploy` warning when fewer than two active superusers have a confirmed Authenticator (my call: so the
  company never runs with a single key holder).
- Everything is recorded in the history (device / remembered computers deleted, with who did it, or "system" for the
  command).

### History and logs
The device model is added to the change history with its secret (`key`) and the counters left out, so the history
shows "Authenticator set up / reset" for whom and by whom, never the secret. Security log lines: code ok / wrong,
setup done, exempt sign-in, remembered-computer sign-in, reset.

## Testing
Backend tests, each written to fail first: every page and `/api/` call blocked until verified; admin pages blocked;
setup → confirm → verified; wrong / reused codes refused; exceptions work but never for admins or superusers;
remember-this-computer accepted for 30 days, rejected for another user, after a password change, after a reset and
after Forget; setup refused outside the 72-hour window and before the forced password change; forced password change; the reset command; the secret never appears in history, logs or responses. The smoke test
signs in with a code (see below); `npm run check` green.

## Updated 2026-11-18 for the current code (my calls, shown to the user)
- **Look:** the new screens use the sign-in card of `login.html` (light and dark tokens in `app.css`, no new
  colours). One new line icon, `phone`, is drawn in `icons.svg` and added to `ICONS` in `dom.js` (`tests_look` keeps
  them equal). **Forget this computer** is a sidebar item under Change password (icon `x`), a small POST form like
  Log out.
- **QR code:** always dark modules on a white square with a quiet zone, in light and dark mode (phones read inverted
  QR codes badly). It is drawn by `segno` as SVG and put in an `<img src="data:image/svg+xml;base64,…">`; the CSP
  already allows `img-src 'self' data:`.
- **One central gate:** a middleware decides for every request, so the Agents and Dashboards pages
  (`/api/dashboard/`, `/api/dashboard/jobs/`), the CSV export, the History page and any page added later are
  covered without listing them.

## How it is built (my calls as the builder, after reading the code)
- **Packages:** `django-otp` (1.7.x, its `otp_totp` plugin only) for the device, code check, reuse refusal and
  throttling; `segno` (1.6.x) for the QR. Both go into `requirements.in` and the hash-locked `requirements.txt`.
  django-otp's own admin page for TOTP devices is **unregistered** (it shows the secret and a QR); ours is read-only
  and shows user, name, confirmed and created, never the key.
- **Verified state is ours:** a session value says how this session passed the second step (`code`, `remembered` or
  `exempt`). It is cleared on every password sign-in (`user_logged_in`), and the session key is cycled when it is
  set. django-otp is used for the device only, not for its `is_verified` / `OTPAdminSite` (our gate covers the admin).
- **URLs:** `/login/code/` (enter code), `/login/setup/` (QR + confirm), `/login/blocked/` (window over: "Ask an
  administrator to reset your two-step login" + Log out), `/login/forget/` (POST, Forget this computer).
  `/password/` stays the forced-password-change page.
- **The gate (`TwoStepMiddleware`, after authentication):** for a signed-in user not yet through the step (or with a
  forced password change pending), only the step pages, `/password/`, `/logout/`, the admin logout and static files
  answer; `/api/…` gets 401 `{"error": "Please log in again."}`, `/export.csv` 401, everything else (admin pages
  included, wherever `DJANGO_ADMIN_URL` puts them) is redirected to the right step.
- **Profile fields:** `two_step_exempt` (refused for role admin and for superusers, in `clean()` and `save()`),
  `must_change_password`, `setup_until` (end of the 72-hour window). The migration sets `setup_until` to 72 hours
  after it runs for every existing profile; a new profile gets 72 hours from creation.
- **Forced password change, how it is switched on:** when a password changes and the person making the change (the
  request's user) is someone else, `must_change_password` is switched on; when they change their own, it is switched
  off. Changes with no request (`createsuperuser`, `changepassword`, `seed_demo`) don't switch it on: whoever runs
  them is at the server and typed the password themselves.
- **Setup:** the first visit to `/login/setup/` creates an unconfirmed device with a fresh secret; reloading shows
  the same one until a correct code confirms it, or a reset removes it.
- **Wrong codes:** django-otp's throttle (growing wait after each wrong code), plus each wrong code counts in the
  existing lock-out (`throttle.record_failure`), so 5 wrong codes lock that person from that address for 15 minutes
  and feed the `login_lockout` alert like wrong passwords do.
- **Remember this computer:** a `RememberedComputer` row (user, SHA-256 of a 32-byte random token, created, expires,
  last used, address, browser name cut to 200 characters) and a cookie `remember` (`__Host-remember` in production;
  HttpOnly, Secure in production, SameSite=Lax, 30 days). One cookie per browser: the last person who ticked the box
  on that browser is the one remembered. The rows are removed when the password changes or the setup is reset.
- **Reset:** an admin action "Reset two-step login" on the Users list, for superusers only; `manage.py
  reset_two_step <username>` does the same. Both: delete the device(s) and remembered computers, set `setup_until`
  to 72 hours from now.
- **Deploy check:** `sheet.W002` (a warning) in `check --deploy` when fewer than two active superusers have a
  confirmed Authenticator; it is skipped quietly when the database can't be reached.
- **History:** TOTP devices and remembered computers are tracked, leaving out the key, the token hash, and the
  fields that change on every sign-in (throttle counters, last used, drift), so a wrong code never writes history.
- **Admin pages, who may change two-step settings (after the builder check):** only superusers. For staff who
  aren't superusers, the exception, forced-password and setup-window fields are read-only and the reset action is
  not offered. "Admin accounts can never be exceptions" covers role `admin`, superusers and any staff account (anyone
  who can open the admin pages).
- **Removing an exception** opens a fresh 72-hour setup window, like a reset (a superuser's deliberate act, recorded
  in the history as the Profile change), so that person isn't stuck on the "ask an administrator" screen.
- **Making an exception an admin / superuser / staff:** refused with "Remove the two-step exception first." (model
  and admin form), never cleared silently, so nobody becomes an admin without a code.
- **A superuser may reset their own two-step login** (they are already signed in with a code; their next sign-in
  starts at setup within the new window).
- **Smoke test and `seed_demo`:** `seed_demo --two-step-key <base32>` gives the demo users a confirmed device with
  that key; the smoke test computes the code itself (Node `crypto` HMAC) and signs in through `/login/code/`, so the
  real path is exercised. Without the option the demo users set up their own, like real users.

## Left to the builder
- How the smoke test and `seed_demo` sign in: for example, `seed_demo` gives the demo users a confirmed device with a
  known key passed as an option, and the smoke test works out the code itself (Node's `crypto` HMAC), so the real
  two-step path is exercised.
- Whether the code step is a separate URL (`/login/code/`, `/login/setup/`) or one view; the middleware layout; file
  names.
- Exact wording on the screens (lean, in the app's style: no help paragraphs beyond the setup steps).
- django-otp's throttle settings and how wrong codes feed `alerts`.
