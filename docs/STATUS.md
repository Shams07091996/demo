# Project status

Last updated: 2026-11-24. Read this with `CLAUDE.md` before starting work. Each feature has a design
(`docs/superpowers/specs/`) and a build plan (`docs/superpowers/plans/`) that record what was decided and why.

## Where things stand right now

- **Services page (2026-11-24):** on branch **`feature/services-page`, not merged yet** (waiting for the fresh
  review and the user's OK). Needs migration **`0022_service_completed_at`** on the user's database (existing
  services get no completed time; the page shows their vessel date as "≈ date"). A **Services** page (sidebar, after
  Vessels) lists services, not vessels: it opens with **In progress** ticked (the operators' daily to-do list);
  **Missing details only** shows services lacking an agent, a cost or revenue (a typed 0 counts as filled in), a
  rate, or complete crew bookings (the managers' view); ticking only **Completed** with a From–To shows what got
  done in that range (by the new completed time). Filters: status ticks, missing, From–To, service, agent, vessel
  search, port (admins / accounting). "Sailed" marks an open service whose vessel has left. A row opens the
  service (edit roles; saving goes back to the list) or the vessel (read-only). **Excel** exports every filtered
  row. 709 backend tests; `npm run check` green; smoke test passes for alex / admin / viewer / suez.

- **Ships, customers and billing (2026-11-24):** merged into `main` on 2026-11-24 (branch deleted); fresh review
  done (four findings fixed test-first). Needs migration **`0021_ships_customers`** on the user's database. Existing
  vessels keep working without a ship; a **new** vessel must be for a ship (picked from the name box's dropdown, or
  added there with + New ship). New **Ships** page (name, IMO or No IMO, OPR, customer, active; admins and port users
  add / edit, only admins delete) and **Customers** page (contacts, agreed rates per service type, linked ships;
  admins edit, everyone reads). Each service has an optional **billing party** (a customer; a new service starts
  with its ship's customer) and **Cash / On account** (a label); the billing party's agreed rate fills in the
  revenue, which the person can change. Calculations has Billing party / Billing columns, a Billing tick filter and
  a billing party dropdown; the Calculations data export has the two columns. 685 backend tests; `npm run check`
  green; smoke test passes for alex / admin / viewer / suez. After the update: add the company's ships and customers
  (Ships / Customers pages) before people add vessels.

- **Data export (2026-11-24):** merged into `main` (branch deleted). No migration. An **Excel** button on Hotels, Transport, Port closures, Garbage & Sludge and Calculations downloads every row that page's filters show (all pages of results) as a plain table for other programs (one header row, numbers and real dates, ids to join the files); **All data** beside the Dashboard's Excel button gives the five in one file for its From–To (at most 24 months) and port. Every role; port users only their port. 646 backend tests; fresh review done (two findings fixed test-first: numbers are written exactly as stored, so a CSV saved from Excel keeps them, and searches are no longer written to the audit log); `npm run check` green; smoke test passes for alex / admin / viewer / suez.

- **Service and accounting status (2026-11-23):** merged into `main` on 2026-11-24 (branch deleted). Needs migrations **`0019_service_status`** and **`0020_cancel_and_frozen`** on the user's database (existing services become Completed). Each service has an operations status (In progress / Completed / Cancelled, with a required reason when Cancelled), chosen beside the Agent in the service dialog and shown as a small coloured label on the service card, the Summary and Calculations; the vessel list shows "N in progress". A cancelled service drops its draft hotel / transport bookings and raises no alerts; choosing Cancelled sets its money to 0 (someone can still type an amount). Accounting (**the read-only accounts**, and admins) switch each Calculations line Open / Closed; a Closed line is **locked for every role** (no edit or delete of that service / booking / garbage & sludge, no deleting its vessel) until accounting reopens it. Calculations has tick-box filters (e.g. "All except Completed") for status and accounting, and its totals count Open / Closed lines. The Dashboard and the management Excel (new tenth sheet "Service status") count services per status and lines Open / Closed per month. 613 backend tests; fresh review done (two important findings fixed test-first: the lock now reads the stored flag under a row lock, and the Django admin pages can't change or delete closed things); `npm run check` green; smoke test passes for alex (with `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) / admin / viewer / suez.
  **Added on the same branch (2026-11-24): cancelled bookings and kept rates.** Hotel stays and transfers have a Cancelled tick (money to 0, a fee can still be typed; label "Cancelled"; no alert). Choosing Cancelled on a saved Crew Change lists its saved bookings, ticked to be cancelled too (closed ones can't be ticked). Accounting can't close a line without a rate (the month's or one written on the line) or, for garbage & sludge, without the month's price; closing writes the month's rate onto the line (and copies the garbage & sludge price), kept after reopening until a person changes it. 627 backend tests; fresh review done (one finding fixed test-first: the kept rate and price are read-only in the admin pages); `npm run check` green; smoke test passes for alex / admin / viewer / suez.
- **ARKAS look (2026-11-23):** merged into `main` (branch deleted). Navy sidebar, white cards with a light shadow, the ARKAS logo with "ARKAS / EGYPT HUSBANDRY", tab titles "ARKAS Egypt Husbandry". No migration. The logo is `brand.png` in `DJANGO_LETTERHEAD_DIR` (never in git); without it the anchor icon shows. **The previous look is kept on branch `backup/look-2026-11-18`** (the user asked to keep it). 569 backend tests; fresh review done (no critical or important findings; seven minors left for the user: logo file read on every page, logo address not rate limited, unreadable logo logs on every page, sidebar logo read twice by screen readers, sign-in logo margins tuned to this picture, flatter dialog shadow, logo cached up to an hour); `npm run check` green; smoke test passes for alex (with `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) / admin / viewer.
- **Edit-conflict warning (2026-11-21):** merged into `main` (branch deleted). Needs migration **`0018_edit_version`** on the user's database (and `0017` if not run yet). A save of a vessel, service, hotel stay, transfer or port closure that someone else saved after the dialog opened is refused (nothing saved); the dialog says who, when and which fields, with **Show their version** / **Save mine anyway**. 553 backend tests; fresh review done (three findings fixed test-first); `npm run check` green; smoke test passes for alex / admin / suez (viewer: re-run after the merge, its only failure was the known Excel timing check fixed in the style tidy).
- **Master receipt (2026-11-20):** merged into `main` (branch deleted). Needs migration **`0017_history_receipt`** on the user's database. 491 backend tests; fresh review done (fixes in); smoke test passes for alex (with `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) / admin / viewer / suez.
- **LOG letter layout (2026-11-20):** on `main` (bold "Flight:" / "Personal details:", personal details and stamp on page 2).
- **Deployment guide (2026-11-20):** `docs/DEPLOYMENT.md` rewritten as a step-by-step checklist for a Windows server (IIS + NSSM + waitress; Linux notes): the three PostgreSQL logins (`postgres`, `marine_app`, `marine_backup` with `pg_read_all_data`) and why people never get one; creating every account in the admin pages; nightly `pg_dump` and restore test; and "what happens if" (two people edit the same record → the second save is warned about, see the edit-conflict warning; database down → saves fail cleanly, app reconnects by itself; disk lost → restore the last backup). README, SECURITY §4 and CLAUDE.md point to it.
- **Style tidy (2026-11-20):** the last four places that set a style from code now use `hidden` (Add vessel button, quick-add bar, Cash to Master's percentage / fixed fields) or a CSS class (port banner colour: `.port-banner.port-<port>` in `app.css`; `PORT_COLOR` removed). Not a security fix: a search found no `innerHTML` or other unsafe code. `npm run check` green; smoke test passes for alex / admin / viewer / suez.
- **Management Excel (2026-11-20):** merged into `main` (branch deleted). No migration. 519 backend tests; fresh review done (no critical or important findings; two minors fixed); `npm run check` green; smoke test passes for alex (with `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) / admin / viewer / suez; a workbook made from the demo data opened in Excel on this PC with its charts.
- **Garbage & Sludge page (2026-11-20):** merged into `main` (branch deleted). Replaces the service of the same name. Needs migration **`0016_garbage_page`** on the user's database (it deletes the old test Garbage & Sludge services and prices). `npm run check` green (472 tests); smoke test passes for alex (with `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) / admin / viewer / suez.
- **Garbage & Sludge (2026-11-20):** merged into `main` together with the admin-port fix and `docs/DEPLOYMENT.md` (branches `feature/garbage-sludge` and `fix/admin-vessel-port` deleted). Needs migration **`0015_disposal_price`** on the user's database. `npm run check` green (467 tests); smoke test passes for alex / admin / viewer / suez.
- **OPR / POC required + Master data layout (2026-11-19):** merged into `main` (branch deleted). No migration. `npm run check` green; smoke test passes for alex / admin / viewer / suez.
- **Crew bookings, sailing date, early arrival, LOG letter (2026-11-19):** merged into `main` (branch deleted). Needs migration
  **`0014_crew_bookings`** (it also moves every vessel that has a sailing time to its sailing day). For the LOG
  pictures, put `logo.jpg`, `stamp.jpg`, `footer.jpg` (from the user's `LOG.docx`) in a folder outside the project and
  set `DJANGO_LETTERHEAD_DIR`; without it the letter has no logo / stamp / footer. `npm run check` green; smoke test
  passes for alex / admin / viewer / suez; fresh review done (fixes in).
- **Port closures, delay reason, Missing details (2026-11-19):** merged into `main` (branch deleted). Needs migration **`0013_port_closures_and_delays`** after merging.
  **Right after migrating, an admin fills Master data → Delay reason and Closure reason** (at least All-ports values):
  while they are empty, no closure can be added and a vessel that berthed more than 2 hours after arrival cannot be
  saved. Smoke test passes for alex / admin / viewer / suez; fresh review done (fixes in).
- **Two-step login (2026-11-18):** merged into `main` (branch deleted).
  Needs migration **`0012_two_step_login`** and `pip install --require-hashes -r requirements.txt` (new packages
  django-otp, segno). After merging, on the user's PostgreSQL database: `migrate`, create the superusers, each sets up
  Authenticator within 72 hours of the migration / account creation.
- **Git branches:** `main`, plus `chore/pythonanywhere-demo` (not merged: puts back the hash-locked
  `requirements.txt` and the settings that the user's Render commits on `main` had replaced). Agents per job, Dashboards and New look merged 2026-11-18 (branches deleted).
- **Online demo (2026-11-18):** https://shams1996.pythonanywhere.com (PythonAnywhere free plan, the user's account,
  demo data only, SQLite with `DJANGO_ALLOW_SQLITE=1`). Updates are built from `main` (the old
  `chore/pythonanywhere-demo` branch is gone; `main` has the hash-locked `requirements.txt`); the demo keeps two-step
  login (user's choice, 2026-11-19). How to update or
  remove it: `docs/DEMO_HOSTING.md` part B. Render was dropped (needs a credit card). `origin` is the user's
  GitHub repo `Shams07091996/demo` (public).
- **Tests:** `npm run check` green with 443 backend tests on `main`; smoke test
  (now signing in with a code) passes for `alex`, `admin`, `viewer` and `suez`. Screenshots (light / dark / phone) in `.superpowers/screenshots/new-look/` (not in git).
- **The user's own database:** **PostgreSQL 17 only**, on this PC (port 5432; PostgreSQL 18 on 5433 is not used).
  Database `marine_sheet`, signed in as `postgres` for now (password in the user's
  `%APPDATA%\postgresql\pgpass.conf`, never in the project). Migrations through `0010` applied; **`0011_agents_per_job` still to apply** (`DJANGO_DEBUG=1 python manage.py migrate` with the settings below); no users yet.
  The old `db.sqlite3` (test data) was deleted. Before company data: a dedicated `marine_app` login instead of the
  superuser, and a stronger `postgres` password.
  App settings for it: `DJANGO_DB_NAME=marine_sheet DJANGO_DB_USER=postgres DJANGO_DB_HOST=localhost
  DJANGO_DB_PORT=5432 DJANGO_DB_SSLMODE=disable` (the local server has SSL off and accepts local connections only).
- **Tests (on `main`):** `cd tools && npm run check` → all passed (452 backend tests; all 452 also passed on PostgreSQL 17 on 2026-11-19, the PostgreSQL-only history trigger tests included); `tools` parser tests pass; the jsdom smoke test
  passes for `admin`, `alex`, `viewer` and the short `suez` run (see `CLAUDE.md` for the throwaway-database setup).

## Built and tested

| When | What | Design |
|---|---|---|
| 2026-11-24 | **Services page** (branch `feature/services-page`): work list of services with status / missing / date / service / agent / search / port filters, what each one is missing, Sailed mark, completed time (`Service.completed_at`), Excel export | `specs/2026-11-24-services-page-design.md` |
| 2026-11-24 | **Ships, customers and billing** (merged 2026-11-24): Ships page and ship picker on the vessel name (quick-add and vessel form, + New ship inline, IMO checked with its check digit, No IMO tick); Customers page (contacts, agreed rates, linked ships); billing party and Cash / On account on every service; agreed rate fills the revenue; Calculations billing columns / filters | `specs/2026-11-24-ships-customers-design.md` |
| 2026-11-20 | **Garbage & Sludge page** (merged 2026-11-20): a sidebar page lists the vessels of a date range and port with garbage m³ and sludge t boxes (saved when left), revenue / cost / profit in EGP and USD, Hide (no garbage or sludge; Hidden filter with Bring back), filters and totals. Prices per month and port on the Exchange rates page: four blocks (garbage / sludge × revenue / cost), each a minimum quantity, a minimum amount in EGP or USD and an extra per unit above the minimum; Copy from last month. The money shows on that page and on Calculations, not in vessel totals. Master data lists are folded shut until clicked. The earlier hand-added service is removed | `specs/2026-11-20-garbage-page-design.md` |
| 2026-11-20 | **Garbage & Sludge** (merged 2026-11-20) (replaced by the page above): admins set USD prices per m³ (garbage cost / revenue, sludge cost / revenue) for each month and port on the Exchange rates page (`DisposalPrice`); the hand-added service "Garbage & Sludge" takes garbage m³ and sludge m³; money = m³ × that port and month's price, converted with the month rate, counted in the vessel totals like any service; no price → the line is flagged and has no money. Prices apply live (changing one changes that month's vessels). Calculations shows each such line's USD profit and USD totals | `specs/2026-11-19-garbage-sludge-design.md` |
| 2026-11-19 | **Admins choose the port of a new vessel** (merged 2026-11-20): with All ports in the header the vessel form and quick add start with no port (the form's Port field is now next to the name); the server refuses an admin's new vessel without one ("Choose a port.") instead of assuming Alexandria. Also: a Master data list loaded before a change was saved no longer overwrites the newer one. `docs/DEPLOYMENT.md`: deploying and creating users | — |
| 2026-11-20 | **Management Excel** (merged 2026-11-20): an **Excel** button on the Dashboard downloads one `.xlsx` for its From–To range (at most 24 months) and port, with nine sheets — Summary, By month, By line, Profit by service, Port performance, Port closures, Agents, Crew, Garbage & Sludge — each with its tables, notes and a native Excel chart. Money is the Calculations page's (services, hotels, transport, garbage & sludge); counts follow the Dashboard. Every role may download; port users get their own port. Written by our own code (no library) | `specs/2026-11-20-management-excel-design.md` |
| 2026-11-20 | **Master receipt** (merged 2026-11-20): a Receipt button on each service opens a form pre-filled with the port, today's date, the vessel and one line (the service and its revenue written as "cost", e.g. "Landing with cost $120"); everything is editable; Download makes a PDF "WHOM IT MAY CONCERN" receipt with the logo and footer, no stamp, and spaces for the master's signature and the ship's stamp. Nothing typed is saved; the History records it | `specs/2026-11-20-master-receipt-design.md` |
| 2026-11-20 | **LOG letter layout** (on `main`): bold "Flight:" above the flights; the personal details start page 2 under a bold "Personal details:", with the stamp beside them and the visa lines after (user's request) | — |
| 2026-11-19 | **LOG letter fixes** (merged 2026-11-19): the airline no longer carries the flight date ("EMIRATES TUE 17 NOVEMBER 2026" was read as the airline; fixed in the parser and, for crew already saved, in the letter); the stamp sits right of the personal details instead of after the last line, so two flight legs no longer push it alone onto page 2. The logo / stamp / footer need `DJANGO_LETTERHEAD_DIR` (on the user's computer: `C:\Users\PC\marine_letterhead`, taken from LOG.docx) | — |
| 2026-11-19 | **CSP on the admin pages** (merged 2026-11-19): the Django admin had no CSP header; it now has the app's strict one minus Trusted Types (its scripts build HTML from text) and with style attributes allowed. Checked in the browser: admin pages, sidebar filter, theme switch, date picker, nothing blocked | — |
| 2026-11-19 | **OPR and POC required** (merged 2026-11-19): a new vessel can't be saved without an OPR and a POC ("Choose an OPR." / "Choose a POC."); once set they can't be emptied; a vessel saved before this rule without them still saves. Master data rows no longer overflow: a long value takes its own line, the port / usage / Remove stay together | — |
| 2026-11-19 | **Port closures, delay reason, Missing details** (merged 2026-11-19): a Port closures page (port, closed from, reopened or still closed, reason from the new Closure reason list, notes; port users their port, admins all, read-only view; change history); a **Delay reason** (new Master data list) required when a vessel berthed more than 2 hours after arrival and refused otherwise; the past-vessel alert is now **Missing details** (the five times, a needed delay reason, arrival / sailing agent, service agents) | `2026-11-19-port-closures-and-delays-design.md` |
| 2026-11-19 | Tighter input rules: OPR / POC / agents / booking hotel, airport and port must be in Master data for the vessel's port (a value already saved stays allowed); service numbers must be real numbers, amounts never negative (user's decision), exchange rate above 0, percentage 0-100; too-long text refused with a message instead of cut (pasted crew-change details still trimmed); exchange rate 0 = empty; more than 100 lines refused | — |
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
| 2026-11-19 | **Crew bookings, sailing date, early arrival, LOG letter** (merged 2026-11-19): every crew member gets an automatic **draft** transfer, and a draft hotel stay when **Needs hotel** is ticked (tagged "To complete" until saved in the dialog); incomplete bookings of a vessel that has sailed join its **Missing details** line; the vessel date becomes the **sailing day** once a sailing time is entered; on-signers landing 2+ days before the vessel show as **Early arrival** until a **Broken visa** cost / revenue (counted in the crew change's money) is entered; a **LOG** button per on-signer downloads the letter as a PDF made by our own code (no library), edit roles only, recorded in the History | `2026-11-19-crew-bookings-early-arrival-log-design.md` |
| 2026-11-16 | Project put under git; `CLAUDE.md` and this file written for future sessions | — |

## Decisions the user made (respect these)

- **Services page (2026-11-24):** operators use it daily as a to-do list, managers to see what is missing;
  **filters, not tabs** (status ticks, Missing details only); a **Completed** view by completed date; an **Excel**
  export; **a typed 0 cost / revenue counts as filled in** (only an empty box is "missing").
- **Ships and customers (2026-11-24):** the customer is **separate from the OPR** (option B): each ship has an OPR
  and a customer. Every ship has an IMO unless **No IMO** is ticked. Admins **and** port users add ships right from
  the vessel form / quick-add bar. A rate **fills in the revenue automatically, and people can change it**. **Cash**
  is a label only; Calculations can filter cash lines out. Next, in this order, each designed on its own: an
  **In-progress services page**, then an **admin accounts & permissions page** (port scope, can edit, can see
  financial reports…).
- **Edit conflicts (2026-11-21):** warn, never overwrite silently: the warning shows who, when and which fields, with Show their version / Save mine anyway (option 2); a `version` counter per record (approach A); the name is shown to **everyone** who gets the warning, port users included (the History page stays admin-only). Not covered: deletes, Garbage & Sludge boxes, rates, prices, Master data, accounts.
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
- **OPR and POC** are required for every new vessel (2026-11-19); older vessels without them still save.
- **Master data:** every list (OPR, POC, Agent, Hotel, Airport, Port) can be per port; admins choose (default All
  ports) and can move values; port users' values are their port's.
- **Security first:** the app is being sold to the user's company. The front end never parses HTML strings
  (no `innerHTML`, no `eval`, no inline styles) and the browser enforces it; keep it that way.
- **UI taste:** lean screens — no help paragraphs, no placeholders, no stat cards; compact controls.
- **Process:** the user chooses **Native** execution (built in-session, one fresh reviewer at the end).
- **Agents (2026-11-18):** an arrival agent and a sailing agent per vessel and an agent per service; **no defaults** (the sailing agent is never copied from the arrival agent, a service never gets the vessel's agent); **every** service type needs an agent, Others / Remarks too; the alert starts the day after the vessel date (agents are known only after the job) and has no look-back limit.
- **Bulk add removed** (2026-11-18, "not needed").
- **Port closures / delays (2026-11-19):** closures are a **separate record** (not linked to vessels; the agent picks
  e.g. "Port closed" as the delay reason); closure reasons have **their own list**; delayed = berthed **more than 2
  hours** after arrival, and a delayed vessel **cannot be saved without a reason**; once a vessel's date has passed
  **all five times** are required; closures on **their own page**; one **Missing details** alert group, one line per
  vessel.
- **Order (2026-11-18):** agents → dashboards → new look, **before** two-step login (which will then be built in the new look).
- **Dashboards (designed 2026-11-18):** jobs per agent (arrival = 1 job, sailing = 1, each service = 1), services per month, money per month as a **separate** table; chart **and** figures; filters date / port / OPR / agent / service type.
- **New look (designed 2026-11-18):** look B (neutral grey, one blue accent), dark and light mode, system font, line icons drawn for the app; **no third-party dependency**.
- **ARKAS look (2026-11-23):** the company's users preferred the colours and cards of a stand-alone ARKAS mock-up. The user chose look C: a **plain navy sidebar (no gradient)**, the **blue accent kept (no teal)**, **white cards, 10 px corners, light shadow**; still no gradients, all-caps labels, stat cards or extra text. The **ARKAS logo** small on a white tile with **"ARKAS" / "EGYPT HUSBANDRY"** beside it; the logo above "EGYPT HUSBANDRY" on the sign-in / locked / error pages. The logo is served from the letterhead folder, never in git. Keep the old look on `backup/look-2026-11-18`. Show the real app before committing.
- **Two-step login (approved 2026-11-18, "go ahead with 2fa"):** everyone, Microsoft Authenticator codes, 30-day
  remember for everyone, no backup codes, superusers reset each other (3–4 planned), exceptions only for non-admins;
  **not for the online demo** for now ("no need for the demo right now").
- **Crew bookings / LOG (2026-11-19):** a draft booking **appears by itself** (the user completes it); every crew member
  must have transport; the warning comes once the vessel **has sailed**; the vessel date is **replaced** by the sailing
  day; early = landing **2+ days** before the vessel date, with a **broken visa** charge; the LOG is a **real PDF**,
  made by **anyone who can edit**, with **no outside library** (Ş → S accepted), no `{{ }}` left in it.
- **Master receipt (2026-11-20):** a PDF made by the app's own PDF code (option 1, not browser printing); edited in a
  form just before download and **never stored** ("I will just give a hard copy"); **no revenue line** — the amount is
  only in the text, written as **cost** because ARKAS's revenue is the vessel's cost; logo and footer, **no stamp**.
- **Service and accounting status (2026-11-23):** two separate statuses: operations on each service (In progress / Completed / Cancelled + reason), accounting Open / Closed on each Calculations line. **Accounting are the read-only accounts** ("they are the same people"). A cancelled service keeps its money lines but its money is set to **0 for both** cost and revenue until someone types an amount (choice B); lines with 0 / 0 are not on Calculations ("they only care if there is any money"). Filters work as **"all except"** (tick boxes). Cancelling drops draft bookings and alerts ("ok"). A Closed line **can't be changed until accounting reopens it** ("they have to get a permission from accounting"). Counts on the Dashboard and the management Excel.
- **Cancelled crew change → bookings (2026-11-23):** cancelling a crew change cancels its hotel stays and transfers **unless someone unticks them** ("unless said otherwise"); bookings are kept with a Cancelled state (money 0 until a fee is typed, no alert), not deleted.
- **Closing keeps the rate (2026-11-23):** accounting can't close a line without a rate ("either global or written manually"); the rate is kept on the line "till someone change it" (also after reopening), and the garbage & sludge price is kept the same way. The Dashboard is left alone for now (it may be overhauled).
- **Data export (2026-11-24):** "every row in all the pages … in an external excel file as we will need them for other programs" — an export, not an import. **Both** kinds: one file per page with its filters (accounting and others) and one All data file (management).
- **Libraries (2026-11-23):** third-party libraries are allowed again, but only with maximum security: each one checked (and the check shown to the user) **before anything is committed**, hash-locked in `requirements.txt`, and installed on the server from an **offline folder of package files** (`pip install --no-index --find-links <folder> --require-hashes`), never from a CDN.
- **Management Excel (2026-11-20):** "line" means the OPR; **all nine sheets** (a tenth, Service status, added 2026-11-23); charts are **real Excel charts inside the file** (option A), not pictures; no library (standard library only); for management presentations.
- **LOG layout (2026-11-20):** bold "Flight:" and "Personal details:"; the personal details and the stamp on page 2.
- **Docs:** keep every `.md` file (STATUS, CLAUDE, README, SECURITY, specs) up to date with each change (user, 2026-11-20).
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
   service, ~~service status~~ (built 2026-11-23, with the accounting Open / Closed), billing basis (Cash / Owners'
   Account).
5. ~~Excel import~~: the user meant an **export** (built 2026-11-24, see Data export above).
6. ~~Ships / customers / billing~~ (built and merged 2026-11-24), ~~the In-progress services page~~ (built
   2026-11-24, branch `feature/services-page`), then the **accounts & permissions page** (admin).

Also: the user may want to move the old shared agent / hotel to a port (Master data page).

Ideas raised along the way:

- Exports of the Calculations page.

## Left open — small things the user hasn't decided on yet

- **Ships / customers (review of 2026-11-24, not fixed):** two people adding the same IMO at the same instant: the
  second gets an error with a reference instead of "another ship already has this number" (customer names likewise
  have no database guard); the Ships page shows the first 200 ships by name with no "more" notice (search finds the
  rest); a rates payload with the same service type twice keeps the last one instead of being refused; port users
  see each ship's port calls counted over all ports; the service dialog can open a moment after a quick second click
  while customers load.
Edit-conflict warning (from the final review, minor):
- "Guests" can be missing from the field list when another save in between changed other booking fields.
- Field names are the stored ones ("Draft" can appear; "On signers" rather than the form's "On-signers").
- An admin-page save raises the version without locking the row (a very narrow race with a dialog save).
- The booking dialog's redraw (e.g. adding a guest) removes the warning; the next Save warns again.
- `describe()` reads the record's whole History (fine now; an index on `object_id` later).
- A version higher than the stored one (only a tampered request) answers 409 listing every field.

Management Excel (from the final review, minor):

- Garbage m³ / sludge t cells use the money format (2 decimals), so 0.125 shows as 0.13 (the cell value is exact).
- The xlsx writer has no 32,767-character cut per cell and lets through sheet names Excel refuses (leading `'`,
  `History`): no current text can reach either (fields are at most 100 characters, sheet names are fixed).
- Charts carry no cached values (previews such as Outlook show them empty until opened in Excel) and have Excel's
  default rounded corners.
- A closure ending exactly at the range start counts as 1 closure with 0.0 hours (same rule as the Port closures page).

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

Crew bookings / LOG (builder's calls to check):
- Old crew changes get automatic bookings only when next saved; a transport draft deleted by hand comes back on the
  next save of the crew change.
- Draft placeholders: 1 night; 00:00 on the vessel date when the flight time can't be read.
- LOG date printed DD/MM/YYYY; "TO" empty when no airline is known; early-arrival look-back 60 days.

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

Port closures / delays (final review, minor, for the user to decide):

- The vessel form decides "delayed" from the wall clock; the server from real time in Cairo. On the night Cairo moves
  its clocks (April / October) the two can disagree: the server may ask for a delay reason while the form hides it
  (change a time, or the reason appears once the times show more than 2 hours).
- A closure that reopened at exactly 00:00 on the From day is still listed for that range.
- The vessel form rebuilds its dropdowns twice when an admin changes the port (harmless).
- The Django admin page for closures doesn't check the reason list or the time order (like the other admin pages).
- No starter values for the Delay / Closure reason lists on a real database (only `seed_demo` adds them).

Master receipt (final review, minor, for the user to decide):

- A double click on Download makes two PDFs and two History records (no "working…" state).
- A failed download (receipt or LOG) shows the error without its reference number.
- The receipt's rate-limit check runs after the vessel lookup (the LOG's runs before): harmless, inconsistent.
- The 40-line limit counts a few rare Unicode line breaks the PDF does not break on (strict side only).
- Migration 0017 and the new tests have not been run on PostgreSQL yet.
- The viewer smoke run ends before its receipt / LOG "403" checks (the backend tests cover them).

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
