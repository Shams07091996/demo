# Security notes

This document says what the app does, what it does **not** do, and what you must do when deploying.
It maps to the **OWASP Top 10 (2025)** and the main OWASP ASVS themes, assuming the app is **reachable from the
internet**. It is a self-assessment, not a certification:
have it penetration-tested before you rely on it for sensitive data.

## 1. Is the data encrypted?

| Where | Encrypted? | Details |
|---|---|---|
| Browser ↔ app | **Only if you serve it over HTTPS** | In production the app forces HTTPS, secure cookies and HSTS. You must provide the certificate (nginx, a load balancer, etc.). |
| App ↔ PostgreSQL | **Yes, by default** | The app connects with `sslmode=require` (TLS). Set `DJANGO_DB_SSLMODE=verify-full` and `DJANGO_DB_SSLROOTCERT` to also verify the database server's identity. Verified here: TLS 1.3. |
| Data on the database disk | **No, not by PostgreSQL itself** | Community PostgreSQL has no built-in "transparent data encryption". Vessel names, services, crew names, flight and personal data are stored as readable text in the data files. Protect them with **disk / volume encryption** (LUKS / dm-crypt, or your cloud provider's encrypted storage / managed-database encryption), and encrypt the **backups** too. |
| Passwords | **Hashed, not encrypted** | Salted PBKDF2-SHA256 (Django default). They cannot be read back, only checked. |
| Individual fields (e.g. crew passport / personal data) | **No** | Not encrypted at application level. Crew personal data is personal data: if your policy or law requires it, add field-level encryption (e.g. a Fernet key held outside the database) – ask for this and it can be added. |
| Secrets | Environment variables | `DJANGO_SECRET_KEY`, DB password. Never commit them; the app refuses to start in production without a secret key. |

## 2. OWASP Top 10 (2025)

Each row: what the app does, which tests prove it, and what is left to the people who deploy it.

| # | Risk | What the app does | Proved by | What is left to you |
|---|---|---|---|---|
| A01 | Broken access control (incl. SSRF) | Every API call goes through `json_api` → role check → port-scoped queries (`access.scoped_vessels`, `access.scoped_closures`). Port users get *404* for other ports' vessels, services, bookings and port closures, can't widen the port filter and are pinned to their port on create / update. Read-only users can't write, except the **accounting Open / Closed switch** (`POST /api/accounting/`, admins and read-only only, scoped, rate limited, audited); a Closed line locks that service / booking / garbage & sludge and its vessel's delete for every role until accounting reopens it. Exchange rates, moving Master-data values and the **change history** are admin-only. The **LOG letter** (a PDF with the signed company stamp) and the **master receipt** (a PDF, no stamp) are made only by roles that can edit that vessel's port. The **management Excel** may be downloaded by every role but only covers the vessels and closures that role may see (port users pinned to their port). Every `<int:pk>` route looks the object up through a scoped query. Unknown users start read-only. The server never fetches a URL a user supplies (no SSRF surface). | `tests.AccessTests`, `tests_logistics`, `tests_closures`, `tests_options`, `tests_history.HistoryApiTests`, `tests_logpdf.LogViewTests`, `tests_receipt`, `tests_management.ExportTests`, `tests_accounting` | Give each person the least role they need. |
| A02 | Security misconfiguration | `DEBUG` is **off unless `DJANGO_DEBUG=1`** (fails closed without a secret key); strict CSP (no inline scripts or styles, Trusted Types with **no** policy; the Django admin gets the same CSP without Trusted Types and with style attributes allowed, because its own scripts need them), `X-Frame-Options: DENY`, `nosniff`, referrer / permissions / cross-origin policies, `no-store` on private responses; production cookies are `__Host-` prefixed; unknown URLs and unexpected errors never show Django pages (JSON under `/api/`, plain pages elsewhere); `check --deploy` is clean and fails (`sheet.E001`) behind a proxy without a client-IP header. | `tests.SessionAndHeaderTests`, `tests.DebugDefaultTests`, `tests_hardening`, `tests_errors` | Never set `DJANGO_DEBUG=1` on a server; restrict `ALLOWED_HOSTS`; harden the server and PostgreSQL (§4). |
| A03 | Software supply chain failures | Two runtime dependencies (Django, psycopg). `requirements.txt` is a **lock with exact versions and the SHA-256 of every published file**, installed with `--require-hashes`; `requirements.in` holds the ranges. No third-party code in the browser beyond the app's own (the PDF reader and its vendored PDF.js were removed); nothing loads from any other site (no CDNs, no web fonts: the system font is used, and the CSP has `font-src 'none'`). `npm run check` runs `pip-audit` and `npm audit`. | `tests_supply_chain`, `tests_frontend_safety.NoPdfReaderTests` | Install only with `pip install --require-hashes -r requirements.txt`; re-run `pip-audit` and update on Django security releases. |
| A04 | Cryptographic failures | HTTPS enforced + HSTS + Secure / HttpOnly / SameSite cookies in production; DB connection TLS by default; salted PBKDF2 passwords; secret key required; no secret is logged or returned by the API. | `tests.SessionAndHeaderTests`, `tests.DatabaseSettingsTests`, `tests.SecurityLogTests` | Certificates, disk / backup encryption (see §1), key management. |
| A05 | Injection | Django ORM only (no raw SQL). All input whitelisted, typed and length-limited in `validators.py`; query parameters typed and sliced; the client-IP header is parsed as an address. The browser never parses HTML strings: screens are built with `js/dom.js`; `innerHTML` & co. are banned by ESLint and refused by the browser (Trusted Types); no `eval` / `new Function`. Log values are escaped; CSV export neutralises formulas. The LOG and master receipt PDFs are written by our own code (no library): crew and receipt text only ever goes in as an escaped PDF string, never as a name, operator or link; pictures are fixed JPEG files placed as they are, never decoded. The management Excel and the data export files are written by our own code too: every text cell is an escaped inline string, never a formula (`=`, `+`, `-`, `@` stay text). | `tests` (hostile JSON, CSV injection, log escaping), `tests_logpdf`, `tests_xlsx`, `tests_dataexport`, `dom_test.js`, `tests_frontend_safety`, smoke test with markup-like names | – |
| A06 | Insecure design | Least-privilege roles; server-side money maths; 1 MB requests; login lock-out; **API rate limits** in the database: writes 120 / 10 min per user and 600 / 10 min per address, CSV export, LOG letters, master receipts and the management Excel together 20 / 10 min per user (`DJANGO_RATE_LIMIT_*`), answered with 429. Requests are counted, not rows. If the counter fails, writes are refused (503) and reads go through. | `tests_ratelimit` | A proxy-level limiter for anonymous floods (the app counts signed-in requests). |
| A07 | Authentication failures | 12+ character passwords with common / similar / numeric checks; lock-out on **both** `/login/` and the admin login (5 failures per user + address, 30 per address, 15 min); the same answer for an unknown user and a wrong password; a new session key on every sign-in; sessions expire after **60 minutes idle**; sessions end on password change. **Two-step login for everyone** (`sheet/twostep.py`, django-otp): after the password, a six-digit TOTP code from Microsoft Authenticator (SHA-1, 30 s, ±1 step; a code is never accepted twice; two requests at once are serialised by a row lock on PostgreSQL). One gate (`TwoStepMiddleware`) blocks every page, API call (401), the CSV export and the Django admin until the step is passed; the passed state is re-checked on every request, so a reset, a forgotten computer or a removed exception ends live sessions. Wrong codes: django-otp's growing wait plus the same lock-out as passwords (5 per user + address). Setup only within 72 hours of the account's creation or a reset (the window closes once set up), and only after a password set by someone else has been replaced by the person's own (a different one). "Remember this computer" (30 days): a random token in an HttpOnly `__Host-` cookie, only its SHA-256 on the server; ends on password change, reset or Forget. Exceptions (password only) never for role admin, superusers or staff. The Authenticator key never appears in the history, logs, API or admin pages (django-otp's own admin page is replaced). | `tests` (throttle, password rules), `tests_hardening.LoginEnumerationTests`, `SessionRotationTests`, `tests_twostep` | No self-service "forgot password" – an admin resets it. Keep at least two superusers with Authenticator (`check --deploy --database default` warns, `sheet.W002`); `manage.py reset_two_step <username>` is the last resort. |
| A08 | Software or data integrity failures | Hash-checked dependencies (A03); no deserialisation of untrusted data; a **change history** (`ChangeRecord`) records every create / update / delete of vessels, services, bookings, guests, Master data, exchange rates, user roles and user accounts (staff / superuser / active flags; a password change is recorded as "(changed)", never the hash) — who, when, from which address, old → new. For every change made through the app's API or the Django admin it is written in the same transaction (if it can't be written, the change fails); management commands and the shell are recorded as "system" but not held to that. No edit / delete path in the app or the Django admin; on PostgreSQL a trigger refuses UPDATE and DELETE. Kept forever. **The trigger stops app bugs and ordinary SQL, not the table's owner** (who can disable it or TRUNCATE). | `tests_history` | To make the history tamper-proof against someone holding the app's database password, run migrations as the owner role and the app as a second role with only `SELECT, INSERT` on `sheet_changerecord` (and normal rights elsewhere); never run `manage.py flush` in production. Back the database up. |
| A09 | Security logging and alerting failures | Audit log (`sheet.audit`), security log (`sheet.security`: logins, lock-outs, denied requests, rate limits, server errors with their reference), the change history and an admin **History** page. **Alerting:** 10 lock-outs, denied requests or server errors within 10 minutes (`DJANGO_ALERT_THRESHOLD`, `DJANGO_ALERT_WINDOW_SECONDS`) write one `sheet.alert` ERROR record and e-mail `DJANGO_ALERT_EMAILS` if set. Logs can also go to a rotating file (`DJANGO_LOG_FILE`). Passwords are never logged. | `tests_errors.AlertTests`, `tests.SecurityLogTests` | Ship the logs somewhere central; set the alert e-mail and `DJANGO_EMAIL_*`. |
| A10 | Mishandling of exceptional conditions | Every API error answers JSON (including CSRF failures, over-size bodies, 400 / 403 / 404); an unexpected one answers `{"error": "Something went wrong.", "ref": "…"}` with an 8-hex reference that is also in the security log (with the stack trace), never a trace to the browser; the page shows the reference. Failures fail closed: a rate-limit store fault refuses writes, a history-write fault rolls the change back. | `tests_errors.ErrorResponseTests`, `tests_ratelimit`, `tests_history` | Watch the log for `server error ref=`. |

