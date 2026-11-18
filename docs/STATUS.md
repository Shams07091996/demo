# Project status

Last updated: 2026-11-18. Read this with `CLAUDE.md` before starting work. Each feature has a design
(`docs/superpowers/specs/`) and a build plan (`docs/superpowers/plans/`) that record what was decided and why.

## Where things stand right now

- **Two-step login (2026-11-18):** merged into `main` (branch deleted).
  Needs migration **`0012_two_step_login`** and `pip install --require-hashes -r requirements.txt` (new packages
  django-otp, segno). After merging, on the user's PostgreSQL database: `migrate`, create the superusers, each sets up
  Authenticator within 72 hours of the migration / account creation.
- **Git branches:** `main`, plus `chore/pythonanywhere-demo` (not merged: puts back the hash-locked
  `requirements.txt` and the settings that the user's Render commits on `main` had replaced). Agents per job, Dashboards and New look merged 2026-11-18 (branches deleted).
- **Online demo (2026-11-18):** https://shams1996.pythonanywhere.com (PythonAnywhere free plan, the user's account,
  demo data only, SQLite with `DJANGO_ALLOW_SQLITE=1`; built from `chore/pythonanywhere-demo`). How to update or
  remove it: `docs/DEMO_HOSTING.md` part B. Render was dropped (needs a credit card). `origin` is the user's
  GitHub repo `Shams07091996/demo` (public).
- **Tests:** `npm run check` green with 319 backend tests on `main`; smoke test
  (now signing in with a code) passes for `alex`, `admin`, `viewer` and `suez`. Screenshots (light / dark / phone) in `.superpowers/screenshots/new-look/` (not in git).
- **The user's own database:** **PostgreSQL 17 only**, on this PC (port 5432; PostgreSQL 18 on 5433 is not used).
  Database `marine_sheet`, signed in as `postgres` for now (password in the user's
  `%APPDATA%\postgresql\pgpass.conf`, never in the project). Migrations through `0010` applied; **`0011_agents_per_job` still to apply** (`DJANGO_DEBUG=1 python manage.py migrate` with the settings below); no users yet.
  The old `db.sqlite3` (test data) was deleted. Before company data: a dedicated `marine_app` login instead of the
  superuser, and a stronger `postgres` password.
  App settings for it: `DJANGO_DB_NAME=marine_sheet DJANGO_DB_USER=postgres DJANGO_DB_HOST=localhost
  DJANGO_DB_PORT=5432 DJANGO_DB_SSLMODE=disable` (the local server has SSL off and accepts local connections only).
- **Tests (on `main`):** `cd tools && npm run check` → all passed (235 backend tests; the 204 of 2026-11-17 also passed on PostgreSQL 17, the agents tests not yet); `tools` parser tests pass; the jsdom smoke test
  passes for `admin`, `alex`, `viewer` and the short `suez` run (see `CLAUDE.md` for the throwaway-database setup).

## Built and tested

