# Excel like the page, icon delete buttons, Live data today, grouped Can ticks — design

Date: 2026-11-26. Four requests from the user after trying Operation round 2.

## Why

- The downloaded Excel files "look bad": no column widths (dates show as ####), no header style, no borders, and
  columns that are not on the page. People expect the file to be the table they were looking at.
- Live data's "Next 7 days" leaves out a vessel due earlier today.
- "Delete" written on buttons is noise; an icon is enough.
- The Accounts dialog lists all 19 "Can" ticks in one block, so it is hard to give someone the Marine work, the
  Operation work, or both.

## What the user decided

### 1. Live data: Next 7 days starts today

- "Next 7 days" = not berthed (no ATB) and ETA from **today 00:00 Cairo** up to the end of the 6th day after today.
- A vessel that has **arrived (ATA) but is not berthed** is also in this list, whatever its ETA, marked **Arrived**
  with its ATA (the user chose: inside Next 7 days, not a separate list).
- Sorted by ETA. "Calls in 7 days" is unchanged.

### 2. Every Excel download shows the page's table, with the page's look

- **Columns = the page's table:** same columns, same order, same headings as the table on screen for that person
  (a column hidden on the page — money without the money ticks, Port for a one-port User — is not in the file). No
  extra columns (ids, record numbers…) that the page does not show. Values as the page shows them (status words,
  "—" for nothing is left empty, dates and times as real Excel dates), numbers as numbers.
- **Look of the page:** a title line (the page name and the date range / filters used), then the table: header row in
  bold on the page's light header colour with a line under it, thin row lines, columns sized to fit their contents,
  the header row frozen with filter arrows, status cells coloured like the page's status pills, totals row in bold
  where the page shows totals.
- **Files:** Vessels (new, below), Services, Hotels, Transport, Port closures, Garbage & Sludge, Calculations, Vessel
  Data, and **All data** (each sheet = that page's table). The **management Excel** (Dashboard) is a report, not a
  page table: it keeps its sheets and charts and gets the same look (my call).
- **Vessels:** the CSV export becomes an Excel file like the others, with an **Excel** button on the Vessels page
  (people with the Exports tick), using the page's filters. The CSV route goes.
- **How (my call):** extend the app's own Excel writer (`xlsx.py`, standard library) with the styles above, instead of
  adding a library. The user allowed an offline library, but the writer already makes safe files (text never becomes
  a formula) and charts, and needs only styles, widths, frozen header and filters — no new package to vet.
  Server-side, so nothing loads from a CDN either way.
- Each export's columns are defined once next to the page's data on the server; a test checks that every page's
  Excel headings equal the headings in that page's table (front end), so the two cannot drift apart.

### 3. Delete buttons are icons

Every Delete button (dialogs, table rows, Master data, rates, ships, customers, bookings, closures, visits, vessel
list…) shows only the **trash icon**, still red where it was red, with "Delete" as its tooltip and accessible name.
The question before deleting stays as it is.

### 4. Accounts: Can and Pages in groups, each with "All"

- The dialog groups the **Can** ticks: **Marine** (vessels, services incl. cancel / complete, documents, port
  closures, bookings, garbage & sludge, customers & ships, accounting), **Operation** (add / edit and delete vessel
  data, edit terminals and vessel list), **General** (exports, enter money, see money, history, master data).
- **Pages** grouped like the sidebar: Marine, Operation, Reports, Master data.
- Each group has an **All** tick (ticks every box of that group; shown ticked when all are), and one **All** at the
  top for everything. A tick that needs another stays disabled until that one is ticked, as now; "All" respects
  that (it ticks the needed page / permission too).
- An agent can have both groups. Templates still fill the ticks.
- Front end only (the dialog); the server's rules do not change.

## Approaches considered

- Excel: own writer + styles (chosen) vs. XlsxWriter library (allowed by the user, offline via pip; more styling
  options, but a new dependency to vet and a rewrite of the chart code).
- Arrived-not-berthed vessels: inside Next 7 days (user's choice) vs. their own list vs. left out.

## Left to the builder

Exact colours (from the light theme tokens in `app.css`), widths, the title line's wording, how the column
definitions are shared on the server.

## Not doing

A separate "Waiting" list on Live data; changing what the management Excel contains; new templates.
