# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Marine Service Sheet: a Django 5.2 app replacing an Excel sheet of vessels and the services done for them (crew change,
deliveries, cash to master…), with cost / revenue / profit in EGP. Two Django apps (`sheet`, and `operation` for every
vessel at every terminal, see **Operation**) plus a vanilla ES-module
front end with **no build step**. **Admins are the superusers** (made with `createsuperuser`, never by the app): every
port, accounts, ports, rates, the History, accounting. Everyone else is a **User** with a home port and extra ports
(`Profile.home_port` / `ports`); no port → blocked ("no port yet"). The Read-only role is gone (migration 0024).
In their ports a User does only what their **19 permissions** allow and sees only their **pages**
(`Profile.permissions` / `pages`, piece 2 of the access rework, `specs/2026-11-24-access-rework-design.md`); piece 3
(`money.edit` hides the forms' money, `money.view` the overviews) is `moneyaccess.py` (see **Money permissions**).
See `README.md` and `SECURITY.md`.

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
python manage.py test sheet operation                          # all backend tests
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
`admin`, `viewer` (a User of Alexandria, Port Said and Damietta), `suez` and `marine`. Run it against a **throwaway database**, never
the user's `db.sqlite3`:

```bash
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py migrate
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py seed_demo --password "<long password>" --two-step-key <KEY>
DJANGO_DEBUG=1 DJANGO_DB_PATH=<scratch>/fresh.sqlite3 python manage.py runserver 8765 --noreload   # background
cd tools && UI_TEST_PASSWORD="<long password>" UI_TEST_TOTP_KEY=<KEY> node ui_smoke_test.js alex    # then admin, viewer, suez
```

- `suez` (a port user outside Alexandria) and `viewer` (the three-port User: port choices, a Damietta vessel, no Suez,
  no Open / Closed buttons) are short separate runs; the full script is written for alex / admin. The admin run also
  adds a `Smoke…` port on the Ports page and a `Smoke…` terminal on the Terminals page each time (neither is ever
  deleted). Both walk the Operation pages; alex also adds, completes and deletes a visit.
- `marine` (Alexandria, Marine template: Vessels + Services, no delete / cancel / exports; money in forms but no
  totals: `money.edit` without `money.view`) is a short separate run too.
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
  "Missing details" alert); customers Blue Owners (USD rates: Fresh Water 50, Crew Change 300) and Red Managers,
  ships MSC AURORA 9074729 MSK / ARKAS STAR / NORTHERN LIGHT / SEA BREEZE, each demo vessel linked to its ship;
  it also adds Delay / Closure reasons, a WEATHER closure in Alexandria (yesterday 06:00-14:00,
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
`access.scoped_vessels(profile, port)` (`port__in` the User's ports; `port` narrows only when it is one of theirs,
`access.asked_port`, so asking never widens). `access.ports_of(profile)` is None for Admins, else the User's keys;
every record written into a port goes through `access.require_port(profile, key, new=...)` (403 for a port that isn't
theirs, 400 "That port is turned off." for a new record in a turned-off one; `validators._record_port` for vessels and
closures: sent port, else saved, else the User's home port). Writes call `access.require(profile, key)` (a
permission) / `require_admin` (exchange rates, prices, moving Master data, deleting ships / customers); page-only
routes call `access.require_page(profile, page)` (see **Permissions and pages**). Changes are recorded
with `api.audit(...)`; values go through `api.log_safe`. `handler404` / `handler500` (`views.not_found` /
`server_error`) answer JSON under `/api/`, plain pages elsewhere.

**Security plumbing:** `ratelimit.py` (writes per user / address, exports per user, counted in `RateCounter`; a broken
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
details as JSON in `Service.data`, whose shape per type is defined by `clean_service_data`. A type's own detail
fields (not money) are listed once in **`constants.SERVICE_FIELDS`** (`{type: {fields: [{key, label, kind, max?,
choices?}], label, suffix, cost_label?, cost_currency?}}`, kinds text / number / date / datetime / choice):
`validators._clean_details` cleans them (refused, never fixed), `finance._single_label` names the money line from the
`label` field ("Fresh Water · 5 t"), and the page sends the table as `service-fields-data` (`config.SERVICE_FIELDS`,
`serviceDetails`) for the service form, card and Summary. The agreed "unit" rate multiplies the field `quantity`.
Types (2026-11-25, from the manager's HTML): Suez Canal Transit (cost labelled SCA charges, USD), Surveyors
Attendance, Supply, SIM Cards (per card), Tourism Tours; Cash to Master (= the HTML's CTM) has Reference /
Beneficiary. Parcels (piece 2): Delivery Parcels / Landing have Transfer type (Vessel-to-Vessel / Vessel-to-Courier),
Receiving vessel (free text) and Courier, each shown only for its choice (field `when` [key, value]; sent under
another choice → refused), and Courier payment; Delivery Courier has Courier, Delivery status and Courier payment.
A new type needs a chart colour (`--c1`… in `app.css`, `CHART_COLORS`; `tests_look`).

**Money** is worked out only in `finance.py`: `service_lines` gives each service's money lines with their working
(every service, Crew Change and Others / Remarks included, has cost and revenue) and `finance.compute` adds them up
for the vessel figures. USD is converted with the item's own rate, else the vessel's month rate (`ExchangeRate`), else
1:1 and flagged `rate_missing`. Every amount is rounded to the cent once, in `finance.money`, so lines always add up
to totals. It cannot be summed in SQL. `serializers.vessel_to_dict` attaches the figures. The front end mirrors the
maths for the live preview (`js/calc.js`, same rounding), but the server's numbers are the truth.

**Vessel list** (`listing.py`): the database narrows by date range and port; every vessel in that range gets its
figures computed once; then search (literal, case-insensitive), OPR bucket (ARK / MSK / other / with services), exact
OPR, sorting (ties by newest id) and paging run in Python. `totals` cover range + port only. The same module serves
the alerts (today / tomorrow in Cairo time, and past vessels missing details) and the Vessels Excel.

**Dashboard** (`dashboard.py`, `GET /api/dashboard/` and `/api/dashboard/jobs/`): vessels in date range + port (+ exact
OPR) → jobs (arrival = 1 for the arrival agent, sailing = 1 for the sailing agent, each service = 1 for its agent; a
Crew Change is 1 job), services and money (`calc` of each service, services only, no bookings) per vessel-date month
with zero-filled gaps, and the OPR charts / cards. `agent=__none__` (`constants.NO_AGENT`) means an empty agent; a
service filter drops arrivals / sailings; agent or service filters narrow the OPR figures to the counted services.
Its OPR / agent / service filters are `state.dashboardFilter` (not the vessel list's); From–To and port are shared.
`customers` (`_customers`, counts only): jobs per customer (a service's `billing_party`, else the ship's customer;
arrivals / sailings the ship's; none → id None "No customer", last) with `places` per POC + port. The page shows
one view at a time (`data-dash-view` agents / opr / customers / overview, tabs `data-act="dash-view"`,
`showDashboardView`, remembered in `localStorage` `sheet.dashboard.view`); every view is drawn from the same
response; a filter the view doesn't use is hidden while empty. The OPR donut is `js/render/svgChart.js` (SVG by
`createElementNS`, colours through CSSOM).

**Hotels and Transport** (`logistics.py`): `HotelStay` (one room; cost and revenue per room per night) and
`Transfer` (one car trip between an airport, a hotel and a port, naming which one of each from Master data) each have
1–6 `Guest` rows (one table; a check constraint ties each guest to exactly one booking). Guests are copies of crew-change members taken at booking time, so editing a crew change never changes a
booking. Bookings are scoped through `vessel` like everything else. Each booking has cost (what we pay) and revenue
(what we get) — per room per night for hotels — visible to every role; `logistics.booking_line` turns it into a money
line. Booking money counts on the Calculations page only and is not part of `finance.compute` or any vessel
figure. `crew_of(vessel)` feeds the dialog's crew picker (on-signers use their last flight leg, off-signers their
first). The two pages are one module configured twice (`js/pages/bookings.js`) plus the dialog (`js/modals/booking.js`).

**Automatic crew bookings** (`crewbookings.py`): every crew member has a stable `uid` (12 hex, made by
`validators._clean_crew_change`), the crew card's **Hotel** / **Transport** buttons (`needsHotel`, `needsTransport`)
with what was typed under them (`hotel {name, checkIn, checkOut}`, `transport {from, fromName, to, toName, at}`, all
strings, "" = automatic; names checked against the port's Master data by `validators.check_crew_lists`, the member's
saved name allowed), and on-signers a `brokenVisa` cost / revenue (a money line of the Crew Change in `finance`).
After every Crew Change write, `crewbookings.sync(vessel)` gives each member, **only while its button is pressed**, a
**draft** transfer (typed values, else on: airport → port at landing; off: port → airport at take-off; else the
vessel date 00:00) and a draft hotel stay (typed hotel / dates, else the landing day or vessel date, 1 night).
Transport became opt-in in migration 0027, which pressed it for every member that already had a transfer. The
dialog's boxes start from `js/crewBookings.js` (twin of `_when` / `parse_flight_time`, `parsing_test.js`);
`GET /api/services/<id>/crew-bookings/` (`saved_by_member`, `services.edit`) tells it whose booking was saved on its
page, shown as "Saved on the … page" instead of the boxes. Drafts (`draft=True`) are linked by `Guest.crew_uid`, follow their member
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
limited like the exports, recorded in the History (action `letter`). The logo / stamp / footer JPEGs come from
`DJANGO_LETTERHEAD_DIR` (`logo.jpg`, `stamp.jpg`, `footer.jpg`) — **never in git (the GitHub repo is public) and never
under `static/`**; missing → the letter has no pictures. "TO:" is every flight leg's airline, each once, joined with " / " (`views._airlines`). Its layout: bold "Flight:" above the flights on page 1, the
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

**Management Excel** (`xlsx.py`, `report.py`, `GET /api/dashboard/export/?from=&to=&port=`, `views.dashboard_export`, the Dashboard's **Excel** button `data-act="dashboard-export"`): a `.xlsx` written with the **standard library only** (`zipfile` + escaped XML; text cells are always inline strings, never formulas; native DrawingML charts). `report.data(profile, Range, now)` builds ten sheets of tables (`{"head", "rows", "total"}`); money comes **only** from `calculations.rows_for` (so it equals the Calculations page, hotels / transport / garbage included), job counts from `dashboard.response`; `report.workbook` lays them out with the page look (title, range line, tables with styled header / row lines / bold totals, fitted widths, the first table's header frozen, notes, one chart; a sheet whose figures are all zero shows "No data"). From and To required, at most 24 months; everyone, Users get their ports (a one-port User's files are named after it); rate limited with the exports; audit `dashboard.export`. `crewbookings.early_on_signers(service)` counts every early on-signer (visa charged or not).

**Page Excel files** (`dataexport.py`, `GET /api/export/<page>/?<that page's list query>` with page `vessels` /
`hotels` / `transfers` / `closures` / `disposal` / `calculations` / `services`, and `GET /api/export/all/?from=&to=&port=`;
`views.data_export` / `data_export_all`; buttons `data-act="page-export" data-page=…` on each page (Vessels too, beside
+ Add Vessel; the old `/export.csv` is gone) and `dashboard-data-export` beside the Dashboard's Excel): **each file is the
page's table with the page look** (user's decision, 2026-11-26). `dataexport.COLUMNS[page]` = the page's headings in its
order, each with the page's rule (`port` = several ports, `money.edit`, `completed` = Completed ticked on Services);
`tests_page_excel` reads the front end's headings (`bookings.js` HOTEL/TRANSFER_COLUMNS, `closures.js` / `calculations.js`
COLUMNS, `disposal.js` / `services.js` `heads`, the Vessels `<thead>` in `index.html`, `opVessels.js` COLUMNS for
`operation/visits.EXPORT_HEAD`) and must stay equal: **a new page column needs its export column**. No ids or other
columns the page does not show; a two-amount cell becomes two columns (`SPLIT`: Garbage & Sludge LE / USD); Calculations'
Cost / Revenue are the LE amounts, with the page's totals as a bold last row (Garbage & Sludge too, with `money.view`).
Values typed: numbers, `xlsx.Day` / `Moment` (Cairo), `xlsx.Price(value, currency)` (a number shown "USD 1,234.00"),
`xlsx.Status(text, tone)` coloured like the pills, "—" = empty. Each sheet takes its page's own unpaged rows
(`listing.matching`, `logistics.filtered`, `closures.filtered`, `calculations.filtered`, `disposal.response`,
`services.filtered`), so filters and port scoping are the page's; the page modules' `exportQuery()` is their list query
without `page` / `page_size`. All data: five sheets (not Vessels / Services), From–To required (at most 24 months,
`views._export_range`, shared with the management Excel), each page reading the range its own way. Every role with
`exports` and the page; rate limited with the exports; audit `data.export`.

**Excel look** (`xlsx.table_sheet(name, title, filters line, head, rows, total=None)`): title (bold 14), the filters
line (`dataexport.filters_line`: range, ports, search), an empty line, the header (bold on `HEADER_FILL` with a line
under), body rows with thin lines, the totals row bold with a line over; `fit_widths` sizes columns (8–60), the header is
frozen (`Sheet.freeze`) with filter arrows (`Sheet.filter` + the `_xlnm._FilterDatabase` name); a text of several lines
wraps. `Sheet.looks` maps row index → `title` / `muted` / `header` / `body` / `total`; a sheet without looks writes
exactly as before (fixed styles 0–6). Styles are collected per workbook (`xlsx._Styles`); currencies get number formats
from 167. Colours are the light theme tokens (`HEADER_FILL`, `TONES`).

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
Every role may read it. Rows' `vessel` has `port_label` (sort `port`; the page's Port column shows for
`ME.multiPort`). Each row carries `status` / `cancel_reason` (service rows; None for bookings and garbage),
`closed` and `ref {kind, id}` (what `/api/accounting/` closes; None for garbage with no `VesselDisposal` yet).
`status=` / `accounting=` comma lists filter the rows (unknown → 400, empty items ignored; any `status` filter drops
rows without a status); totals follow the filters and add `open` / `closed`.

**Service status** (migration 0019): `Service.status` (`in_progress` default / `completed` / `cancelled`,
`constants.SERVICE_STATUSES`) and `cancel_reason` (`validators.clean_service_status`: required when Cancelled, refused
otherwise, 500 characters; a save without the key keeps the stored value). Existing services became Completed. A
cancelled service is skipped by `crewbookings.crew_members` (its drafts go, and come back if un-cancelled),
`early_arrivals` and `listing.missing_details`; its money lines stay (the dialog sets the money to 0 on choosing
Cancelled). **Accounting** (`accounting.py`, `POST /api/accounting/ {kind: service|hotel|transfer|disposal, id,
closed}`, permission `accounting.close` (which needs the Calculations page); only a thing with a line on Calculations, i.e. some
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

**Ships and customers** (migration 0021; `ships.py`, `customers.py`, `GET/POST /api/ships/`, `PUT/DELETE
/api/ships/<id>/`, `GET/POST /api/customers/`, `PUT/DELETE /api/customers/<id>/`): `Ship` (name upper-cased, `imo`
7 digits with its check digit (`validators.imo_valid`), unique when not empty; empty only with `no_imo`; `opr`;
`customer` PROTECT; `active`) is shared by all ports; admins and port users create / edit ships (OPR from their
port's list + All ports), only admins delete (`ships.IN_USE` while vessels use it). `Customer` with
`CustomerContact` (max 20) and `CustomerRate` (one per service type in `constants.RATE_UNITS`: per service, per unit
of quantity, per line, or a percentage); every role reads, admins write. `Vessel.ship` (PROTECT, null for old
vessels): `validators.clean_vessel_ship` requires `ship_id` on a **new** vessel (`NEED_SHIP`), keeps the saved one
when the key is absent, allows an inactive ship only if already linked; the ship's OPR is allowed even if not in
the port's list. Vessel JSON `ship {id, name, imo, customer_id}`. `Service.billing_party` (Customer, PROTECT) and
`Service.billing` (`constants.BILLING`: `account` default / `cash`, a label only; `clean_service_billing`: a new
service defaults to its ship's active customer, a save without the key keeps the stored value). Calculations rows
carry `billing` / `billing_party`; `billing=` filters service rows only, `party=` (id or `__none__`) keeps service
rows only; response `parties`; the data export's Calculations sheet has both columns. Front end: `js/shipPicker.js`
(type-ahead on the vessel name, "+ New ship" last; Enter with no pick opens the inline `newShipPanel` from
`js/modals/ship.js`, inside `#qa-newship` / `#vf-newship`: the app has one dialog), `js/parties.js` (customer
cache), `js/rates.js` (pure, tested in `parsing_test.js`: which revenue boxes the agreed rate fills; a box typed
in during the dialog is never filled, a saved service only fills empty ones, nothing while Cancelled); the service
dialog (now async: it loads customers) shows the rate under the billing fields.

**Services page** (`services.py`, `GET /api/services/`, page `js/pages/services.js`, migration 0022): services as a
work list. `Service.completed_at` is set only by the server (`services.stamp_completed`, in `service_create` /
`service_detail`, and the admin inline in `VersionedAdmin.save_formset`, read-only there): becomes Completed → now,
leaves it → None, else kept (one completed before 0022 stays None); JSON gives it as Cairo `local_iso`. `services.missing(service, month_rate,
incomplete_uids)` gives, in order, `Agent`, `Cost`, `Revenue` (`money_gaps`: an **empty** box per type, a typed 0
is filled in; Cash to Master has no cost, its revenue needs the amount and its percentage / fixed share), `Rate`
(a `finance.service_lines` line `rate_missing`) and `Bookings` (Crew Change: a crew uid on a not-cancelled draft or
money-less booking, `incomplete_crew_uids`, uses crewbookings' `_crew_uids` / `_INCOMPLETE`); nothing for
Cancelled. `sailed` = the booking alerts' rule. `filtered(profile, params)` (also the export): `status` comma list
(default `in_progress`), `missing=1`, `from` / `to` on the vessel date — **on the completed date when only Completed
is ticked** (`completed_day`: `completed_at` Cairo date, else the vessel date, `completed_guess`) — `type`,
`agent` (`__none__`), `q`, `port`; database narrows by port / status / type / vessel date, the rest in Python;
oldest first (only Completed: newest first); a fixed number of queries. The page gets them grouped
(`grouped(rows)`: `vessels: [{vessel {id, name, date, port, opr, terminal, berth}, services}]` in row order, paged by
vessel, `count` = vessels, `services_count`) and shows vessel cards that open to service cards (`sv-toggle`). Export
page `services` in `dataexport` (still one row a service; its headings are services.js's exported `heads`;
not in All data: `ALL_PAGES`). The tick filter is shared (`components.tickFilterEl`, `util.tickSummary`; each
page reads its own `data-tick` group inside its own box). A service card opens `openServiceForm(type, service, {from:
'services'})` (edit roles; `afterServiceChange` closes the dialog and reloads the page) or the vessel (read-only);
filters are kept in `localStorage` (`sheet.services.filter`).

**Permissions and pages** (migration 0025, `constants.PERMISSIONS` / `PAGES` / `TEMPLATES`, `tests_permissions`):
each User has `Profile.permissions` and `Profile.pages` (JSON lists of fixed keys); `Profile.can(key)` /
`sees(page)` answer True for Admins, and re-apply the dependencies whatever is stored (`PERMISSION_NEEDS`:
`history.view` needs `money.view`, `accounting.close` needs the Calculations page; `PAGE_NEEDS`: Calculations /
Exchange rates need `money.view`, History = `history.view`; Vessels always). Writes: `vessels.edit` (create / update),
`vessels.delete`, `services.edit` (create / update / delete) plus `services.status_permissions(old, new)` (to or from
Cancelled `services.cancel`, to or from Completed `services.complete`; a new service counts from In progress),
`cancel_bookings` also `bookings.edit`, the service's bookings list `services.cancel`, `documents` (LOG, receipt),
`master.edit` (add / remove values), `customers.edit` (ships and customers; changed agreed rates also `money.edit`,
`customers.save_customer(may_change_rates=)`), `closures.edit`, `bookings.edit`, `disposal.edit`, `accounting.close`.
Page-only routes: `/api/services/` services, `/api/hotels|transfers/…` hotels / transport (crew picker: either),
`/api/closures/…`, `/api/disposal/…`, `/api/calculations/`, `/api/dashboard/` + jobs, `/api/rates/` and
`/api/disposal-prices/` (rates page). Vessels, alerts, options, ships and customers stay readable for dropdowns.
Exports: `exports` + the page (`dataexport.EXPORT_PAGE`, Vessels included); All data and the management Excel need
the Dashboard page and leave out the sheets of pages not had (`dataexport.all_pages_for`, `report.data`); the
alerts' `Hotel: …` / `Transport: …` lines follow those pages. History: `history.view`; a User gets only
`history.PORT_TYPES` records of their ports (Profile records carry a home port, so types, not ports, keep people out;
`port_of` gives PortClosure its port from 0025 on). Migration 0025 gave every existing Profile everything; a new
account starts with nothing (Vessels only); `tests.make_user(..., permissions=None, pages=None)` gives all.
`index` sends `me.permissions` / `me.pages` as they apply; the template shows only those nav items, Excel buttons
with `exports`; JS uses `config.can(key)` / `sees(page)` (no `canEdit` any more), the router lands unseen pages on
Vessels, the service dialog disables statuses `util.statusNeeds` (twin of the server rule, `parsing_test.js`) says
are not allowed. `seed_demo` adds `marine` (Alexandria, Marine template); other demo Users have everything.
Templates: Marine employee, Operations employee, Branch manager (the Accounts employee template was cancelled).

**Money permissions** (access rework piece 3, `moneyaccess.py`, `tests_money`, migration 0026): the one place that
knows which values are money; the maths (`finance`, `calculations`, `vessel_to_dict`) always works on full data and
responses go through `moneyaccess` last (`profile=None` = internal, everything). **`money.edit`** (the forms): a
service's money keys (`SERVICE_MONEY`: cost / revenue / currencies / `exchangeRate`; per line of `MULTI_TYPES` the
four price keys; on-signers' `brokenVisa`; Cash to Master's six keys), a booking's prices (`BOOKING_MONEY`, incl.
currencies and `exchange_rate`), the Garbage & Sludge rows' money (`disposal_row_out`, also each line's), customers'
`rates`, the receipt's amounts (`receipt.prefill(service, with_amounts)`), and with either permission the vessel's
month `rate`. Without it the server never sends them, a save **keeps the stored values**
(`keep_service_money` matches lines / on-signers **by uid**: since 0026 every line of a Delivery / Landing service
has a stable 12-hex `uid` made by `validators._uid`; `keep_booking_money`; `save_customer` keeps the rates) and
**sending any key is 403** (`service_money_sent`, `booking_money_sent`, `"rates" in payload`); `cancel_bookings(...,
zero_money=)` zeroes booking money only with it. **`money.view`** (overviews): `vessel_out` drops `total_cost_egp` /
`total_profit_egp` and every service's `calc`, `totals_out` the list's money totals, `require_sort` refuses
`sort=total_cost_egp` (403, list and Vessels Excel), `dashboard_out` the Dashboard's money keys, `disposal_out` the page's
`totals`, `tags_out` the Services page's `Cost` / `Revenue` / `Rate` tags (also in `missing=1` and the export),
`money_columns` every column whose head is in `MONEY_HEADS` (the management Excel; the page Excel files follow their
page's own column rules;
the Excel also drops "Profit by service" and the Summary's money notes; `report.CHARTS` name their series by head,
so a chart whose column is gone is not drawn). Front end: `config.can('money.edit' | 'money.view')` hides the boxes /
pills / columns / panels (the template leaves out the Dashboard's money panels), `js/moneyKeys.js` `stripMoney` (twin
of `SERVICE_MONEY`, `parsing_test.js`) cleans what the service dialog sends; the dialog's entry rows carry `data-uid`.
A new money field: add it to `moneyaccess` (and `moneyKeys.js` for service data).

**Accounts page** (`accounts.py`, `GET/POST /api/accounts/`, `PUT /api/accounts/<id>/`, page `js/pages/accounts.js`,
dialog `js/modals/account.js`): **Admins (superusers) only** (`access.require_superuser(request)`, `me.isSuperuser`
renders the nav item / page). Lists every account (on first, then username) with home port / ports (column "Ports":
"Alexandria (home), Damietta", superusers "Admin · all ports"), `two_step` (`set_up` / `waiting` / `expired` /
`exempt`), last sign-in, "Can" (`8 of 19`); a GET never creates a Profile; the response's `ports` is
`[[key, name, active]]`, plus `permissions` / `pages` (`[[key, label]]`) and `templates` (`[[key, label, perms,
pages]]`).
`validators.clean_account`: new → username (`USERNAME_RE`, unique ignoring case: `accounts.TAKEN`), names (150),
`home_port` + `ports` (`_account_ports`: home required and put first; each must exist and be turned on unless the
account already has it; at most 50), `permissions` / `pages` (`_account_ticks`: known keys only, fixed order;
Vessels added, History set from `history.view`; dependencies refused; absent on an existing account = kept),
password through Django's `validate_password`; existing → names / ports / ticks / `active` only, anything else
ignored. The dialog: Home port select + Extra ports ticks (the home's tick on and fixed), Template (fills the ticks,
not saved), Pages ticks grouped like the sidebar (Marine / Operation / Reports / Master data) and Can ticks grouped
Marine / Operation / General (`js/tickGroups.js`, twin of `PAGE_NEEDS` / `PERMISSION_NEEDS`, checked by
`tests_permissions.TickGroupsTwinTests`; a new permission or page must be put in a group), each group with an **All**
tick plus one top **All** (an All also ticks what its boxes need); a tick that needs another is disabled and unticked
without it. Superuser and staff accounts are
refused (`accounts.LOCKED_ACCOUNT`, managed in the admin pages); the page never sets either flag. Turn off =
`is_active=False` (Django drops the session on the next request) + the user's remembered computers deleted. The
temporary password triggers `must_change_password` through the existing signal; History via the User / Profile
signals. No version column (last save wins).

**Ports** (`ports.py`, `Port` model, migration 0023; page `js/pages/ports.js`, dialog `js/modals/port.js`, `GET/POST
/api/ports/`, `PUT /api/ports/<key>/`, Admins only): `key` (fixed, made once by `ports.make_key` from the name:
a–z / 0–9, at most 18, a digit added when taken), `name` (2–40, unique ignoring case: `validators.clean_port`),
`active`, `position`. Never deleted (no DELETE route). Records store the key; every label comes from
`ports.label(key)` / `labels()` / `ordered()` / `exists(key, active_only)`, read once per request (cached on
`history.current_request()`, `ports.forget()` after a save). A turned-off port takes no new vessel / closure /
Master-data value (incl. a PATCH move) / price month; what is there stays editable. The page lists vessels and active
Users per port; after a save it updates the shared `PORTS` / `PORT_LABEL` in place (`refreshPorts`).

**Agents:** `Vessel.arrival_agent` (who entered it), `Vessel.sailing_agent` (who sailed it) and `Service.agent` (who
did that service), all plain text from the Agent list, empty until chosen. `listing.missing_details` feeds the
"Missing details" alert (key `missing`): vessels dated before today (Cairo) missing any of the five times, a needed
delay reason, or any agent (every service type needs one).

**Operation** (Django app `operation`, its own migrations from `operation 0001`; design
`specs/2026-11-25-operation-app-design.md`): the user's workbook `ARKAS_Port_Berthing` as four pages — every vessel
at every terminal, separate from Vessels (which lists only the vessels the company serves). `Terminal` (name, code,
`port`, quay length, cranes, `berths` JSON list, `lines` (its shipping lines from the port's Master data list;
empty = every line of the port; a visit then offers only these), `active`; on the Terminals page in the Operation
folder for Admins (every port) and the tick `operation.master` "Edit terminals and vessel list" (own ports,
`access.require_master`), `GET/POST /api/operation/terminals/`, `PUT …/<id>/`, never deleted) and `Visit` (terminal PROTECT, vessel name upper-cased,
shipping line from the Master data "Shipping line" list, LOA, ETA / ATA / ETB / ETC / ATB / ATD, planned / actual
berth from the terminal's list (the saved value stays allowed), cranes, discharge / loading, `version`). A visit's
port is its terminal's: `operation.access.scoped_terminals` / `scoped_visits` (`terminal__port__in`), every write
`require_port`; another port's visit is 404, moving one to another port's terminal 403. Input in
`operation/validators.py` (refused, never fixed; ETA required; ATB needs ATA, ATD needs ATB, ETB not before
ETA, ETC not before ETB, order checked). Figures
only in `operation/figures.py`, worked out on read, never stored: status Completed (ATD) / Working (ATB) / Planned,
waiting ATB−ATA, operation ATD−ATB, port stay ATD−ATA (hours, 1 decimal), total moves, moves/hr = total ÷ operation;
Live data's moves/hr = moves ÷ hours since ATB. Pages (`constants.PAGES` `op_vessels` / `op_live` / `op_analysis` /
`op_charts`) and permissions `operation.edit` / `operation.delete` / `operation.master` (all need `op_vessels`); existing accounts start
with them off, the Branch manager template has them. **Vessel Data** (`visits.py`, `GET/POST /api/operation/visits/`,
`PUT/DELETE …/<id>/` with `conflicts`, filters status / terminal / line / q / from–to on the report date (ATA's Cairo
date, else ETA's) / port, sorts, paging; Excel `…/visits/export/` with `exports`), **Live data** (`live.py`, one card
per turned-on terminal: calls in 7 days, Working vessels, Next 7 days = not berthed and (ATA set, or ETA before the end
of the 6th day after today, past ETAs included): marked **Arrived** with an ATA, **Overdue** (`overdue`) without one
and ETA passed; All / one-terminal buttons in the
page; the terminal's picture on top when the server has one: `pictures.py`, `<letterhead folder>/terminals/<CODE>.png|.jpg`,
PNG / JPEG by first bytes, 1 MB, codes of letters / digits / _ / - only, `GET …/terminals/<id>/picture/` scoped; no upload
in the app, never in git — the cut demo pictures live in git-ignored `terminal-pictures/`), **Vessel list** (`vessel_list.py`,
`ListedVessel` name + fixed LOA + `line` (shown **Operator**, from any port's Shipping line list, required on a
new entry; migration `operation 0004`), all ports, `GET/POST /api/operation/vessels/`, `PUT/DELETE …/<id>/`: read with `op_vessels`,
write with `operation.master`, delete Admins; the visit dialog's name box suggests them and fills the LOA and, when the terminal
offers it, the line; visits keep their own text copy), **Berthing windows** (`windows.py`, `BerthingWindow`, migration
`operation 0005`: a line's weekly slot at a terminal, start day + time → end day + time, Mon = 0, Cairo, an end at or
before the start is in the next week; a line may have none or several; same line at the same terminal may not
overlap, `validators.clean_window` / `week_span`; `GET/POST /api/operation/windows/`, `PUT/DELETE …/<id>/`: read with
`op_vessels`, write with `operation.master` in own ports; page `js/pages/windows.js` + dialog `js/modals/window.js`,
nav item beside Terminals for the same people; `GET …/windows/nearest/?terminal=&line=&eta=` → the occurrence holding
the ETA, else the next one to start after it (never one that started before; the user's rule), worked out on read: the visit dialog's
`#visit-window` hint, nothing when the line has no window), **Analysis reports** and **Report
charts** (one response, `analysis.py`: headline averages, Calls per week / month / year when From and To are both set,
a row per terminal in scope and per shipping line; filters port / terminal / berth / line / from–to). History tracks
the models (`history.track`, `history_port()`; types `visit` / `berthingwindow` are in `PORT_TYPES`). Front end: `js/operation/shared.js`,
`js/pages/opVessels.js`, `opLive.js`, `opAnalysis.js`, `terminals.js`, `vesselList.js`, `windows.js`, dialogs
`js/modals/visit.js`, `terminal.js`, `listedVessel.js`, `window.js`. `dom.js` allows `src` / `alt` with the same safe-URL check as `href`.
`seed_demo` adds five Alexandria terminals and PSD EAST (Port Said), six lines and the workbook's seven visits plus
two Working and four upcoming ones, and a vessel-list entry for each; `viewer` has the pages without the three
Operation ticks.

**Terminal / berth** (migration 0029): `Vessel.terminal` (Master data "Terminal" list of its port, optional) and
`Vessel.berth` (typed, 20 characters); a save without the key keeps the stored value. Shown in the vessel form and
Port call block, and as a "Port / Terminal / Berth" table on the management Excel's Port
performance sheet. `seed_demo` adds terminals for every demo port (Alexandria ACCHCO / AICT, Port Said TMT…).

**Delay reason:** `Vessel.delay_reason` (Master data "Delay reason" list) is required when berthing is more than 2
hours after arrival (`constants.is_delayed`, exactly 2:00 is not delayed) and refused otherwise
(`validators.clean_delay_reason`; a PUT without the key keeps the stored reason). The vessel form shows it while the
times say delayed or a reason is set (`util.isDelayed`).

**Port closures** (`closures.py`, `GET/POST /api/closures/`, `PUT/DELETE /api/closures/<id>/`): `PortClosure` (port,
closed from, reopened or empty = still closed, reason from the "Closure reason" list, notes), not linked to vessels.
Scoped by its own port with `access.scoped_closures`; the list shows closures overlapping a date range. Page
`js/pages/closures.js`, dialog `js/modals/closure.js`.

**Master data** (`Option`: kind, value, `port`): ten lists (OPR, POC, Agent, Hotel, Airport, Port, Delay reason,
Closure reason, Terminal, Shipping line — the last used only by Operation's visits). `port` is `""`
for All ports or one port key. Users only ever create values for one of their ports (home port when none is named;
never All ports) and see All-ports + their own; admins choose the port when adding and move values with `PATCH /api/options/<id>/` (admin only). Every dropdown is
built with `optionChoices(kind, current, port)` → only that port's + All-ports values, always keeping `current`.

**Front end** (`static/sheet/js/`, entry `main.js`):
- **Sidebar folders:** `index.html` groups the nav into **Marine** (Vessels, Services, Port closures, Ships),
  **Operation** (Vessel Data, Live data, Analysis reports, Report charts, Vessel list, Terminals, Berthing windows), **Reports** (Dashboard, Garbage & Sludge, Hotels, Transport, Calculations) and **Master data** (Master data,
  Customers, Exchange rates, Ports, Accounts, History); each item keeps its own `{% if %}`, a folder with none is not
  rendered. A folder head is a shaded band with its icon (`nav-group-label`), no capitals, items indented under a
  thin line. `js/navGroups.js`: `data-act="toggle-nav-group"` opens / closes (localStorage `sheet.navGroups`), the
  router opens the folder of the page on screen.
- **The person's ports:** `me` (`json_script`) has `ports` (every key for Admins), `homePort` ("" for Admins),
  `multiPort` (Admin or 2+ ports), `isAdmin`, `isSuperuser`, `permissions`, `pages`. `config.myPorts()` (filters) and
  `openPorts()` (turned-on ones, for new records) are functions because the Ports page changes `PORTS` in place;
  `components.portOptionEls({all, selected, ports})` ("All my ports" for Users) and `formPorts(open, current)`.
  Port filters / Port columns show when `ME.multiPort`; forms start on the shown port, else the home port.
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
- **Delete / Remove buttons** show only the bin icon: `components.deleteBtn(act, dataset, cls = 'danger', label =
  'Delete')` (`title` and `aria-label` carry the word).
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