| When | What | Design |
|---|---|---|
| 2026-11-18 | Faster first load: the page names all 32 script files up front (`modulepreload`), so they arrive in 1 round instead of 4; vessel toolbar on one line (no big empty gap) | — |
| 2026-11-15 | Security fixes: exchange rates admin-only; debug mode off unless `DJANGO_DEBUG=1`; audit-log values escaped | — |
| 2026-11-15 | Vessel list served by the server: From–To date range (this month by default), search, ARK / MSK / Other chips, sorting, paging 10 / 25 / 50 / 100; Dashboard, OPR summary, alerts and CSV from the server; "Saved — … outside the current date range" notice with **Show it** | `2026-11-15-server-side-vessel-list-design.md` |
| 2026-11-15 | Vessels page trimmed at the user's request: no stat cards, no CSV button, no Total Cost column, smaller chips, a 🗑 Delete button per row (click a row to edit) | — |
| 2026-11-15 | Bulk add: editable preview table (edit cells, live checks, add / remove rows, "Set on all rows", server duplicate check); help text and placeholders removed | `2026-11-15-bulk-add-editable-preview-design.md` |
| 2026-11-15 | ☰ hides / shows the sidebar on wide screens; alerts banner can shrink to one line; dev `runserver` sends static files with `no-cache` | — |
| 2026-11-16 | 🏨 Hotels and 🚗 Transport pages: bookings for 1–6 crew guests of a vessel (rooms and cars can be shared), entered on their own pages with the guest picked from the vessel's crew change; transfers name which airport / hotel / port (Master data lists) | `2026-11-16-hotels-and-transport-design.md` |
| 2026-11-16 | 💰 Calculations page: every money line with its working (amount × rate = EGP) for a vessel-date range / OPR / port, one totals line; every service (Crew Change and Others too) and every booking has cost and revenue; one money-maths source (`finance.service_lines`), amounts rounded to the cent once | `2026-11-16-calculations-page-design.md` |
| 2026-11-17 | Safe page building: no `innerHTML` / HTML strings anywhere (screens built with `js/dom.js`), browser-enforced by Trusted Types and a CSP with no inline styles; every `eval` removed (PDF.js patched); ruff security rules, ESLint, pip-audit, npm audit and `npm run check` | `2026-11-17-safe-dom-and-checks-design.md` |
| 2026-11-17 | Master data per port: every list's values belong to one port or All ports (admins choose and can move them); every dropdown offers the item's port + All-ports values | `2026-11-16-master-data-per-port-design.md` |
| 2026-11-17 | OWASP Top 10 (2025) hardening: PDF reader removed (CSP `trusted-types 'none'`); hash-locked `requirements.txt` from `requirements.in`; API rate limits (writes per user / address, CSV per user, 429; broken counter refuses writes); every API error JSON, unexpected ones with an 8-hex `ref` in the log; alerting (`sheet.alert` + optional e-mail); append-only change history of every tracked model incl. user accounts, with an admin-only 🕘 History page; `__Host-` cookies in production; deploy check `sheet.E001`; SECURITY.md rewritten for 2025 | `2026-11-17-owasp-2025-design.md` |
| 2026-11-18 | **Agents per job** (merged 2026-11-18): Arrival agent (was Agent) and Sailing agent on each vessel, an Agent on every service (all from the Master data Agent list, empty until chosen); search / sort / CSV / "used by N" cover them; a **Missing agent** alert (bell + banner, max 20 rows + "+ N more") for vessels dated before today that miss any agent; **Bulk add removed** | `2026-11-18-agents-per-job-design.md` |
| 2026-11-18 | **Dashboards** (merged 2026-11-18): one filter bar (dates, port, OPR, agent, service type); jobs per agent (bars + table; a row opens that agent's jobs), services per month (stacked columns + table), money per month (Cost / Revenue / Profit table); OPR charts and cards follow the filters | `2026-11-18-dashboards-design.md` |
| 2026-11-18 | **New look** (merged 2026-11-18): neutral grey with one blue accent; dark and light mode (follows the computer until chosen in the sidebar, remembered); system font, no Google Fonts (CSP `font-src 'none'`); 28 line icons drawn for the app instead of emojis; full-width pages, smaller radii, no gradients or all-caps headings | `2026-11-18-new-look-design.md` |
| 2026-11-18 | **Two-step login** (security piece 3): password + six-digit Microsoft Authenticator code for everyone; one gate for every page, API call and admin page; remember this computer 30 days (Forget in the sidebar); setup within 72 hours of creation / reset; forced password change when someone else set it; superuser-only reset (admin action, `reset_two_step` command); exceptions for non-admins; key never in history / logs / admin; deploy warning `sheet.W002` (fewer than two superusers with Authenticator) | `2026-11-17-two-step-login-design.md` |
| 2026-11-16 | Project put under git; `CLAUDE.md` and this file written for future sessions | — |

## Decisions the user made (respect these)

- **Who sees what:** admins everything; port users only their port (server-enforced); **read-only users see all
  money everywhere** (vessels, Dashboard, Hotels / Transport cost and revenue, Calculations) but change nothing. The
  read-only role is also used by the hotel / transport staff.
- **Money:** every service and every booking has cost (what we pay) and revenue (what we get). **Hotel / transport money
  counts only on the Calculations page**, never in vessel totals, the Summary of services or the Dashboard. Crew
  Change / Others money does count in vessel totals (they are services).
- **Calculations page:** company profit view, filtered by date range and OPR; the range is on the **vessel date**
  (a vessel's whole port call lands in one period).
- **Hotels / Transport:** two separate pages; bookings entered there (not in the Crew Change editor); one room or one
  car trip can hold several guests and is priced once; transfers record which airport / hotel / port; no driver data.
- **Master data:** every list (OPR, POC, Agent, Hotel, Airport, Port) can be per port; admins choose (default All
  ports) and can move values; port users' values are their port's.
- **Security first:** the app is being sold to the user's company. The front end never parses HTML strings
  (no `innerHTML`, no `eval`, no inline styles) and the browser enforces it; keep it that way.
- **UI taste:** lean screens — no help paragraphs, no placeholders, no stat cards; compact controls.
- **Process:** the user chooses **Native** execution (built in-session, one fresh reviewer at the end).
- **Agents (2026-11-18):** an arrival agent and a sailing agent per vessel and an agent per service; **no defaults** (the sailing agent is never copied from the arrival agent, a service never gets the vessel's agent); **every** service type needs an agent, Others / Remarks too; the alert starts the day after the vessel date (agents are known only after the job) and has no look-back limit.
- **Bulk add removed** (2026-11-18, "not needed").
- **Order (2026-11-18):** agents → dashboards → new look, **before** two-step login (which will then be built in the new look).
- **Dashboards (designed 2026-11-18):** jobs per agent (arrival = 1 job, sailing = 1, each service = 1), services per month, money per month as a **separate** table; chart **and** figures; filters date / port / OPR / agent / service type.
- **New look (designed 2026-11-18):** look B (neutral grey, one blue accent), dark and light mode, system font, line icons drawn for the app; **no third-party dependency**.
- **Two-step login (approved 2026-11-18, "go ahead with 2fa"):** everyone, Microsoft Authenticator codes, 30-day
  remember for everyone, no backup codes, superusers reset each other (3–4 planned), exceptions only for non-admins;
  **not for the online demo** for now ("no need for the demo right now").
- **Field encryption** of crew personal data: **not now** — revisit when getting ready for production (disk / backup encryption is the production setup step).

## Next

Agreed order (2026-11-18), each on its own branch, designed and approved:

1. **Agents per job** — done and merged (2026-11-18).
2. **Dashboards** — done and merged (2026-11-18).
3. **New look** — done and merged (2026-11-18).
4. **Two-step login** — done and merged (2026-11-18).

The user is **selling the app to their company: security comes first** ("no security vulnerability should be there").
Their security push has three pieces, in this order:

1. **Safe page building + checks** — done and merged (2026-11-17).
2. **OWASP Top 10 (2025) review** — done and merged (2026-11-17).
3. **Two-step login (MFA)** — done and merged (2026-11-18).

4. **After the security push** (user's top picks from the ARKAS 2027 preview): keep the exchange rate used by each
   service, service status (completed / in progress / cancelled + reason), billing basis (Cash / Owners' Account),
   accounts review (Pending / Reviewed, possibly an Accounts role).

Also: the user may want to move the old shared agent / hotel to a port (Master data page).

Ideas raised along the way:

- Exports of the Calculations page.

## Left open — small things the user hasn't decided on yet

OWASP 2025 (from the final review, minor / for the user to decide):
- The history keeps crew personal data (guest names, crew in services) forever and, on PostgreSQL, undeletable:
  conflicts with right-to-erasure — a policy decision for the company.
- Splitting the database roles (migrations as owner, app with only SELECT / INSERT on the history) would make the
  history tamper-proof against someone holding the app's DB password; documented in SECURITY.md, not done.
- History date filters use `at__date`, which can't use the index; slows down as the table grows (filter on Cairo
  start / end datetimes instead).
- Counters use fixed windows: two requests finding an expired window both reset it (one count lost); a burst across a
  window edge can stay under the alert threshold.
- `profile_of`'s first-use profile creation and management commands are not atomic with their history record.
- Every booking edit records a delete + create for each guest (the guests are replaced); noisy but accurate.
- Front-end display of the error reference (`js/api.js`) has no automated test.

Vessel list:
- The outside-range notice also shows for edits that didn't change the date.
- The default month and "Today / Tomorrow" labels use the browser's clock, not Cairo's.
- Sorting by Port uses the port key, not its label.
- The vessel cache can show figures another user changed, until reload.

Hotels and Transport:
- An EGP booking keeps a hidden exchange rate if one was typed while USD was selected.
- A crafted `nights` value (e.g. "²") gives a 500; the dialog never sends one.
- An exchange rate like 999999.99999 overflows the database column on PostgreSQL.
- The 60-night cap is checked by the app but not on the model (the Django admin could store more).
- Transfer time pre-fill uses arrival (on-signers) / departure (off-signers) regardless of direction.
- The dialog's vessel search also matches OPR / POC / agent, not only names.
- `seed_demo` writes the flight month with the machine's locale.
- Test gaps: transfer cross-port access.

Master data per port:
- A PATCH without a `port` key moves the value to All ports (the page always sends one).
- Two admins moving the same value at once could hit the unique rule (500 instead of the duplicate message).
- The audit line for a move records the new port only.
- The server does not check that a vessel's OPR / POC / Agent belongs to its port (only the dropdowns filter).

Calculations:
- Cash to Master no longer flags "no exchange rate" when only the amount handed to the master is in USD (share 0%);
  the live preview still flags it.
- The "Item" column sorts by service type, not by the label shown.
- The Summary hides the profit banner when no service has money (it used to show 0.00).
- Migration 0008 updates bookings one at a time (fine for the few rows that exist).
- Bookings migrated from a single price show only a cost, so they appear as a loss until a revenue is entered.

Safe page building (from the final review, all minor):

- `tools/check.js`: when a tool is missing (no venv, ruff not installed) it says only "FAILED: ruff"; print the
  error too. `pip-audit` and `npm audit` need the network, so the check fails offline.
- `tools/dom_test.js` / `parsing_test.js` / `pdf_reader_test.js` leave a temp folder behind on every run.
- The smoke test doesn't check a markup-like OPR on the Dashboard bars / cards or the OPR summary title (safe by
  construction today).
- `dom.js` accepts `style: { cssText }`; nothing passes user data into `style`, but refusing `cssText` would close it.
- ESLint doesn't flag direct `el.href = …` / `.src = …` assignments (none exist).
- SECURITY.md A05 still mentions "the deliberate HSTS-preload note"; `check --deploy` is now simply clean.
- `requirements-dev.txt` doesn't pin ruff / pip-audit versions.

Development database:

- SQLite (development only) can answer **"database is locked" (500)** when two requests write at once (every
  request saves the session). Seen in the smoke test; the test now waits. Possible fix: `"transaction_mode": "IMMEDIATE"`
  in the SQLite `OPTIONS` (`config/database.py`, Django 5.1+). Production uses PostgreSQL, which is not affected.

Agents per job (final review, minor, for the user to decide):

- `listing.missing_agents` treats an agent of only spaces as filled; only a raw database write can store one.
- No automated test runs migration 0011 itself (it is a plain rename).
- The bell panel's empty text still says "No vessels today or tomorrow." (shown only when nothing is pending).
- The Master data agent usage count reads one row per service; fine now, watch it if `/api/options/` slows.

Two-step login (final review, minor, for the user to decide):

- The "fewer than two superusers with Authenticator" warning (`sheet.W002`) reads the database, so it runs only with
  `check --deploy --database default` on the server, not in `npm run check`.
- The "same code twice at once" lock is a database row lock: it works on PostgreSQL (production), not on SQLite.
- Several people on one browser: "Remember this computer" remembers only the last one who ticked it.

## How work has been done here

1. **Brainstorm** with the user (Superpowers `brainstorming`): one question at a time, approaches compared, user picks.
2. **Design** written to `docs/superpowers/specs/`, read by a fresh "builder check" agent, user approves.
3. **Plan** written to `docs/superpowers/plans/` (tasks with failing tests first), user picks Native.
4. **Build** on a feature branch, test first, one commit per task; backend suite + parser tests + smoke test (3 roles).
5. **Fresh reviewer** (most capable model) reads the whole branch; important findings fixed test-first; the rest are
   listed above under "Left open".
6. Update this file, `README.md` / `SECURITY.md` test counts and `CLAUDE.md`.

## Operational notes

- After front-end changes, a browser that cached old modules may need one hard refresh (Ctrl + Shift + R); the dev
  server now sends `no-cache`, so this is only needed once after upgrading from an old version.
- Moving data from SQLite to PostgreSQL: see README "PostgreSQL" (`dumpdata` → `migrate` → `loaddata`).
- Git commits made by Claude end with a `Co-Authored-By: Claude …` line.

Dashboards (final review, minor, for the user to decide):

- The agent-jobs list (`/api/dashboard/jobs/`) works out every vessel's money though it only needs names, dates and agents; with "All dates" each click recomputes the whole range.
- An agent named exactly `__none__` would be read as "(no agent)".
- Two quick clicks on different agent rows can open the slower answer last.
- Vessels still in port (no sailing agent yet) count as "(no agent)" sailings, as the design says.

New look (final review, minor, for the user to decide):

- The 404 and 500 pages follow the computer's light / dark setting only (they are rendered without the request, so the theme cookie is not read).
- In light mode a few tinted boxes (yellow notices, the OPR badges) are just under the 4.5:1 contrast guideline (about 4.2–4.4:1).
- The dialog header's top-right corner is rounder (16px) than the rest (6px).
- Screen readers: the "rate missing" warning icon on Calculations and the sort direction of table headings are not read out.
- If no mode was chosen and the computer switches mode while the page is open, the sidebar button's label is not updated until reload.
- The chosen mode belongs to the browser, not the user account (on a shared PC it carries over to the next person).
- OPR cards no longer say "Click for details" (they are still clickable).
- Tints and borders use CSS `color-mix()` (Chrome 111+, Edge 111+, Firefox 113+, Safari 16.2+).
