# Data export (Excel) — short design

Date: 2026-11-24. Branch: `feature/data-export` (from `main`). Approved by the user ("yes, write it up").

## Why

The user wants "every row in all the pages … in an external excel file as we will need them for other programs":
Hotels, Transport, Port closures, Garbage & Sludge and Calculations. Management needs all of them together; teams
such as accounting need one page at a time ("do both"). (Recorded first on 2026-11-23 as an "Excel import"; the user
meant an export.)

## Goals, non-goals

- Goals: plain tables another program can read: one header row, one row per record, real numbers and real dates.
- Non-goals: no import; no titles, totals, notes, charts or "No data" in these files (that is the management Excel,
  which stays as it is); no new library.
- Anti-goals: a file whose shape changes with the data (a program reading it would break); anything a port user may
  not see; a text cell that Excel would run as a formula.

## Approaches

- **Build on the app's own `xlsx.py` writer** (chosen): standard library only, text always written as inline strings
  (never formulas), already used and tested by the management Excel.
- CSV files: as easy, but the user asked for Excel, and CSV loses the types (dates, numbers) and the five-sheet file.
- openpyxl: an outside package for something the app already does.

## Design

**One file per page** (for accounting and others): an **Excel** button on Hotels, Transport, Port closures, Garbage &
Sludge and Calculations downloads exactly what that page's filters show now — every matching row, not only the page
on screen. One sheet named after the page.

**All data** (for management): a button beside the Dashboard's Excel button; From and To required, at most 24 months
(like the management Excel), the Dashboard's port. One file, five sheets (Hotels, Transport, Port closures, Garbage &
Sludge, Calculations), each in the same columns as its single-page file, rows in that date range as each page reads it
(stays covering a night in it, trips on a day in it, closures overlapping it, vessel dates for the other two).

**Columns:** each page's own columns, plus the vessel id and the row's own id so programs can join the files. Money as
numbers with the currency in its own column; dates and times as real Excel dates. Hotels / Transport: one row per
booking, the guests' names in one cell separated by "; ". Calculations: status, cancellation reason and Open / Closed
included. The header row is the same in every file whatever the data; an empty result is the header row alone.

**Rules as everywhere:** every role may export; port users only their own port (`access.scoped_vessels` /
`scoped_closures`); rate limited with the other exports; each export recorded with `api.audit`.

## Left to the builder

Exact column names and order per sheet (follow each page's labels), the button placement on each page, the file
names (page + date), and how the page passes its current filters (the same query string as its list request).
