# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Marine Service Sheet: a Django 5.2 app replacing an Excel sheet of vessels and the services done for them (crew change,
deliveries, cash to master…), with cost / revenue / profit in EGP. One Django app (`sheet`) plus a vanilla ES-module
front end with **no build step**. Users have a role: `admin`, `readonly` (sees all ports, edits nothing but the
accounting Open / Closed switch: the read-only accounts are the accountants), or a port
role (`alexandria`, `portsaid`, `damietta`, `suez`: sees and edits only that port). See `README.md` and `SECURITY.md`.

The project is a **git repository** (branch `main`; each feature on its own branch, merged only when the user agrees)
and runs on Windows. Designs and plans live in `docs/superpowers/`.

**Start here:** `docs/STATUS.md` says where things stand (unmerged branches, migrations the user's database still
needs), what was built, the **decisions the user made** (respect them), what may come next, the small issues the user
hasn't decided on, and how work has been done (Superpowers: brainstorm → design → plan → build test-first → fresh
review). Keep it up to date when you finish a piece of work.

`docs/DEPLOYMENT.md` is the user's step-by-step guide for the company server (Windows / IIS / NSSM, Linux notes),
the three PostgreSQL logins (`postgres`, `marine_app`, `marine_backup`; people never get one), creating everyone's
account in the admin pages, backups, and what happens on concurrent edits or a database outage. Update it when
settings, roles, account handling or deployment steps change.

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
cd tools && npm run check                                      # EVERYTHING: ruff, ESLint, pip-audit, npm audit,
                                                               # check --deploy, backend + parser + dom tests
