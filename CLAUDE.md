# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Marine Service Sheet: a Django 5.2 app replacing an Excel sheet of vessels and the services done for them (crew change,
deliveries, cash to master…), with cost / revenue / profit in EGP. One Django app (`sheet`) plus a vanilla ES-module
front end with **no build step**. Users have a role: `admin`, `readonly` (sees all ports, edits nothing), or a port
role (`alexandria`, `portsaid`, `damietta`, `suez`: sees and edits only that port). See `README.md` and `SECURITY.md`.

The project is a **git repository** (branch `main`; each feature on its own branch, merged only when the user agrees)
and runs on Windows. Designs and plans live in `docs/superpowers/`.

**Start here:** `docs/STATUS.md` says where things stand (unmerged branches, migrations the user's database still
needs), what was built, the **decisions the user made** (respect them), what may come next, the small issues the user
hasn't decided on, and how work has been done (Superpowers: brainstorm → design → plan → build test-first → fresh
review). Keep it up to date when you finish a piece of work.

## Commands

Use the project venv (`venv\Scripts\activate`, or call `venv/Scripts/python.exe` directly).

**Debug mode is off unless `DJANGO_DEBUG=1` is set** (fail-closed: without it the app refuses to start because it has
no secret key). `manage.py runserver` and `manage.py test` set it themselves (`manage.py`); every other command
(`migrate`, `makemigrations`, `seed_demo`, `createsuperuser`, `check`) needs it in the environment.

```bash
python manage.py test sheet                                    # all backend tests
python manage.py test sheet.tests_listing.ListingTests         # one class
python manage.py test sheet.tests.AccessTests.test_read_only_user_can_read_but_not_write   # one test
DJANGO_DEBUG=1 python manage.py makemigrations sheet
cd tools && npm run test:parsing                               # front-end parser unit tests (Node, esbuild)
```

`ruff` is configured in `pyproject.toml` (line length 120) but is not installed in the venv.

### Browser smoke test (`tools/ui_smoke_test.js`)

Loads the real page in jsdom, signs in over HTTP and clicks through every page; run it for `alex` (port user),
`admin` and `viewer`. Run it against a **throwaway database**, never the user's `db.sqlite3`:

```bash
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py migrate
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py seed_demo --password "<long password>"
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py runserver 8765 --noreload   # background
cd tools && UI_TEST_PASSWORD="<long password>" node ui_smoke_test.js alex    # then admin, viewer, suez
```

- `suez` is a short separate run (a port user outside Alexandria); the full script is written for alex / admin / viewer.
- `seed_demo` only sets passwords for users it creates; on a database that already has them, use a new database.
- A run that fails part-way leaves its test vessels behind and later runs then fail on them: start from a fresh
  database (or delete the leftovers) before trusting a result.
- `runserver --noreload` caches templates **and Python code**: restart it after editing `index.html` or any `.py`.
- `seed_demo` gives MSC AURORA (Alexandria, today) a Crew Change with two on-signers and a USD Fresh Water service at
  the month rate 50; the smoke test relies on both.
- Assertions on anything async (search, date inputs, alerts, duplicate checks) must `waitFor`, not read immediately.

## Architecture

**One page, JSON API.** `views.index` renders `templates/sheet/index.html` once; the strict CSP (`middleware.py`,
`script-src 'self'`) forbids inline scripts, so page context goes to the browser through `json_script` tags and is read
in `static/sheet/js/config.js`. Everything else is fetched from `/api/...` (routes in `sheet/urls.py`).

**Every API view** is wrapped in `api.json_api` (auth check, `request.profile`, maps `errors.ApiError` subclasses to
JSON errors, logs 403s) and must get vessels through `access.scoped_vessels(profile, port)`, which pins port users to
their own port whatever `port` they send. Writes call `access.require_edit` / `require_admin` (exchange rates are
shared by all ports, so admin-only). Changes are recorded with `api.audit(...)`; values go through `api.log_safe`.

**Input** is cleaned only in `validators.py` (whitelisted keys, length limits, typed numbers). Services store their
details as JSON in `Service.data`, whose shape per type is defined by `clean_service_data`.

