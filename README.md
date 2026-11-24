# Marine Service Sheet

A Django web app that replaces the vessel/services Excel sheet: every vessel in one table, and a click opens a
modal to record its services (zero or many). Data lives in a real database; users sign in and see only what their
role allows.

**Putting it on a server and creating everyone's account:** `docs/DEPLOYMENT.md` (step by step, with backups and what happens when the database stops or two people edit the same thing).

## Run it (development)

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install --require-hashes -r requirements.txt   # exact versions, every file checked against its hash
export DJANGO_DEBUG=1               # Windows PowerShell: $env:DJANGO_DEBUG="1"   (cmd: set DJANGO_DEBUG=1)
python manage.py migrate            # uses SQLite unless DJANGO_DB_NAME is set (see "PostgreSQL" below)
python manage.py seed_demo          # optional: demo users + vessels (prints a random password for each user)
python manage.py runserver
```

**Debug mode is off unless `DJANGO_DEBUG=1` is set**, so a production server whose environment was forgotten refuses to
start instead of running in debug mode with a public secret key. `runserver` and `test` switch it on by themselves; other
commands (`migrate`, `seed_demo`, `createsuperuser`) need the `DJANGO_DEBUG=1` line above when you run them locally.

Open http://127.0.0.1:8000/ and sign in. For real accounts use `python manage.py createsuperuser`, then give each
user a role in the admin (`/admin/` -> Users -> Profile). **New users start read-only.**

**Two-step login:** after the password everyone types a six-digit code from **Microsoft Authenticator** (any
authenticator app works). At the first sign-in the person scans a QR code; this is only possible within 72 hours of
the account being created or reset. "Remember this computer" skips the code on that browser for 30 days (Forget this
computer in the sidebar). A person whose password was set by someone else must choose their own first. A lost phone:
a superuser picks the person in `/admin/` -> Users -> action "Reset two-step login", or on the server
`python manage.py reset_two_step <username>`. A superuser can make a non-admin an exception (password only). Keep at
least two superusers with Authenticator set up (`check --deploy --database default` warns, `sheet.W002`).

## PostgreSQL

Production runs on PostgreSQL (the app refuses to start in production on SQLite). Create a role and database, then set
the `DJANGO_DB_*` variables from `.env.example`:

```sql
CREATE ROLE marine_app LOGIN PASSWORD '…long random…';
CREATE DATABASE marine_sheet OWNER marine_app;
```

The connection is encrypted by default (`sslmode=require`); use `verify-full` with a CA file when you can. **PostgreSQL
does not encrypt the data on disk by itself** – see `SECURITY.md` §1 for what is and isn't encrypted and what to do about it.
The backend suite was tested on PostgreSQL 17 (all 452 tests on 2026-11-19; an older suite also on 16). A local PostgreSQL without a certificate needs `DJANGO_DB_SSLMODE=disable`.

**Moving existing data from SQLite to PostgreSQL** (Django's own export / import; users keep their hashed passwords):

```bash
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e admin.logentry -e sessions --indent 2 -o data.json   # still on SQLite
python manage.py migrate        # with the DJANGO_DB_* variables pointing at PostgreSQL
python manage.py loaddata data.json
```

PostgreSQL enforces text lengths and number sizes that SQLite ignores; the app trims input before saving, so normal
data loads, but run the test suite against PostgreSQL once before relying on it.

## Static files (CSS, scripts, icons) in production

With debug off, Django does **not** serve the CSS and JavaScript files: without the step below the page loads with no
styles and no scripts. On every release, in the production environment:

```bash
python manage.py collectstatic --noinput     # copies everything under static/ into staticfiles/
```

Then let the web server answer `/static/` from that `staticfiles/` folder and send everything else to Django. The files
have fixed names (no version in the name), so tell browsers to check for a newer copy each time (`no-cache`): otherwise
after an update a browser can mix old and new scripts and the page breaks. Example for nginx:

```nginx
location /static/ {
    alias /srv/marine_sheet/staticfiles/;
    add_header Cache-Control "no-cache";
    add_header X-Content-Type-Options "nosniff";
}
location / {
    proxy_pass http://127.0.0.1:8000;              # the WSGI server running config.wsgi
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;    # with DJANGO_BEHIND_PROXY=1
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;   # with DJANGO_CLIENT_IP_HEADER=X-Forwarded-For
}
```

- **IIS:** a virtual directory `/static` pointing at `staticfiles\`, with `Cache-Control: no-cache` in its HTTP response
  headers.
- **PythonAnywhere:** Web tab → Static files → URL `/static/`, directory `…/marine_sheet/staticfiles`.
- Never put anything private in `static/`: everything there is public. The LOG letter pictures stay in their own folder
  (`DJANGO_LETTERHEAD_DIR`).
- The development server (`runserver`) serves these files itself, already with `no-cache`.

## Pages (sidebar)

| Page | What it is for |
|---|---|
| Vessels | The vessel table for a **From – To date range** (this month by default), quick-add bar, search / ARK–MSK filters, sorting and paging (10 / 25 / 50 / 100 rows) – all done by the server – a *Summary of services* button on every vessel, CSV export of everything matching |
| Hotels | Every hotel stay (one room, 1–6 crew guests, check-in, nights, hotel from Master data) with guest and vessel, for a date range and port; cost and revenue per night; editors add / edit / delete, read-only users only see |
| Transport | Every transfer between an airport, a hotel and a port — saying which one of each, from Master data — with date and time, 1–6 guests, flight and vessel; same rules as Hotels |
| Calculations | Every money line — each service (each entry of Parcels / Courier / Landing), hotel stay and transfer — for a vessel-date range, OPR and port, showing its working (amount × rate = EGP) and one totals line (revenue, cost, profit, lines without an exchange rate). Every role can see it |
| Dashboard | Filters (dates, port, OPR, agent, service type); jobs per agent (chart + table, a row lists that agent's jobs), services per month (stacked chart + table), money per month (table), then the OPR charts and cards — all totalled by the server |
| Master data | Add / remove the OPR, POC, Agent, Hotel, Airport and Port values used in the dropdowns (with "used by N"). Each value belongs to **one port or All ports**: admins choose when adding and can move it later; port users' values are for their port. Every dropdown offers only the item's port plus All-ports values |
| Exchange rates | Monthly USD → EGP rates (shared by every port, so only admins can change them) |
| History | **Admins only.** Every create / change / delete (vessels, services, bookings, guests, Master data, rates, user roles) with who, when, from which address and old → new; filter by date, what changed and user. Nobody can edit or delete it |

Each vessel also records its **arrival agent** (who entered it), its **sailing agent** (who sailed it) and its **port-call times** (arrived, berthed, ops started, ops finished, sailed – Cairo
time) with the time spent at berth / operating / in port. Operations may start before berthing (anchorage work); other
out-of-order times are rejected.

## What it does

| Area | Details |
|---|---|
| Vessels | Quick-add bar (with arrival agent), add / edit / delete, date range, search, ARK / MSK / Other filters, sorting, paging, status chip, CSV export. A vessel saved outside the range shows a notice with **Show it** |
| Port call | Arrival and sailing agents plus arrival, berthing, operations start / end and sailing times, with durations |
| Services | Crew Change, Delivery Parcels, Delivery Courier, Medical Treatment, Landing, Certificates, Fresh Water, Cash to Master, Others / Remarks. A vessel can have several of one type |
| Money | Cost / revenue / profit in EGP, live preview while typing, USD converted with the vessel's monthly rate or a per-service override |
| Cash to Master | Our revenue is a share **of** the amount (a percentage or a fixed figure), never on top of it; the remainder is "paid to master" and is not our cost |
| Crew | Pasted personal / flight text is parsed (rank, nationality, flights) |
| Reports | *Summary of services* per vessel (port call, services with counts, details, crew table, total profit, financial summary; printable), OPR summary, Dashboard |
| Excel | The Dashboard's management workbook; an **Excel** button on Hotels, Transport, Port closures, Garbage & Sludge and Calculations (every row the page's filters show, as a plain table for other programs) and **All data** (the five in one file for a From – To range) |
| Alerts | Bell + banner for vessels dated today or tomorrow |

### Roles

| Role | Sees | Can edit |
|---|---|---|
| admin | all ports | everything, including shared master data |
| readonly | all ports, money included (vessels, hotels, transport, Calculations) | only the accounting Open / Closed switch on Calculations (the read-only accounts are accounting) |
| alexandria / portsaid / damietta / suez | own port only | own port only (and that port's master-data values; exchange rates are admin-only) |

Port restrictions are enforced on the server for every request, not just hidden in the page.

## Security

Short version: role- and port-based access control on every request, CSRF protection, brute-force lock-out (also on the
admin login), API rate limits, 60-minute idle sessions, 12+ character passwords, `__Host-` cookies, strict
Content-Security-Policy with no third-party scripts, **two-step login (Authenticator codes) for everyone**, hash-locked dependencies, encrypted database connection, audit and
security logs, a tamper-proof change history, alerting, JSON errors with a reference, validated input and escaped output.

**Read `SECURITY.md`** for the answer to "is the data encrypted?", the OWASP Top 10 (2025) mapping, the known gaps (no
field-level encryption) and the deployment checklist.

## Tests

```bash
python manage.py test sheet         # 732 backend tests: maths, validation, permissions, CSRF, throttling, two-step login, agents, closures, LOG, receipt, Excel, edit conflicts...
pip install -r requirements-dev.txt # dev tools: ruff (with security rules), pip-audit, pip-tools
cd tools && npm install && npm run check   # every check and test in one go (ruff, ESLint, pip-audit, npm audit,
                                           # Django's production-settings check, backend and front-end tests)