```

`requirements.txt` is a **hash-locked** file generated from `requirements.in` (`pip-compile --generate-hashes
--strip-extras requirements.in -o requirements.txt`; install with `--require-hashes`); `tests_supply_chain` checks them.
Dev tools are in `requirements-dev.txt` (ruff with the security rules `S`, pip-audit, pip-tools) and `tools/package.json`
(ESLint 9, `tools/eslint.config.js`, run from the repo root). `npm run check` must stay green before a merge.

### Browser smoke test (`tools/ui_smoke_test.js`)

Loads the real page in jsdom, signs in over HTTP and clicks through every page; run it for `alex` (port user),
`admin` and `viewer`. Run it against a **throwaway database**, never the user's `db.sqlite3`:

```bash
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py migrate
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py seed_demo --password "<long password>" --two-step-key <KEY>
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py runserver 8765 --noreload   # background
cd tools && UI_TEST_PASSWORD="<long password>" UI_TEST_TOTP_KEY=<KEY> node ui_smoke_test.js alex    # then admin, viewer, suez
```

- `suez` is a short separate run (a port user outside Alexandria); the full script is written for alex / admin / viewer.
- `seed_demo` only sets passwords for users it creates; on a database that already has them, use a new database.
- A run that fails part-way leaves its test vessels behind and later runs then fail on them: start from a fresh
  database (or delete the leftovers) before trusting a result.
- `runserver --noreload` caches templates **and Python code**: restart it after editing `index.html` or any `.py`.
- The full `alex` run now writes more than 120 times: start the smoke server with
  `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`.
- The smoke test's writes count against the API rate limits (120 writes / 10 min per user, 600 per address): fine for
  one run of each role; many back-to-back runs on one server may need `DJANGO_RATE_LIMIT_*` raised.
- `seed_demo` gives MSC AURORA (Alexandria, today) a Crew Change with two on-signers (Ahmed Test needs a hotel, Ali
  Sayed lands 3 days early: the "Early arrival" alert; drafts made by `crewbookings.sync`) and a USD Fresh Water service at
  the month rate 50, and SEA BREEZE (Alexandria, yesterday) no times, a missing sailing agent and a Landing without agent (the
  "Missing details" alert); it also adds Delay / Closure reasons, a WEATHER closure in Alexandria (yesterday 06:00-14:00,
  "Strong wind") and an open FOG closure in Port Said; the smoke test relies on all of these.
- `<KEY>` is 32+ base32 characters (e.g. `python -c "import base64,secrets;print(base64.b32encode(secrets.token_bytes(20)).decode())"`):
  `seed_demo` gives every demo user a confirmed Authenticator with it and the smoke test computes the code. A code
  is accepted once per user per 30 seconds, so don't run the same role twice within 30 seconds.
- Assertions on anything async (search, date inputs, alerts, duplicate checks) must `waitFor`, not read immediately.

## Architecture

**One page, JSON API.** `views.index` renders `templates/sheet/index.html` once; the strict CSP (`middleware.py`,
`script-src 'self'`) forbids inline scripts, so page context goes to the browser through `json_script` tags and is read
in `static/sheet/js/config.js`. Everything else is fetched from `/api/...` (routes in `sheet/urls.py`).

**Every API view** is wrapped in `api.json_api` (auth check, `request.profile`, rate limit via `ratelimit.check`,
**one `transaction.atomic` per write**, maps `errors.ApiError` subclasses to JSON errors, logs 403s, turns any other
exception into `{"error", "ref"}` 500 with the ref in the `sheet.security` log) and must get vessels through
`access.scoped_vessels(profile, port)`, which pins port users to their own port whatever `port` they send. Writes call
`access.require_edit` / `require_admin` (exchange rates are shared by all ports, so admin-only). Changes are recorded
with `api.audit(...)`; values go through `api.log_safe`. `handler404` / `handler500` (`views.not_found` /
`server_error`) answer JSON under `/api/`, plain pages elsewhere.

**Security plumbing:** `ratelimit.py` (writes per user / address, CSV per user, counted in `RateCounter`; a broken
counter refuses writes, allows reads), `alerts.note(kind)` (threshold → one `sheet.alert` record + `mail_admins`),
`checks.py` (deploy check `sheet.E001`). **Change history** (`history.py`): model signals on Vessel, Service,
HotelStay, Transfer, Guest, Option, ExchangeRate, PortClosure, Profile and auth `User` (no password hash, no last_login) write a `ChangeRecord` (who / when / IP / old → new) in the
same transaction; `bulk_create` sends no signals, so callers use `history.record_created`. The request comes from
`HistoryMiddleware` (none → "system"). Append-only (read-only admin; PostgreSQL trigger in migration 0010).
`GET /api/history/` is admin-only; the History page is `js/pages/history.js`, rendered in the template for admins only.

**Two-step login** (`twostep.py`, `views_twostep.py`, django-otp's `TOTPDevice`, `RememberedComputer`): after the
password, `TwoStepMiddleware` sends a signed-in person to the step they are on (`twostep.next_step`: code →
forced password change → setup / blocked) and lets nothing else through (API 401, admin pages redirected). The passed
state is `session["two_step"] = {"how": "code" | "remembered" | "exempt", "ref": id}`, re-checked every request,
cleared on every password sign-in. Profile has `two_step_exempt` (never admin / superuser / staff),
`must_change_password` (set when someone else sets the password, via `history.current_request()`), `setup_until`
(72-hour window). History tracks devices and remembered computers without the key / token hash. Tests sign in with
`tests.pass_two_step(client, username)` after `client.login`; the real code path is in `tests_twostep`.

**Input** is cleaned only in `validators.py` (whitelisted keys, length limits, typed numbers) and **refused, never
silently fixed**: too-long text (`_short`), non-numbers and negative amounts (`_amount`; amounts are never negative,
the user's decision), exchange rates <= 0 (`_rate`), percentages outside 0-100. OPR / POC / agents and booking
hotel / airport / port must be in Master data for the vessel's port or All ports (`listed`, `check_booking_lists`);
the value already saved on the record stays allowed. Tests add list values with `tests.allow(kind, *values)`;
pasted crew-change details are still trimmed. Services store their
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
the alerts (today / tomorrow in Cairo time, and past vessels missing details) and the CSV export.

**Dashboard** (`dashboard.py`, `GET /api/dashboard/` and `/api/dashboard/jobs/`): vessels in date range + port (+ exact
OPR) → jobs (arrival = 1 for the arrival agent, sailing = 1 for the sailing agent, each service = 1 for its agent; a
Crew Change is 1 job), services and money (`calc` of each service, services only, no bookings) per vessel-date month
with zero-filled gaps, and the OPR charts / cards. `agent=__none__` (`constants.NO_AGENT`) means an empty agent; a
service filter drops arrivals / sailings; agent or service filters narrow the OPR figures to the counted services.
Its OPR / agent / service filters are `state.dashboardFilter` (not the vessel list's); From–To and port are shared.

**Hotels and Transport** (`logistics.py`): `HotelStay` (one room; cost and revenue per room per night) and
`Transfer` (one car trip between an airport, a hotel and a port, naming which one of each from Master data) each have
1–6 `Guest` rows (one table; a check constraint ties each guest to exactly one booking). Guests are copies of crew-change members taken at booking time, so editing a crew change never changes a
booking. Bookings are scoped through `vessel` like everything else. Each booking has cost (what we pay) and revenue
(what we get) — per room per night for hotels — visible to every role; `logistics.booking_line` turns it into a money
line. Booking money counts on the Calculations page only and is not part of `finance.compute` or any vessel
figure. `crew_of(vessel)` feeds the dialog's crew picker (on-signers use their last flight leg, off-signers their
first). The two pages are one module configured twice (`js/pages/bookings.js`) plus the dialog (`js/modals/booking.js`).

**Automatic crew bookings** (`crewbookings.py`): every crew member has a stable `uid` (12 hex, made by
`validators._clean_crew_change`), `needsHotel`, and on-signers a `brokenVisa` cost / revenue (a money line of the Crew
Change in `finance`). After every Crew Change write, `crewbookings.sync(vessel)` gives each member a **draft** transfer
(on: airport → port at landing; off: port → airport at take-off; else the vessel date 00:00) and, while Needs hotel is
on, a draft hotel stay (hotel "", 1 night). Drafts (`draft=True`) are linked by `Guest.crew_uid`, follow their member
while they hold that one guest, and are deleted when the member goes away; a booking saved in the dialog becomes
`draft=False` and is never touched again (the dialog keeps `crew_uid`). The alerts add `early` (on-signers landing 2+
days before the vessel date, 60-day look-back, cleared by any broken-visa amount incl. 0) and, in `missing`,
`Hotel: …` / `Transport: …` for incomplete bookings (draft or no cost / revenue) of vessels that have **sailed**
(sailing time passed, or none and dated before today). `crewbookings` imports `logistics`, which imports `listing`, so
`listing` imports `crewbookings` inside its functions.

**LOG letter** (`logpdf.py`, `GET /api/services/<id>/log/<uid>/`, `views.service_log`): the on-signer's "Invitation
letter for boarding" as a PDF written with the **standard library only** (the user refused any PDF library): built-in
fonts with WinAnsi (`to_winansi`: Ş → S, Cyrillic → ?), JPEGs placed raw (`/DCTDecode`, only the header is read), every
value a plain escaped PDF string, never `{{ }}`. Edit roles only (`require_edit`, scoped, Crew Change on-signers), rate
limited like the CSV export, recorded in the History (action `letter`). The logo / stamp / footer JPEGs come from
`DJANGO_LETTERHEAD_DIR` (`logo.jpg`, `stamp.jpg`, `footer.jpg`) — **never in git (the GitHub repo is public) and never
under `static/`**; missing → the letter has no pictures. Its layout: bold "Flight:" above the flights on page 1, the
personal details on page 2 under a bold "Personal details:" with the stamp beside them.

**Master receipt** (`logpdf.build_receipt`, `receipt.py`, `GET/POST /api/services/<id>/receipt/`,
`views.service_receipt`, dialog `js/modals/receipt.js`): a "WHOM IT MAY CONCERN" paper the vessel's master signs and
stamps by hand, after the user's "name of port.docx". A Receipt button on every service card (edit roles) opens a form
pre-filled by GET (port label, today in Cairo, vessel, one line: the service type — Others / Remarks: its note's first
line — plus its **revenue written as "cost"** in its own currency, `$120` / `EGP 3,000`: the revenue side of `finance.service_lines`, so entries,
Cash to Master's share and broken-visa charges count, summed per currency;
no revenue → the label only); POST with the edited text (`validators.clean_receipt`: services required, 2000 characters,
40 lines) returns the PDF: logo and footer, **no stamp**, no separate revenue line. Nothing typed is stored; the
History records action `receipt` (migration 0017 widened `ChangeRecord.action` to 7). Scoped, `require_edit`, rate
limited with the exports. The LOG and the receipt download through `api.download()`.

**Management Excel** (`xlsx.py`, `report.py`, `GET /api/dashboard/export/?from=&to=&port=`, `views.dashboard_export`, the Dashboard's **Excel** button `data-act="dashboard-export"`): a `.xlsx` written with the **standard library only** (`zipfile` + escaped XML; text cells are always inline strings, never formulas; native DrawingML charts). `report.data(profile, Range, now)` builds ten sheets of tables (`{"head", "rows", "total"}`); money comes **only** from `calculations.rows_for` (so it equals the Calculations page, hotels / transport / garbage included), job counts from `dashboard.response`; `report.workbook` lays them out (title, range line, tables, notes, one chart; a sheet whose figures are all zero shows "No data"). From and To required, at most 24 months; every role, port users pinned to their port; rate limited with the exports; audit `dashboard.export`. `crewbookings.early_on_signers(service)` counts every early on-signer (visa charged or not).

**Data export** (`dataexport.py`, `GET /api/export/<page>/?<that page's list query>` with page `hotels` / `transfers` /
`closures` / `disposal` / `calculations`, and `GET /api/export/all/?from=&to=&port=`; `views.data_export` /
`data_export_all`; buttons `data-act="page-export" data-page=…` on each page and `dashboard-data-export` beside the
Dashboard's Excel): plain tables for other programs — one fixed header row, one row per record, numbers as numbers,
`xlsx.Day` / `xlsx.Moment` real Excel dates (Cairo time), no titles / totals / notes. Each sheet takes its page's own
unpaged rows (`logistics.filtered`, `closures.filtered`, `calculations.filtered`, `disposal.response`), so filters and
port scoping are the page's; the page modules' `exportQuery()` is their list query without `page` / `page_size`. All
data: the five sheets, From–To required (at most 24 months, `views._export_range`, shared with the management Excel),
each page reading the range its own way. Every role; rate limited with the exports; audit `data.export`.

