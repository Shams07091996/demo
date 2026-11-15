# Bulk add: editable preview

Date: 2026-11-15 · Size: small change (front end only) · Status: draft for approval

## Why
When bulk adding, the user wants to fix data on the fly (a date, an OPR, a name) without going back to the pasted
text and pressing Preview again. Today the preview is read-only.

## Goals
- After Preview, every row is editable in place: name (text), date (date picker), OPR / POC / Agent (Master-data
  dropdowns).
- Per row: a live ✓ / ⚠ / ✗ check and a 🗑 remove button. "+ Add row" adds a blank row.
- "Set on all rows": pick a date, OPR, POC and/or Agent and apply it to every row at once.
- "Create N vessels" sends exactly what the table shows.

## Non-goals
- Pasting directly into the grid like Excel (approach B). Changes to the server; the existing bulk create and
  bulk check endpoints are reused.

## Approaches
| | What | Trade-off |
|---|---|---|
| **A. Editable preview (chosen)** | Paste → Preview → the preview table is editable | Keeps the paste flow; medium change |
| B. Spreadsheet grid | Type or paste straight into a grid | Most Excel-like; multi-cell paste is fiddly; biggest change |
| C. Live text preview | Preview redraws as you type in the text box | Smallest; still editing raw tab-separated text |

The user picked **A**.

## Design
- **Pasting** works as today (same columns, date formats, defaults, header row ignored). Preview turns the lines into
  table rows. If rows were already edited, pressing Preview again asks "Replace the rows below with the pasted
  text?" first. *(my call: so edits aren't lost by accident.)*
- **Checks per row, live as you edit:** name required; valid date required; OPR / POC / Agent not in Master data → ⚠
  (the value is kept and shown as an extra option in its dropdown); same name + date twice in the table → the later
  one is ⚠ skipped; already saved in the target port → ⚠ skipped (server check, re-run 300 ms after edits stop and
  when an admin changes the bulk port). *(the port re-check fixes a reviewer finding.)*
- **Create** stays blocked while any row has ✗; ⚠-skipped rows are left out; the button says how many will be
  created. After creating, the table clears and "View them" works as now. Limit stays 200 rows, counting added rows.
- **Set on all rows** sits above the table; empty choices are ignored; it overwrites that column on every row.
  *(my call: overwrite, not "only empty cells" — that is what "set" suggests.)*
- **Escaping:** every value goes into inputs via `value` / escaped attributes, never raw HTML.
- **Read-only users** still never reach the Bulk add page.

## Left to the builder
Exact markup and CSS within the existing styles; how row state is held (likely the existing `rows` array in
`pages/bulk.js`, edited in place and re-rendered per row).

## Testing
Smoke test: paste → preview → change a date and an OPR in the table → fix a ✗ row → remove a row → add a row →
"Set on all rows" agent → create → vessels have the edited values; duplicate check re-runs after a name edit and
after an admin changes the port. Parser unit tests stay green.
