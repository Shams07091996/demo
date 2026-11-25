# Operation app: port berthing — design

Date: 2026-11-25. Source: the user's workbook `ARKAS_Port_Berthing -2.xlsx` (sheets Vessel Data, Dashboard,
Analysis & Reports, Report Charts, Settings; the hidden "Combined Data" sheet is ignored, the user's instruction).

## Intent

The Vessels page lists only the vessels we do services for. The new **Operation** part lists **every vessel calling
at every terminal**, ours or not, so the company can follow its jobs against the whole port: who is on which berth
now, who comes in the next 7 days, and how each terminal and shipping line performs (waiting, operation, port stay,
moves per hour). It replaces the Excel workbook above.

## Goals

- A new Django app **`operation`** with four pages in a new sidebar folder **Operation**:
  1. **Vessel Data** (Excel "Vessel Data") — the visits, typed in by people.
  2. **Live data** (Excel "Dashboard") — per terminal: vessels under operation now and vessels due in 7 days.
  3. **Analysis reports** (Excel "Analysis & Reports") — filters, five headline figures, two tables.
  4. **Report charts** (Excel "Report Charts") — two bar charts from the same figures.
- Terminals (Excel "Settings") become records with port, code, quay length, cranes and berths.
- The same rules as the rest of the app: ports, page ticks, permission ticks, History, edit conflicts, input refused
  never fixed, rate limits, strict CSP front end.

## Non-goals

- **No link to the Vessels page** (the user: the two are separate). A visit is not a `Vessel`, not a `Ship`, and the
  existing Master data "Terminal" list (used by the Vessels page) is not merged with the new terminals.
- No money anywhere in this part (so `moneyaccess` is not involved).
- No import of old Excel data (everything is demo data, the user said).
- No management-Excel / "All data" sheets for this part in the first version; only the Vessel Data export.

## Anti-goals

- A User seeing another port's terminals or visits (through any page, filter, export, or the History).
- Anyone who was not ticked by an Admin seeing the Operation folder.
- Figures that disagree between Analysis reports and Report charts (one server function computes both).

## Approaches (picked: A)

- **A. Own Django app inside the same single page** (picked by the user). `operation/` has its own models,
  migrations, API routes (`/api/operation/...`) and tests, and reuses `sheet`'s plumbing (`api.json_api`, `access`,
  `history`, `conflicts`, `ratelimit`, `ports`, `validators` helpers). The four pages live in the existing one-page
  front end. Trade-off: `operation` depends on `sheet` and cannot be lifted out alone (not wanted).
- B. Everything inside `sheet`: less wiring, but not what the user asked and `sheet` is already large.
- C. A separate app with its own web pages: duplicates sign-in, two-step, CSP and styles; two security surfaces.

## Decisions the user made

- Separate from the Vessels page (all vessels, all terminals).
- Terminals **belong to a port**; a User sees only the terminals (and their visits) of their own ports; Admins see all.
- Access through the existing ticks: four new **page** ticks and new **permission** ticks on the Accounts page.
- **Every existing account starts with the new pages off**; an Admin ticks them per person. Branch manager template
  gets them (it is "every page / every permission"); Marine and Operations templates do not.
- Approach A.

## Data

### `operation.Terminal`

| field | rule |
|---|---|
| `name` | 2–40 characters, unique ignoring case (e.g. `ACCHCO - ALX`) |
| `code` | 1–10 characters, upper-cased (e.g. `EGALY`) |
| `port` | a port key (`ports.exists`, turned on for a new terminal) |
| `quay_length` | whole metres, 1–10000 |
| `cranes` | gantry cranes, whole, 0–50 |
| `berths` | JSON list of 1–30 berth names, each 1–10 characters, unique within the terminal (e.g. `["40/1","40/2"]`) |
| `active`, `position` | like `Port`; never deleted, only turned off |

A turned-off terminal takes no new visit; its visits stay and stay editable. Removing a berth from the list does not
touch visits already on it (the saved value stays allowed, like Master data).

Managed on a new **Terminals** page in the Master data folder, **Admins only** (like Ports): list + dialog.
`GET/POST /api/operation/terminals/`, `PUT /api/operation/terminals/<id>/`. Every role that has any Operation page
reads the terminals of its ports (for filters and the Live data cards).

### `operation.Visit` (Visit ID = its `id`, shown as the number)

Typed fields (Excel columns A–N, R–S):

| field | rule |
|---|---|
| `terminal` | FK PROTECT; must be one of the person's ports (`access.require_port` on `terminal.port`) |
| `vessel_name` | required, 1–100 characters, saved upper-case |
| `shipping_line` | required; from the Master data list **Shipping line** for the terminal's port or All ports (saved value stays allowed) |
| `loa` | metres, decimal > 0, at most 500, one decimal place; optional |
| `eta` | required (date-time) |
| `ata`, `etb`, `etc`, `atb`, `atd` | optional date-times |
| `planned_berth`, `actual_berth` | optional; must be in the terminal's `berths` (saved value stays allowed) |
| `cranes` | optional whole number 1–50 |
| `discharge`, `loading` | optional whole moves, ≥ 0 |
| `version` | edit conflicts, as on Vessel (`conflicts.locked` / `bump_if_changed`) |

