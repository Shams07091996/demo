# Visit "Save and add another", Reports folder, Live data Excel, Dashboard Customers / OPR / Money, Calculations cards

Date: 2026-11-26. The user's eight points of 2026-11-26 (with the workbook `ARKAS_Port_Berthing -2.xlsx`), agreed in
chat. Three pieces, each on its own branch, built in this order, merged only with the user's OK:

1. **Operation extras** (`feature/operation-extras`): points 1, 2, 3, 6.
2. **Dashboard: Customers, OPR, Money** (`feature/dashboard-money`): points 5, 7, 8.
3. **Calculations as cards** (`feature/calculations-cards`): point 4.

## Why

The user works from the app instead of the workbook: entering many visits in a row, reading the reports in one
folder, sending a per-terminal Live data file, and seeing what each customer / service is worth. Success = they no
longer need the workbook's Dashboard sheet, and the Dashboard answers "how much from each service / each customer".

Anti-goals: no stat cards, help text or placeholders (the user strips them); no new library; the Dashboard's job counts
and the Calculations page's money must never disagree with the rest of the app.

## Approaches (picked in chat)

- **Report charts and the Dashboard (point 3):** merge into one page, or keep them apart. **Kept apart** (my
  recommendation, the user: "ok"): Report charts counts every vessel at every terminal, the Dashboard only the
  vessels and services we do; on one page the numbers would seem to disagree. Report charts moves to Reports beside
  Analysis reports.
- **Money view (point 8):** A. one screen with totals, by service, by customer and per month, all narrowed by the
  filters; B. one table with a "Group by" switch. **A picked** by the user.
- **Pictures in the Live data Excel (point 6):** leave them out, or place the terminal's picture with the app's own
  writer. **Placed** (the user asked what could be done; no library needed).

## Piece 1: Operation extras

### Visit dialog: Save and add another (point 1)

- A new visit's dialog has a second button **Save and add another** beside Save (not on an existing visit, not
  without `operation.edit`).