## 3. Known gaps (honest list)

1. **Two-step login** (since 2026-11-18) uses authenticator codes, which a convincing fake sign-in page can still
   relay in real time; phishing-proof passkeys / security keys are not supported. No backup codes: a lost phone is
   reset by a superuser. Exceptions (password only) are possible for non-admins and recorded in the history.
2. **No field-level encryption** of crew personal data (see §1).
3. **No third-party requests from the page** (since 2026-11-18: system font, icons drawn into the page as an inline
   SVG sprite). Inline styles are not allowed: `style-src-attr 'none'`.
4. **Login throttling and API rate limits use the database**, which is fine for a small team; very high traffic
   would want a proxy-level limiter too.
5. **Password change** requires the old password but isn't throttled separately (needs an authenticated session).

## 4. Deployment checklist

The full step-by-step procedure (database logins, service, web server, accounts, backups) is `docs/DEPLOYMENT.md`; this list is what must be true at the end.

* Install with `pip install --require-hashes -r requirements.txt` (exact versions, every file hash-checked).
* HTTPS everywhere; leave `DJANGO_DEBUG` unset (or `0`); set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
* Serve the app from the **root of its own host** (e.g. `https://sheet.example.com/`, not `/sheet/`): the cookies are
  `__Host-` prefixed, which browsers only accept for path `/` over HTTPS. Everyone signs in once more after this update.