Times are Cairo local in the form and JSON, like the vessel times. Order rules (refused, never fixed): `atb` needs
`ata`; `atd` needs `atb`; `atb ≥ ata`; `atd > atb`; `etc ≥ etb` when both are set. Unknown keys refused (whitelist).

Worked out on read, never stored (`operation/figures.py`, one function used by every page and export):

| figure | Excel | rule |
|---|---|---|
| status | O | `Completed` if ATD, else `Working` if ATB, else `Planned` |
| waiting (hrs) | P | ATB − ATA, 1 decimal; blank without both |
| operation (hrs) | Q | ATD − ATB |
| port stay (hrs) | AH | ATD − ATA |
| total moves | T | discharge + loading; blank when both blank |
| productivity (moves/hr) | U | total moves ÷ operation hours, 1 decimal; blank without both or when hours are 0 |
| report date | A&R A20 | ATA if set, else ETA (date filters use this) |

### Shipping lines

A new Master data kind **`line`** ("Shipping line") in `sheet.constants.OPTION_KINDS`, following the Master data
page's existing rule: Admins add values for All ports (or one port); a User with **Master data** adds values for their
own port. `seed_demo` adds ARKAS, MAERSK, SOC, ICR, CUL, MCL for All ports. (Correction to what the user was told: a
User's new line belongs to their port, not to everyone; Admins make All-ports lines. This is the existing Master data
rule and keeps one rule for every list.)

## Access

- Pages (`sheet.constants.PAGES`): `op_vessels` "Vessel Data", `op_live` "Live data", `op_analysis` "Analysis
  reports", `op_charts` "Report charts". Not in any existing Profile (migration adds nothing); new accounts start
  without them; Branch manager template gets them through `PAGE_KEYS`.
- Permissions (`PERMISSIONS`, now 18): `operation.edit` "Add / edit vessel data" and `operation.delete` "Delete vessel
  data"; both need the page `op_vessels` (`PERMISSION_NEEDS`). The Accounts page's "Can" count becomes "x of 18".
- Exports: the Vessel Data **Excel** button needs `exports` + `op_vessels` (`dataexport.EXPORT_PAGE`-style).
- Scoping: every query goes through one `operation.access.scoped_visits(profile, port)` (`terminal__port__in` the
  User's ports; a `port` filter only narrows) and `scoped_terminals(profile, port)`.
- History: `Terminal` and `Visit` added to `history.TRACKED`; `visit` added to `PORT_TYPES` with its page
  `op_vessels` in `TYPE_PAGES`; `port_of` gives a visit its terminal's port. Terminal records are Admin-only in the
  History (not in `PORT_TYPES`).
- Rate limits and audit: writes through `api.json_api` (counted like every write); export rate limited with the
  exports, audit `operation.export`.

## Pages

All four follow the app's look (tokens, cards, `dom.js`, icons from the sprite) and the user's preference for
compact screens without help text. Port filter / Port column only for `ME.multiPort`.

### 1. Vessel Data (`#op-vessels`)

- Filters: port, terminal, status (tick filter Planned / Working / Completed, default all), shipping line, search
  (vessel name, literal), From–To on the report date (optional). Kept in `localStorage`.
- Table, one row per visit: ID, Vessel, Line, Terminal, LOA, ETA, ATA, Planned berth, ETB, ETC, ATB, Actual berth,
  Cranes, ATD, Status pill, Waiting, Operation, Discharge, Loading, Total moves, Moves/hr, Port stay. Sortable;
  newest ETA first; paged like the vessel list.
- **+ Add visit** (with `operation.edit`) opens the visit dialog; a row opens the same dialog (read-only without the
  permission). The dialog: Terminal first, then the berth dropdowns list that terminal's berths (the Excel's
  dependent dropdown); calculated figures shown read-only. Delete button with `operation.delete`. 409 conflicts use
  the existing conflict panel.
- **Excel** button (`exports`): a plain data-export sheet of the filtered rows (`xlsx.py`, real dates, typed and
  calculated columns).
- API: `GET/POST /api/operation/visits/`, `PUT/DELETE /api/operation/visits/<id>/`, `GET
  /api/operation/visits/export/`.

### 2. Live data (`#op-live`)

One card per active terminal of the person's ports (port filter for multi-port people), in terminal order:

- Header: name (code), quay length, berths, cranes, calls in the last 7 days (Excel Settings F: visits with ETA in
  the last 7 days including today).
- **Under operation**: visits with ATB and no ATD — Vessel, Line, Actual berth, ATB, Cranes, Discharge, Loading,
  Moves/hr (moves so far ÷ hours since ATB, answer 2 below). Every such visit, ordered by ATB.
