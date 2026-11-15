# Project status

Last updated: 2026-11-16. Read this with `CLAUDE.md` before starting work. Each feature has a design (`docs/superpowers/specs/`)
and a build plan (`docs/superpowers/plans/`) that record what was decided and why.

## Built and tested

| When | What | Design |
|---|---|---|
| 2026-11-15 | Security fixes: exchange rates admin-only; debug mode off unless `DJANGO_DEBUG=1`; audit-log values escaped | — |
| 2026-11-15 | Vessel list served by the server: From–To date range (this month by default), search, ARK / MSK / Other chips, sorting, paging 10 / 25 / 50 / 100; Dashboard, OPR summary, alerts and CSV from the server; "Saved — … outside the current date range" notice with **Show it** | `2026-11-15-server-side-vessel-list-design.md` |
| 2026-11-15 | Vessels page trimmed at the user's request: no stat cards, no CSV button, no Total Cost column, smaller chips, a 🗑 Delete button per row (click a row to edit) | — |
| 2026-11-15 | Bulk add: editable preview table (edit cells, live checks, add / remove rows, "Set on all rows", server duplicate check); help text and placeholders removed | `2026-11-15-bulk-add-editable-preview-design.md` |
| 2026-11-15 | ☰ hides / shows the sidebar on wide screens; alerts banner can shrink to one line; dev `runserver` sends static files with `no-cache` | — |
| 2026-11-16 | 🏨 Hotels and 🚗 Transport pages: bookings for 1–6 crew guests of a vessel, rooms and cars can be shared, prices stored for a future calculations page and hidden from read-only users; transfers name which airport / hotel / port (Master data lists) | `2026-11-16-hotels-and-transport-design.md` |

Tests: `python manage.py test sheet` → 130 OK; `tools` parser tests and the jsdom smoke test pass for `admin`, `alex`,
`viewer` (see `CLAUDE.md` for how to run the smoke test on a throwaway database).

## Next (agreed with the user)

- **Calculations page** (dedicated page for money). It should read the prices already stored on hotel stays
  (`price_per_night` per room, × nights) and transfers (`price`), with `currency` and optional `exchange_rate`
  (else the vessel's month rate, as services do). Hotel / transport money is deliberately **not** in vessel totals,
  the Summary of services or the Dashboard. Not designed yet: start with brainstorming.

## Left open — small things the user hasn't decided on yet

Vessel list:
- The outside-range notice also shows for edits that didn't change the date.
- The default month and "Today / Tomorrow" labels use the browser's clock, not Cairo's.
- Sorting by Port uses the port key, not its label.
- The vessel cache can show figures another user changed, until reload.
- SECURITY.md claims the tests also run on PostgreSQL 16; the newer ones have only run on SQLite.

Bulk add:
- The 200-row limit message is above the table, out of view of "+ Add row".
- Server error row numbers count only the rows sent, not the table's numbering.
- Removing the last row hides "+ Add row" until Preview.
- "Date is missing." no longer hints at the default date.

Hotels and Transport:
- An EGP booking keeps a hidden exchange rate if one was typed while USD was selected.
- A crafted `nights` value (e.g. "²") gives a 500; the dialog never sends one.
- An exchange rate like 999999.99999 overflows the database column on PostgreSQL.
- The 60-night cap is checked by the app but not on the model (the Django admin could store more).
- Transfer time pre-fill uses arrival (on-signers) / departure (off-signers) regardless of direction.
- Booking table headers sort but don't look clickable.
- The dialog's vessel search also matches OPR / POC / agent, not only names.
- `seed_demo` writes the flight month with the machine's locale.
- Test gaps: transfer cross-port access; read-only detail GET without prices.

## Operational notes

- The user's own `db.sqlite3` must be migrated after pulling these changes (`DJANGO_DEBUG=1`, `python manage.py migrate`).
- After front-end changes, a browser that cached old modules may need one hard refresh (Ctrl + Shift + R).
- The folder is not a git repository; there is no history. Putting it under git was recommended to the user.