* Behind a proxy: `DJANGO_BEHIND_PROXY=1` **and** `DJANGO_CLIENT_IP_HEADER=X-Forwarded-For` (`check --deploy` fails
  with `sheet.E001` without it: rate limits, lock-outs and the history would see every visitor as one address). Make
  sure the proxy *appends* the real client address and that clients cannot reach the app directly.
* Alerting: `DJANGO_ALERT_EMAILS=a@example.com,b@example.com` plus `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`,
  `DJANGO_EMAIL_USER`, `DJANGO_EMAIL_PASSWORD`, `DJANGO_EMAIL_FROM` (TLS on unless `DJANGO_EMAIL_TLS=0`; a mail server
  that does not answer is given up after `DJANGO_EMAIL_TIMEOUT` = 10 seconds). Counting uses fixed windows, so a burst
  that straddles two windows can stay just under the threshold in both.
* Logs: `DJANGO_LOG_FILE=/var/log/marine-sheet/app.log` for a rotating file (10 × 10 MB) as well as the console.
* PostgreSQL:
  * Create a dedicated, **non-superuser** role that owns only this database (`CREATE ROLE … LOGIN PASSWORD …; CREATE DATABASE … OWNER …;`).
  * `ssl = on` with a real certificate, `hostssl` lines in `pg_hba.conf` using `scram-sha-256`, no `trust`, listen only on the interfaces you need and firewall port 5432.
  * Use `DJANGO_DB_SSLMODE=verify-full` with `DJANGO_DB_SSLROOTCERT`.
  * Encrypt the disk / volume and the backups; test restoring a backup.