- **Upcoming, next 7 days**: Planned visits with ETA from now (Cairo) to now + 7 days — Vessel, Line, ETA, LOA,
  Planned berth, ETB, ETC; ordered by ETA. Every such visit (the Excel stopped at 3–5 rows).
- The Excel's terminal photo is replaced by the plain card header (pictures are not used for data).
- Refreshes when opened and with a Refresh button. API: `GET /api/operation/live/`.

### 3. Analysis reports (`#op-analysis`)

- Filters (Excel row 4): port, terminal (All), berth (All, or that terminal's berths), From / To (optional, on the
  report date), shipping line (All). Shared with Report charts (`state.operationFilter`).
- Headline figures: Vessel calls, Average waiting, Average operation, Average port stay, Average productivity.
- **Terminal performance comparison**, one row per terminal in scope: Vessel calls, Avg waiting, Avg operation, Avg
  port stay, Avg LOA, Avg cranes, Avg productivity, Total moves, Berthed calls (visits with ATB).
- **Shipping line performance**: one row per shipping line (answer 1 below).
- With From and To both set: Calls per week / month / year (answer 4 below).
- Averages skip blanks; a terminal with no figure shows "—". Every visit counts (Planned, Working, Completed), once.
- API: `GET /api/operation/analysis/?port=&terminal=&berth=&from=&to=&line=` (one function, `operation/analysis.py`).

### 4. Report charts (`#op-charts`)

- The same filters and the same API response as Analysis reports.
- **Vessel calls by terminal** (bars) and **Average waiting vs operation** (two bars per terminal, hours), drawn
  with `dom.js` bars like the Dashboard's, colours from the chart tokens.

## Sidebar

A new folder **Operation** (`data-group="operation"`), right below the Marine folder, holding the four pages, each behind its own page tick; the
folder is not rendered when the person has none. The Terminals page goes in the Master data folder (Admins).

## Code layout

- `operation/` Django app: `models.py`, `migrations/`, `validators.py`, `figures.py`, `analysis.py`, `live.py`,
  `views.py`, `urls.py` (included from `config/urls.py` under `api/operation/`), `admin.py` (read-only, like the rest),
  tests `operation/tests_*.py` using `sheet.tests` helpers. Listed in `INSTALLED_APPS` after `sheet`.
- Front end stays in `sheet/static/sheet/js/` (new `pages/opVessels.js`, `opLive.js`, `opAnalysis.js`,
  `opCharts.js`, `pages/terminals.js`, `modals/visit.js`, `modals/terminal.js`) so `views.script_modules()`, the
  CSP and `tests_frontend_safety` / `tests_look` cover them unchanged. Template sections in `index.html`.
- `seed_demo`: the five terminals in **Alexandria** (ACCHCO - ALX 23/24/25, 500 m, 4 cranes, EGALY; AICT - ALX
  40/1 40/2, 350 m, 2, EGAIT; ACCHCO - DKH 96/1–96/4, 1000 m, 8, EGEDK; AICT - DKH 98/1 98/2, 500 m, 3, EGACT;
  TMT - ALX 27/28, 1200 m, 4, TMT), the six shipping lines, and demo visits: the Excel's seven completed visits moved
  to recent days, plus some Working and Planned (next 7 days) ones; a terminal in Port Said for the scoping tests.
  Demo Users other than `marine` get the new pages and permissions; `viewer` gets the pages without the edit ticks.
- Smoke test: an admin run through the four pages and the Terminals page; `alex` adds and edits a visit.
- Docs: STATUS, CLAUDE.md (an **Operation** section), README / SECURITY test counts, DEPLOYMENT (new migrations).

## Answered by the user (2026-11-25)

1. **Shipping line table: one row per shipping line** (Vessel calls, Avg waiting, Avg operation, Avg port stay, Avg
   productivity, Total moves, Berthed calls, Avg cranes, Avg LOA), narrowed by the port / terminal / berth / date
   filters; the Shipping line filter narrows it to that line. Lines ordered by vessel calls, then name.
2. **Moves/hr for Working vessels on Live data** = (discharge + loading typed so far) ÷ hours from ATB to now,
   1 decimal; blank with no moves typed or under 0.1 h. Live data only; everywhere else productivity stays total
   moves ÷ operation hours (needs ATD).
3. **A separate Operation folder** in the sidebar, right below the Marine folder (not a sub-folder).
4. **Calls per week / per month / per year** are added to the Analysis reports headline figures when both From and
   To are chosen: vessel calls ÷ (days in the range, both ends counted, ÷ 7), ÷ (days ÷ 30.44), ÷ (days ÷ 365.25),
   1 decimal. Without a full range they are not shown. Report charts does not show them.

## Left to the builder

Exact page sizes, column widths, empty-state wording, the order of tests, the dialog layout within the app's style.