**Edit conflicts** (`conflicts.py`, migration 0018, `js/conflict.js`): Vessel, Service, HotelStay, Transfer and PortClosure have `version`. Every update of those (vessel / service PUT-PATCH, booking / closure PUT) must send it (missing → 400 "This page is out of date…"); `conflicts.locked` re-reads the row with `select_for_update`, a different version → **409** `{"error": "conflict", "conflict": {who, same_person, at, fields, version}}` and nothing saved (who / fields from the History records whose version rose). `bump_if_changed` raises it **before** the save, only when the values (compared with `==`; booking guests in any order) really differ; automatic writes (`crewbookings.sync`, sailing-day rule) never touch it. Admin-page saves raise it (`admin.VersionedAdmin`; read-only there). The History page hides `version`. Front end: `api()` errors carry `.status` / `.data`; `mutate(action, onConflict)` sends a 409 to `showConflict` (panel `#conflict-panel`, `data-act` `conflict-reload` / `conflict-force`); each dialog keeps the version it opened with. Tests: `ApiTestCase.call` adds the current version to such updates itself; the real check is in `tests_conflicts_api` (raw requests).

**Vessel date = sailing day:** once `sailing_at` is set, `clean_vessel` sets `date` to its Cairo date (migration 0014
did the same for existing vessels); the form shows the date read-only.

