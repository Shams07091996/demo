# Management Excel — design

Agreed with the user 2026-11-20: all nine sheets, option A (native Excel charts, no library). Builder check done;
the answers to its questions are marked **(builder's call)** below or written into "Where the figures come from".

## Why

The user presents the company's figures to **management** and builds the slides by hand from the app. They want one
download that holds every figure management would look at, **with the charts already made**, so a chart can be copied
into PowerPoint (as a chart, or as a picture with Paste Special) without being built in Excel.

## What

An **Excel** button on the **Dashboard** downloads one `.xlsx` workbook for the Dashboard's **From–To range and
port** (port users: always their own port). The Dashboard's OPR / agent / service filters are **not** applied: the
workbook is the whole picture of the range (builder's call: a management pack filtered by one agent would mislead;
the file says what range and port it covers).

Nine sheets, in this order, each a heading line (sheet title, range, port, "made <date time>"), a table, and — where
listed — one **native Excel chart** drawn from that table (Excel renders it; no picture files):

| # | Sheet | Table rows → columns | Chart |
|---|---|---|---|
| 1 | Summary | one row per port in range + Total → vessels, services, revenue, cost, profit (EGP); a line "Money includes hotels, transport and garbage & sludge"; a line with how many money lines used USD 1:1 because a month rate was missing (only when > 0) | column: profit per port |
| 2 | By month | each month in range (zero-filled) → vessels, services, revenue, cost, profit | line: revenue, cost, profit per month |
| 3 | By line | each OPR (sorted by revenue, high first; empty OPR as "(no line)") → vessels, services, revenue, cost, profit; then the same split by port (OPR × port rows) | bar: revenue per line (first table) |
| 4 | Profit by service | each service type, then Hotels, Transport, Garbage & Sludge → lines, revenue, cost, profit | bar: profit per service |
| 5 | Port performance | per port, then per month → vessels with times, average hours arrival→berthing (waiting), berthing→sailing (at berth), arrival→sailing (in port); delayed vessels (more than 2 h to berth, `constants.is_delayed`); then a table delay reason → vessels | column: average waiting hours per port |
| 6 | Port closures | per port → closures, hours closed, still closed (count); then per reason → closures, hours | column: hours closed per port |
| 7 | Agents | each agent (busiest first, "(no agent)" last) → arrivals, sailings, one column per service type present, total jobs | bar: total jobs per agent |
| 8 | Crew | per OPR → crew changes, on-signers, off-signers, early arrivals, broken-visa revenue (EGP), hotel nights, transfers | column: on / off signers per line |
| 9 | Garbage & Sludge | per port, then per month → garbage m³, sludge t, revenue, cost, profit (EGP) | column: garbage m³ and sludge t per month |

### Where the figures come from (one source each, no new money maths)

- **All money (sheets 1–4, 9):** the Calculations rows (`calculations.py`: services, hotel stays, transfers, garbage &
  sludge, each with `revenue_egp` / `cost_egp` / `profit_egp`) for the same range and port. Totals add the rows'
  rounded figures, so the Summary equals the Calculations page's totals for that range and port.
  This is the **full** money (user's call, 2026-11-20): the Dashboard's money (services only) is lower by the
  bookings and garbage; the Summary says what it includes.
- **Counts (vessels, services, jobs per agent):** the same rules as the Dashboard (`dashboard.py`): a Crew Change is
  one service / one job; arrival and sailing are one job each.
- **Times (sheet 5):** each vessel's own times; an average uses only vessels that have both times of that pair; hours
  to one decimal.
- **Closures (sheet 6):** closures overlapping the range (as the Port closures page lists them); hours **clipped to
  the range** (from max(start, range start) to min(end or now, range end + 1 day)); an open closure counts to now.
- **Crew (sheet 8):** Crew Change data: on- / off-signers counted per member; **early arrivals = every on-signer whose
  landing is 2+ days before the vessel date** (the alert's day rule, but *not* its other filters: someone already
  charged a broken visa still counts, and there is no 60-day look-back — management wants how often it happened;
  the broken-visa column shows what was charged) — a small counting function next to the alert's, not the alert
  itself; broken-visa revenue from the finance lines; hotel nights = sum of nights, transfers = count, of the
  bookings of the range's **vessels** (by vessel date, like Calculations, so the crew sheet agrees with the money
  sheets; nights not cut at the range edge), per vessel OPR, draft bookings included.
- **Garbage & Sludge (sheet 9):** `VesselDisposal` quantities (hidden vessels left out); money from the **Calculations
  rows** (so it adds up with the Summary). Lines without a price add 0 (as on Calculations); USD without a month rate
  is converted 1:1 and counted in the Summary's note. The Garbage & Sludge page leaves such rows out of its totals
  instead, so the two can differ only by those flagged lines.
- **Summary notes:** besides the USD-1:1 count, a line with how many garbage / sludge lines had no price (only when
  > 0), so a gap is visible.
- **"Per port, then per month" (sheets 5 and 9):** two tables: one row per port, then one row per month for everything
  in scope (months **not** split by port; choosing a port in the Dashboard narrows the whole file). The month table
  feeds the chart.

## The file

- A real `.xlsx` (Office Open XML: a zip of XML parts) written with the **standard library only** (`zipfile`,
  `xml.sax.saxutils.escape`) — the user refuses outside libraries; same rule as the PDFs.
- Numbers are stored as numbers (money with 2 decimals and thousands separators, hours with 1, counts as integers);
  text as inline strings, escaped; heading row bold; column widths set; first row frozen optional (builder's call).
- **Formula injection:** a text cell is never a formula (inline string type); values starting with `= + - @` stay
  text. No external links, no macros (`.xlsx`, not `.xlsm`).
- Charts: one DrawingML chart per sheet (bar / column / line), referring to that sheet's own cell ranges, placed to the
  right of the table; title = the sheet's subject. A sheet with no data shows "No data" and no chart.
- File name: `Management <port or All ports> <from> to <to>.xlsx` (cleaned like the LOG's names).
- Must open without a repair prompt in Excel (Microsoft 365) and LibreOffice; checked by hand once before merge.

## Rules

- `GET /api/dashboard/export/?from=&to=&port=` (dates required; range at most 24 months — refuses "Choose a range of
  at most 24 months."), every role (read-only users see all money, user's decision), scoped with
  `access.scoped_vessels` / `scoped_closures`, rate limited with the exports (`ratelimit.check(request, "export")`),
  audit entry `dashboard.export`. Not recorded in the History (it changes nothing).
- Front end: an **Excel** button in the Dashboard filter bar (icon `file`), downloading through `api.download()` like
  the LOG / receipt; no help text (user's taste).

## Approaches

1. **Our own `.xlsx` with native charts (picked):** ready-made charts that management sees in Excel and that paste into
   PowerPoint as a chart or a picture; no dependency.
2. Picture files (SVG) of the charts in a zip with the workbook: not editable, Office 2016 and older can't open SVG.
3. PNG pictures: without a library every letter would be drawn pixel by pixel — blurry, much work.
4. CSV files (zip): nine files, locale problems (dates, Arabic, numbers as text). Rejected.
5. openpyxl: easier, but an outside package (user's rule) and the hash-locked requirements.

## Non-goals

No PowerPoint file, no scheduled e-mailing, no comparison with a previous period, no per-agent or per-service filter
on the file, no Arabic sheet names, no picture export.

## Left to the builder

- Exact chart styling, colours (Excel defaults are fine), sizes and positions.
- Splitting the code: suggested `sheet/xlsx.py` (generic writer: sheets of rows + charts → bytes) and
  `sheet/report.py` (the nine tables from the existing modules).
- Sorting inside tables where not stated (ports in `PORTS` order; months ascending).