* Delete the demo users; create real ones with long passwords; consider `DJANGO_ADMIN_URL=private-path/`.
* LOG letter pictures: put `logo.jpg`, `stamp.jpg` and `footer.jpg` (baseline JPEGs, at most 2 MB each) in a folder
  **outside the project and outside static files**, readable only by the app's user, and set `DJANGO_LETTERHEAD_DIR` to
  it. Never commit them (the stamp is signed); `.gitignore` ignores a `letterhead/` folder.
* Static files: run `python manage.py collectstatic --noinput` on every release and have the web server serve
  `staticfiles/` at `/static/` with `Cache-Control: no-cache` (README, "Static files … in production").
* Run `cd tools && npm run check` on every release (it includes `check --deploy`, `pip-audit` and `npm audit`).
* On the server, `python manage.py check --deploy --database default`: warns (`sheet.W002`) while fewer than two
  active superusers have Authenticator set up.
* Centralise and monitor the `sheet.audit`, `sheet.security` and `sheet.alert` logs.

## 5. What is tested

`python manage.py test sheet` (646 tests on SQLite; all 452 also passed on PostgreSQL 17 on 2026-11-19; three of them check the
history's append-only trigger and run on PostgreSQL only): access control for every endpoint and role, port isolation, CSRF, malformed / hostile JSON,
validation limits, money maths, login throttling (user, IP, admin login, proxy header spoofing), password change
rules, audit / security logging without secrets, headers and CSP, CSV injection, port-call time
rules, database settings, the dependency lock, API rate limits, JSON errors with references, alerting, the change
history (every path incl. user accounts, rollback on failure, admin-only API), `__Host-` cookies, the proxy deploy check and login
answers.
Front end: `tools/` has parser unit tests, element-builder tests (`dom_test.js`: markup in values stays text, unsafe
attributes and links are refused) and a browser-less end-to-end test that clicks through every page as each role, with
markup-like names (`<i>`, `<b>`, `&`, quotes) checked to show literally on every screen (the History page included).
Source checks: no `eval`, no inline `style=` in templates, no PDF reader (`tests_frontend_safety.py`).