```

**Dependencies** are locked: `requirements.in` lists the direct ones (with version ranges) and `requirements.txt` is
generated from it with exact versions and the hash of every published file (a test checks they agree). To update a
package, edit `requirements.in` if needed, then:

```bash
pip-compile --generate-hashes --strip-extras --upgrade-package <name> requirements.in -o requirements.txt
```

Optional front-end tests (need Node 18+):

```bash
cd tools && npm install
npm run test:parsing                                  # crew / flight parsers
DJANGO_DEBUG=1 python ../manage.py seed_demo --password "a-long-password" --two-step-key <32 base32 chars>  # then:
python ../manage.py runserver 8765
UI_TEST_PASSWORD="a-long-password" UI_TEST_TOTP_KEY=<same key> node ui_smoke_test.js alex   # also: viewer, admin
```

## Layout

```
config/                 settings and database setup (all environment-driven), urls
sheet/
  constants.py          ports, roles, service types
  models.py             Vessel, Service, ExchangeRate, Option, Profile, bookings, LoginAttempt, RateCounter,
                        ChangeRecord
  validators.py         cleaning of everything the browser sends
  finance.py            cost / revenue / profit maths
  access.py             who may see / change what
  serializers.py        model -> JSON
  api.py, errors.py     JSON endpoint plumbing, audit log
  listing.py            vessel list: date range, search, sorting, paging, totals, alerts
  dashboard.py          Dashboard: jobs per agent, services / money per month, OPR figures
  views.py              page, API, CSV
  xlsx.py, report.py    Excel writer (standard library only) and the management workbook
  dataexport.py         plain-table Excel files of five pages (Data export)
  throttle.py, signals.py   login failure counting and security logging
  ratelimit.py          API rate limits (writes, CSV export)
  alerts.py             alert record / e-mail when lock-outs, denials or errors pass a threshold
  history.py            change history (signals + request context), History API in views.py
  checks.py             deploy check: proxy without client-IP header
  middleware.py         login lock-out, CSP and other headers
  tests.py
  static/sheet/js/      front end as ES modules (main.js is the entry point)
tools/                  optional front-end tests
```