- After a successful save, a fresh **Add visit** dialog opens with **only the terminal kept** (the user's words: "only
  keep the terminal"); everything else empty; the Vessel Data list behind it reloads. On an error the dialog stays
  as it is (as Save does).

### Analysis reports and Report charts in Reports (points 2, 3)

- The sidebar items **Analysis reports** and **Report charts** move from the Operation folder into the **Reports**
  folder (after Calculations). Page keys (`op_analysis`, `op_charts`), permissions and the Accounts ticks are
  unchanged; only `index.html`'s nav and the two folders' `{% if %}` lines change (the Reports folder now also shows
  for someone with only those pages). The router opens the folder of the page on screen, as now.
- In the Accounts dialog's Pages ticks (`js/tickGroups.js`, grouped like the sidebar), the two pages move to the
  Reports group too (my call: the ticks follow the sidebar). `tests_permissions.TickGroupsTwinTests` still holds.

### Live data Excel, one sheet per terminal (point 6)

- **Excel** button on Live data (with `exports`), `GET /api/operation/live/export/?port=&terminal=`: the page's
  port filter, and its All / one-terminal choice (`terminal` empty = every card on screen). Needs the `op_live` page
  and `exports`; rate limited with the exports; audit `live.export`; file name like the other exports
  (`live-data-YYYY-MM-DD.xlsx`, a one-port User's port in it like the others).
- Built from `live.response` (same vessels as the page, same moment `now`), so the file equals the screen.
- **One sheet per terminal** (sheet name = terminal code, made safe / unique by `xlsx.safe_sheet_name`), laid out
  like a block of the workbook's Dashboard sheet, with the app's Excel look (`xlsx.table_sheet` style):
  - Title (bold 14): `ACCHCO - ALX | Berth No. 23 / 24 / 25 | Quay 500 m | Gantry Cranes: 4` (terminal name,
    berths joined " / ", quay length, cranes; a part with no value left out), then a muted line `Live data ·
    <Cairo date and time> · Calls in 7 days: N`.
  - The terminal's **picture** (when the server has one, `pictures.py` rules) below the title, scaled to the sheet
    width keeping its shape; the tables start under it.
  - **Under operation** (bold line), table: Vessel, Line, Actual berth, ATB, Cranes, Discharge, Loading, Moves/hr
    (the page's live rate). "No vessels" when empty.
  - **Next 7 days** (bold line), table: Vessel, Line, ETA, LOA (m), Planned berth, ETB, ETC, Status (Arrived /
    Overdue coloured like the page's chips, else "—"). "No vessels" when empty.
  - Times as `xlsx.Moment` (Cairo), numbers as numbers, "—" for empty, fitted widths.
- A terminal with no vessels still gets its sheet. No terminal → one sheet "No data".
- **Pictures in `xlsx`:** a new `xlsx.Picture(data, kind, width, height)` on `Sheet.pictures`, written into the same
  drawing part as charts (`xl/media/imageN.png|jpeg`, its relationship, a `xdr:pic` one-cell anchor, the content
  type). Width / height come from the file's header (PNG IHDR; JPEG SOF), read the same way `logpdf` reads JPEGs; a
  file whose size can't be read is left out. No library.
- `tests_page_excel`: the Live data cards are not a table, so its headings are the workbook's, not the page's; the
  export's two heads are kept in `operation/live.py` and tested there.

## Piece 2: Dashboard — Customers, OPR, Money

### A Customer filter (points 5, 8)

- New **Customer** dropdown in the Dashboard filters (`d-customer`, `state.dashboardFilter.customer`): the customers
  with jobs in the range + port, plus "(no customer)" (`__none__`). It narrows **every view** to the jobs counted
  for that customer (the Customers view's rule: a service's billing party, else the ship's customer; arrivals /
  sailings the ship's customer) and, on the Money view, the money lines charged to it. Server param `customer=`
  (id or `__none__`; unknown id 400) in `dashboard.parse` and the money endpoint. My call: it applies everywhere
  rather than only on two views, so a set filter never shows numbers that ignore it.

### Customers view: services per customer (point 5)

- The view gets a new first panel **Services per customer**: one row per customer (same order as Jobs per customer,
  "No customer" last), columns Arrivals, Sailings (left out while a service filter is set, as on Agent jobs), each
  service type present, Total; a bold Total row. Port, service and customer filters narrow it like everything else.
- Server: each `customers` entry gains `arrivals`, `sailings`, `by_type` (counts). The two existing panels stay.

### OPR view: figures only (point 7)

- Remove the **Total cost (LE) per OPR** and **Profit (LE) per OPR** charts and the "LE cost" line of each OPR card.
  The OPR table and cards keep vessels / services / service counts. `oprs` in the response loses `cost_egp` /
  `profit_egp` (and `moneyaccess.dashboard_out` stops stripping them). The management Excel is unchanged (it has its
  own money sheets).

### Money view (point 8)

- New tab **Money** (after Overview), only with `money.view` (template leaves the tab and panels out otherwise; a
  remembered `money` view without it falls back to Agent jobs).
- `GET /api/dashboard/money/?from=&to=&port=&opr=&service=&agent=&customer=` (`dashboard` page + `money.view`; the
  same read rate rules as `/api/dashboard/`). Money comes **only from `calculations.rows_for`** of the vessels in
  range + port (+ OPR), so it equals the Calculations page: services, Hotel stay, Transfer, Garbage & Sludge lines.
  - Each line's **customer**: a service line's billing party, else (hotel / transfer / garbage) the vessel's ship's
    customer, else "No customer".
  - `service=` keeps lines of that kind (a service type, or `Hotel stay` / `Transfer` / `Garbage & Sludge`);
    `agent=` keeps service lines whose service has that agent (bookings / garbage dropped), `__none__` = no agent;
    `customer=` as above.
  - Response: `totals {revenue_egp, cost_egp, profit_egp, lines, rate_missing_lines, price_missing_lines}`,
    `by_service [{kind, revenue_egp, cost_egp, profit_egp, lines}]` (service types in their usual order, then Hotel
    stay, Transfer, Garbage & Sludge; only kinds present), `by_customer [{id, name, …same}]` (highest revenue first,
    "No customer" last), `months [{month, …same}]` (zero-filled between the first and last month), `kinds` (for the
    dropdown). Rounded to the cent once per sum.
- Page (view `money`, loaded when the view is on screen and on every filter change while it is):
  - One-line headline (like the other views, no stat cards): "Revenue 1,250,000 LE · Cost 900,000 LE · Profit
    350,000 LE" plus "· N lines without a rate" when any.
  - **By service**: bars of revenue per kind and a table Service / Revenue / Cost / Profit / Lines with a Total row
    (negative profit red).
  - **By customer**: table Customer / Revenue / Cost / Profit / Lines with a Total row.
  - **Per month**: the "Money per month (LE)" table **moves here from Overview** (Cost / Revenue / Profit rows ×
    months, total column), now from the money endpoint (so it includes hotels / transport / garbage).
  - While the Money view is on screen the Service dropdown also offers Hotel stay, Transfer, Garbage & Sludge; leaving
    the view with one of those chosen clears the service filter.
- Overview keeps Services per month and Service status.

## Piece 3: Calculations as cards (point 4)

- Like the Services page: one **card per vessel** that has lines in the filters: name (opens the vessel summary as
  today), date, OPR, port (multi-port people), "N lines", Revenue · Cost · Profit (LE), a warning icon when a line
  has no rate / price. A click (`calc-toggle`) opens it to **line cards**: item label (+ note, rate / price warnings),
  Cost and Revenue with their working (today's `sideCell`), Profit LE (+ USD), status pill + cancel reason, billing
  party · billing, and the Open / Closed switch (same `acct-toggle`).
- Filters, tick boxes and the totals line stay as they are; the totals still cover every filtered line.
- Server: `calculations.response` returns `vessels: [{vessel, rows, cost_egp, revenue_egp, profit_egp, lines}]`
  **paged by vessel** (`count` = vessels, `lines` = lines), like `services.grouped`. Sort applies to vessels: date,
  vessel, OPR, port, cost / revenue / profit (the vessel's sums); ties newest vessel first; lines keep their order.
  The `kind` sort goes (400 "Unknown sort." like any other).
- The Excel stays one row per line (`dataexport` unchanged); `calculations.js` keeps an exported `COLUMNS` list of the
  export headings so `tests_page_excel` still compares them.
- Which vessels are open is kept while paging / reloading (like Services), not stored.

## Left to the builder

Exact CSS (reuse the Services page's `sv-` card styles), test names, the picture's row reservation in the Excel,
the order of panels inside a view.

## Docs

STATUS, CLAUDE.md (Dashboard, Calculations, Live data, xlsx, Operation folder), README / SECURITY test counts,
NEXT-CHAT; the smoke test's Calculations / Dashboard / Live data steps updated with each piece.