**Money** is worked out only in `finance.py`: `service_lines` gives each service's money lines with their working
(every service, Crew Change and Others / Remarks included, has cost and revenue) and `finance.compute` adds them up
for the vessel figures. USD is converted with the item's own rate, else the vessel's month rate (`ExchangeRate`), else
1:1 and flagged `rate_missing`. Every amount is rounded to the cent once, in `finance.money`, so lines always add up
to totals. It cannot be summed in SQL. `serializers.vessel_to_dict` attaches the figures. The front end mirrors the
maths for the live preview (`js/calc.js`, same rounding), but the server's numbers are the truth.

**Vessel list** (`listing.py`): the database narrows by date range and port; every vessel in that range gets its
figures computed once; then search (literal, case-insensitive), OPR bucket (ARK / MSK / other / with services), exact
OPR, sorting (ties by newest id) and paging run in Python. `totals` cover range + port only. The same module serves
the alerts (today / tomorrow in Cairo time), the Dashboard, the bulk-add duplicate check and the CSV export.

**Hotels and Transport** (`logistics.py`): `HotelStay` (one room; cost and revenue per room per night) and
`Transfer` (one car trip between an airport, a hotel and a port, naming which one of each from Master data) each have
1–6 `Guest` rows (one table; a check constraint ties each guest to exactly one booking). Guests are copies of crew-change members taken at booking time, so editing a crew change never changes a
booking. Bookings are scoped through `vessel` like everything else. Each booking has cost (what we pay) and revenue
(what we get) — per room per night for hotels — visible to every role; `logistics.booking_line` turns it into a money
line. Booking money counts on the Calculations page only and is not part of `finance.compute` or any vessel
figure. `crew_of(vessel)` feeds the dialog's crew picker (on-signers use their last flight leg, off-signers their
first). The two pages are one module configured twice (`js/pages/bookings.js`) plus the dialog (`js/modals/booking.js`).

**Calculations** (`calculations.py`, `GET /api/calculations/`): vessels in a vessel-date range / exact OPR / port →
`service_lines` for each service plus `booking_line` for each hotel stay and transfer → rows, totals over all
filtered rows, and the OPRs present in the range for the page's dropdown. Computed on each request, never stored.
Every role may read it.

**Front end** (`static/sheet/js/`, entry `main.js`):
- `state.js` holds one `state.filter` (from, to, q, bucket, port, sort, dir, page, pageSize), the current page of
  vessels and a cache by id (`getVessel`); `data.js` loads from the server (`setFilter`, `loadVessels`,
  `refreshAfterChange`, `ensureVessel`), dropping out-of-order responses with a request counter.
- Every button carries `data-act="name"`; `actions.js` maps names to handlers and `main.js` has one document click
  listener that dispatches them.
- Rendering builds HTML strings: every dynamic value must go through `util.esc()`.
- `bulkParsing.js` (`parseBulk`, `checkRows`) and `crewParsing.js` are pure and unit-tested in `tools/parsing_test.js`.

**Dev server caching:** `sheet/management/commands/runserver.py` overrides `runserver` to send static files with
`Cache-Control: no-cache`, because the browser otherwise mixes old and new ES modules after an update. It only wins
because `sheet` is listed before `django.contrib.staticfiles` in `INSTALLED_APPS`.

## Conventions and gotchas

- Files use **LF** line endings. On Windows, Python's `Path.write_text` turns `\n` into CRLF: write with
  `write_bytes(text.encode("utf-8"))` or `newline=""`.
- Shell heredocs containing backslash escapes, `$$(` or complex quoting can be mangled or refused by the shell safety
  check; put such scripts in a file (or use the Edit tool) instead. Windows occasionally refuses a file write
  ("Invalid argument"): check the file is intact, then retry the change.
- Hand-write migrations that rename fields (`RenameField` + a data step); `makemigrations` would drop and re-add the
  column and lose data. Check with `makemigrations --check --dry-run`.
- Production requires PostgreSQL and `DJANGO_SECRET_KEY` (`config/settings.py`, `config/database.py`); SQLite is
  development only. The admin URL can be moved with `DJANGO_ADMIN_URL`.
- Keep `BULK_MAX_ROWS` (`constants.py`) and `MAX_ROWS` (`pages/bulk.js`) in step.
- `README.md` and `SECURITY.md` both state the backend test count; update them when it changes.
