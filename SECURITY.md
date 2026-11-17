# Security notes

This document says what the app does, what it does **not** do, and what you must do when deploying.
It maps to the OWASP Top 10 (2021) and the main OWASP ASVS themes. It is a self-assessment, not a certification:
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

## 2. OWASP Top 10 (2021)

| # | Risk | What the app does | What is left to you |
|---|---|---|---|
| A01 | Broken access control | Every API call goes through `json_api` → role check → port-scoped queries. Port users get *404* for other ports' vessels/services, can't widen the port filter, and are pinned to their port on create/update/bulk. Read-only users can't write. Exchange rates are shared by every port, so only admins can change them; only admins can move a Master-data value to another port (port users' values always belong to their port). Hotel stays and transfers are scoped through their vessel (404 across ports); every role may read their cost and revenue (user decision), only editors change them. Unknown users start read-only. Tested for every endpoint. | Give each person the least role they need. |
| A02 | Cryptographic failures | HTTPS enforced + HSTS + secure cookies in production; DB connection encrypted; PBKDF2 passwords; secret key required. | Certificates, disk/backup encryption (see §1), key management. |
| A03 | Injection | Django ORM only (no raw SQL). All input whitelisted, typed and length-limited in `validators.py`. The browser code never parses HTML strings: screens are built from elements with typed text inserted as text (`js/dom.js`); `innerHTML` & co. are banned by ESLint and refused by the browser through Trusted Types (`require-trusted-types-for 'script'`); no `eval` / `new Function` anywhere (PDF.js patched, see `vendor/pdfjs/PATCHES.md`); strict CSP with no inline scripts or styles, CSV export neutralises formula injection. Tested with script payloads. | – |
| A04 | Insecure design | Least-privilege roles, all-or-nothing bulk imports, server-side money maths (the browser preview is never trusted), request size limits (1 MB), bulk limit (200 rows), login lock-out. | API-wide rate limiting at the proxy (e.g. nginx `limit_req`). |
| A05 | Security misconfiguration | Secure defaults: `DEBUG` is **off unless `DJANGO_DEBUG=1` is set** (only `runserver` / `test` switch it on), so a forgotten environment fails closed; strict CSP, `X-Frame-Options: DENY`, `nosniff`, referrer / permissions / cross-origin policies, `no-store` on all private responses; `manage.py check --deploy` is clean (only the deliberate HSTS-*preload* note). | Never set `DJANGO_DEBUG=1` on a server, restrict `ALLOWED_HOSTS`, harden the server and PostgreSQL (§4). |
| A06 | Vulnerable & outdated components | Few dependencies (Django, psycopg). `pip-audit`: no known vulnerabilities at build time. PDF.js is bundled locally at 4.10.38 (past CVE-2024-4367) and run with `isEvalSupported: false`. No third-party scripts load from CDNs. | Re-run `pip-audit` regularly, update Django on security releases, update the vendored PDF.js when new versions appear. |
| A07 | Identification & authentication failures | 12+ character passwords with common/similar/numeric checks; throttle on **both** `/login/` and the admin login (5 failures per user+IP, 30 per IP, 15 min, stored in the DB); generic error text; sessions expire after **60 minutes idle** (`DJANGO_SESSION_IDLE_MINUTES`); cookies HttpOnly + SameSite=Lax + Secure; sessions end on password change; users can change their own password. | **No multi-factor authentication** (see §3). No self-service "forgot password" – an admin resets it. |
| A08 | Software & data integrity failures | No CDN scripts (nothing to tamper with); vendored PDF.js with its licence; migrations are plain Django; no deserialisation of untrusted data. | Verify what you deploy (pin versions, review updates). |
| A09 | Logging & monitoring failures | Audit log (`sheet.audit`): logins, creations, edits, deletes, bulk adds, exports, rate and master-data changes – with user and IP. Security log (`sheet.security`): failed logins, lock-outs, denied requests. Passwords are never logged; usernames and every audited value are logged with control characters escaped, so typed text can't forge log lines. | Ship the logs somewhere central and alert on repeated failures. |
| A10 | Server-side request forgery | The server never fetches URLs supplied by users. PDFs are read in the browser. | – |

## 3. Known gaps (honest list)

1. **No MFA.** Admin and port accounts rely on password + lock-out only. For admins in particular, add TOTP
   (e.g. `django-otp`) or put the site behind your company SSO / VPN.
2. **No field-level encryption** of crew personal data (see §1).
3. **Google Fonts are loaded from Google**; self-host them if you want zero third-party requests. (Inline styles are
   no longer allowed: `style-src-attr 'none'`.)
4. **Login throttling uses the database**, which is fine for a small team; very high traffic would want a
   proxy-level limiter too.
5. **Password change** requires the old password but isn't throttled separately (needs an authenticated session).

## 4. Deployment checklist

* HTTPS everywhere; leave `DJANGO_DEBUG` unset (or `0`); set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
* Behind a proxy: `DJANGO_BEHIND_PROXY=1` and `DJANGO_CLIENT_IP_HEADER=X-Forwarded-For` (otherwise the login lock-out sees
  every visitor as one address). Make sure the proxy *appends* the real client address and that clients cannot reach the app directly.
* PostgreSQL:
  * Create a dedicated, **non-superuser** role that owns only this database (`CREATE ROLE … LOGIN PASSWORD …; CREATE DATABASE … OWNER …;`).
  * `ssl = on` with a real certificate, `hostssl` lines in `pg_hba.conf` using `scram-sha-256`, no `trust`, listen only on the interfaces you need and firewall port 5432.
  * Use `DJANGO_DB_SSLMODE=verify-full` with `DJANGO_DB_SSLROOTCERT`.
  * Encrypt the disk / volume and the backups; test restoring a backup.
* Delete the demo users; create real ones with long passwords; consider `DJANGO_ADMIN_URL=private-path/`.
* Run `cd tools && npm run check` on every release (it includes `check --deploy`, `pip-audit` and `npm audit`).
* Centralise and monitor the `sheet.audit` and `sheet.security` logs.

## 5. What is tested

`python manage.py test sheet` (152 tests, also run against PostgreSQL 16): access control for every endpoint and role,
port isolation, CSRF, malformed / hostile JSON, validation limits, money maths, login throttling (user, IP, admin login,
proxy header spoofing), password change rules, audit/security logging without secrets, headers and CSP, CSV injection,
bulk all-or-nothing, port-call time rules, database settings.
Front end: `tools/` has parser unit tests, element-builder tests (`dom_test.js`: markup in values stays text, unsafe
attributes and links are refused) and a browser-less end-to-end test that clicks through every page as each role, with
markup-like names (`<i>`, `<b>`, `&`, quotes) checked to show literally on every screen. Source checks: no `eval`, no
inline `style=` in templates (`tests_frontend_safety.py`).