**Garbage & Sludge** (`disposal.py`; page `js/pages/disposal.js`, `GET /api/disposal/`, `PUT /api/disposal/<vessel>/`;
prices `GET/POST /api/disposal-prices/`, `DELETE /api/disposal-prices/<id>/`, admin-only writes, port users read
their port's): `DisposalPrice` per month and port has four blocks (garbage / sludge × revenue / cost), each a minimum
quantity, a minimum amount in its currency and an extra per m³ / t above it (`block_amount`). `VesselDisposal` (one
per vessel: garbage m³, sludge t, `hidden`; hiding clears the quantities) is typed on the page, which shows EGP and
USD (a figure needing a missing rate is None, the row flagged). The money is on that page and on Calculations
(`calculation_lines`, finance format, USD 1:1 when no rate) only, never in the vessel figures. It replaced the
"Garbage & Sludge" service (migration 0016 deleted that test data). The price form's Copy from last month is front end.

**Calculations** (`calculations.py`, `GET /api/calculations/`): vessels in a vessel-date range / exact OPR / port →
`service_lines` for each service plus `booking_line` for each hotel stay and transfer → rows, totals over all
filtered rows, and the OPRs present in the range for the page's dropdown. Computed on each request, never stored.
Every role may read it. Each row carries `status` / `cancel_reason` (service rows; None for bookings and garbage),
`closed` and `ref {kind, id}` (what `/api/accounting/` closes; None for garbage with no `VesselDisposal` yet).
`status=` / `accounting=` comma lists filter the rows (unknown → 400, empty items ignored; any `status` filter drops
rows without a status); totals follow the filters and add `open` / `closed`.

**Service status** (migration 0019): `Service.status` (`in_progress` default / `completed` / `cancelled`,
`constants.SERVICE_STATUSES`) and `cancel_reason` (`validators.clean_service_status`: required when Cancelled, refused
otherwise, 500 characters; a save without the key keeps the stored value). Existing services became Completed. A
cancelled service is skipped by `crewbookings.crew_members` (its drafts go, and come back if un-cancelled),
`early_arrivals` and `listing.missing_details`; its money lines stay (the dialog sets the money to 0 on choosing
Cancelled). **Accounting** (`accounting.py`, `POST /api/accounting/ {kind: service|hotel|transfer|disposal, id,
closed}`, `access.require_accounting`: admin or role `readonly`; only a thing with a line on Calculations, i.e. some
money, can be closed: `accounting.NO_MONEY`): `acct_closed` on Service, HotelStay, Transfer and
VesselDisposal, never written by operations saves (`conflicts.UNTRACKED`); the flag alone never raises `version`
(writing a kept rate on closing does, below). Closed =
locked for every role: `accounting.require_open` on service PUT / DELETE, booking PUT / DELETE and the disposal PUT,
`require_vessel_open` on vessel DELETE (message `accounting.LOCKED`); `crewbookings.sync` leaves closed bookings
alone. Dashboard `response()["status"]` (`dashboard.status_counts`: services per status, Calculations rows Open /
Closed per month; under agent / service filters only the counted services' rows) and the Excel sheet
"Service status" (`report._service_status`).

**Cancelled bookings and kept rates** (migration 0020): HotelStay / Transfer have `cancelled` (dialog tick that sets
the money to 0, a fee can be typed; a PUT without the key keeps it): no missing-details alert, status `cancelled` on
its Calculations line. `GET /api/services/<id>/bookings/` (`crewbookings.saved_bookings` / `booking_ref`) lists a Crew
Change's saved (non-draft) bookings, those with a guest whose `crew_uid` is one of its crew; the service PUT may send
`cancel_bookings: [{kind: hotel|transfer, id}]` (`validators.clean_booking_refs`, `crewbookings.cancel_bookings`: only
when the saved status is Cancelled, only its own bookings, none closed; each gets cancelled, money 0, version +1).
**Closing needs a rate** (`accounting._lines`: `NEEDS_PRICE` / `NEEDS_RATE` when a row is `price_missing` /
`rate_missing`) and **keeps it** (`accounting._keep_numbers`): a line that used the month rate gets it written as the
service's `data.exchangeRate` or the booking's `exchange_rate` (version +1, like a typed change); garbage & sludge gets
`VesselDisposal.exchange_rate` and `frozen_price` (the month's price dict), used by `disposal.kept` on the page and on
Calculations. Reopening keeps them; only a person changes them.

**Agents:** `Vessel.arrival_agent` (who entered it), `Vessel.sailing_agent` (who sailed it) and `Service.agent` (who
did that service), all plain text from the Agent list, empty until chosen. `listing.missing_details` feeds the
"Missing details" alert (key `missing`): vessels dated before today (Cairo) missing any of the five times, a needed
delay reason, or any agent (every service type needs one).

**Delay reason:** `Vessel.delay_reason` (Master data "Delay reason" list) is required when berthing is more than 2
hours after arrival (`constants.is_delayed`, exactly 2:00 is not delayed) and refused otherwise
(`validators.clean_delay_reason`; a PUT without the key keeps the stored reason). The vessel form shows it while the
times say delayed or a reason is set (`util.isDelayed`).

**Port closures** (`closures.py`, `GET/POST /api/closures/`, `PUT/DELETE /api/closures/<id>/`): `PortClosure` (port,
closed from, reopened or empty = still closed, reason from the "Closure reason" list, notes), not linked to vessels.
Scoped by its own port with `access.scoped_closures`; the list shows closures overlapping a date range. Page
`js/pages/closures.js`, dialog `js/modals/closure.js`.

**Master data** (`Option`: kind, value, `port`): eight lists (OPR, POC, Agent, Hotel, Airport, Port, Delay reason,
Closure reason). `port` is `""`
for All ports or one port key. Port users only ever create values for their port and see All-ports + their own;
admins choose the port when adding and move values with `PATCH /api/options/<id>/` (admin only). Every dropdown is
built with `optionChoices(kind, current, port)` → only that port's + All-ports values, always keeping `current`.

**Front end** (`static/sheet/js/`, entry `main.js`):
- `state.js` holds one `state.filter` (from, to, q, bucket, port, sort, dir, page, pageSize), the current page of
  vessels and a cache by id (`getVessel`); `data.js` loads from the server (`setFilter`, `loadVessels`,
  `refreshAfterChange`, `ensureVessel`), dropping out-of-order responses with a request counter.
- Every button carries `data-act="name"`; `actions.js` maps names to handlers and `main.js` has one document click
  listener that dispatches them.
- **Screens are built only with `dom.js`** (`h(tag, props, ...children)`, `setChildren`, `optionEls`): dynamic values
  go in as text or as allow-listed attributes / properties; `h()` throws on anything else. **Never** use `innerHTML`,
  `outerHTML`, `insertAdjacentHTML`, `document.write`, `DOMParser`, inline `style=` or `eval` / `new Function`: ESLint
  bans them, the CSP (`require-trusted-types-for 'script'`, `style-src-attr 'none'`) makes the browser refuse them,
  and `sheet/tests_frontend_safety.py` checks the files. Hide/show template elements with the `hidden` attribute.
  No Trusted Types policy may be created (`trusted-types 'none'`); there is no PDF reader any more (removed for
  security; crew are added with + Add and pasted text).
- **Icons** are one inline SVG sprite, `templates/sheet/icons.svg`, included once per page; templates use
  `<svg class="ic" aria-hidden="true"><use href="#i-NAME"></use></svg>` and JS uses `dom.js` `icon(name)`, which only
  accepts names in `ICONS` (kept equal to the sprite by `tests_look`). No emoji or dingbat anywhere in templates / JS
  (`tests_look`); the plain → arrow is allowed as text.
- **Theme:** colours exist only as tokens at the top of `app.css` (light `:root`, dark under `prefers-color-scheme`
  and `[data-theme="dark"]`, light again for print); everything else uses `var(--…)` (JS charts use `--c1`…`--c8`).
  The navy sidebar uses `--side-*`; cards (`.table-wrap`, `.panel`, `.svc-card`, `.modal`, `.login-card`) have 10 px
  corners and `--card-shadow` (none in dark mode). The old grey look is on branch `backup/look-2026-11-18`.
- **Brand:** "ARKAS" / "EGYPT HUSBANDRY". The logo is `brand.png` in `DJANGO_LETTERHEAD_DIR` (never in git or `static/`),
  served by `GET /brand/logo.png` (`branding.py`, `views.brand_logo`; PNG only, 500 KB max, open without sign-in and
  during two-step); the context processor `brand` gives templates `brand_logo`, and without it they show the anchor.
  Sign-in / locked / error pages share `templates/sheet/brand_login.html`.
  The sidebar switch (`js/theme.js`) sets `data-theme`, a `theme` cookie and localStorage; the context processor
  `sheet.context_processors.theme` renders `data-theme` from a whitelisted cookie. System font, no web fonts.
- **Script loading:** `views.script_modules()` lists every file under `static/sheet/js/` and `index.html` names them
  as `<link rel="modulepreload">` before `main.js`, so the browser fetches all modules at once instead of in 4
  import rounds (`tests_speed`). New files are picked up automatically.
- `crewParsing.js` and `util.limitRows` are pure and unit-tested in `tools/parsing_test.js`. (Bulk add was removed
  on 2026-11-18: vessels are added with the quick-add bar and the vessel form.)

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
- `README.md` and `SECURITY.md` both state the backend test count; update them when it changes.
