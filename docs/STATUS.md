# Project status

Last updated: 2026-11-17. Read this with `CLAUDE.md` before starting work. Each feature has a design
(`docs/superpowers/specs/`) and a build plan (`docs/superpowers/plans/`) that record what was decided and why.

## Where things stand right now

- **Git branches:**
  - `main` — everything up to and including the 💰 Calculations page.
  - `feature/master-data-per-port` — **checked out**, built, reviewed and tested, **not merged yet**. The user was
    last asked whether to merge it into `main`; do it only when they say so (`git switch main` +
    `git merge --ff-only feature/master-data-per-port`). No migration needed. The docs on this branch (this file,
    `CLAUDE.md`, `README.md`) are newer than `main`'s.
  - `feature/calculations-page` — already merged; can be deleted (`git branch -d feature/calculations-page`).
- **The user's own database** (`db.sqlite3`, not in git) is up to date: migrations through `0008` are applied.
  It still has one **shared** agent and one shared hotel from before per-port Master data; once the branch is merged,
  an admin can move them to a port on the Master data page.
- **Tests (on the branch):** `python manage.py test sheet` → 150 OK; `tools` parser tests pass; the jsdom smoke test
  passes for `admin`, `alex`, `viewer` and the short `suez` run (see `CLAUDE.md` for the throwaway-database setup).

## Built and tested

| When | What | Design |
|---|---|---|
| 2026-11-15 | Security fixes: exchange rates admin-only; debug mode off unless `DJANGO_DEBUG=1`; audit-log values escaped | — |
| 2026-11-15 | Vessel list served by the server: From–To date range (this month by default), search, ARK / MSK / Other chips, sorting, paging 10 / 25 / 50 / 100; Dashboard, OPR summary, alerts and CSV from the server; "Saved — … outside the current date range" notice with **Show it** | `2026-11-15-server-side-vessel-list-design.md` |
| 2026-11-15 | Vessels page trimmed at the user's request: no stat cards, no CSV button, no Total Cost column, smaller chips, a 🗑 Delete button per row (click a row to edit) | — |
| 2026-11-15 | Bulk add: editable preview table (edit cells, live checks, add / remove rows, "Set on all rows", server duplicate check); help text and placeholders removed | `2026-11-15-bulk-add-editable-preview-design.md` |
| 2026-11-15 | ☰ hides / shows the sidebar on wide screens; alerts banner can shrink to one line; dev `runserver` sends static files with `no-cache` | — |
| 2026-11-16 | 🏨 Hotels and 🚗 Transport pages: bookings for 1–6 crew guests of a vessel (rooms and cars can be shared), entered on their own pages with the guest picked from the vessel's crew change; transfers name which airport / hotel / port (Master data lists) | `2026-11-16-hotels-and-transport-design.md` |
| 2026-11-16 | 💰 Calculations page: every money line with its working (amount × rate = EGP) for a vessel-date range / OPR / port, one totals line; every service (Crew Change and Others too) and every booking has cost and revenue; one money-maths source (`finance.service_lines`), amounts rounded to the cent once | `2026-11-16-calculations-page-design.md` |
| 2026-11-17 (branch, unmerged) | Master data per port: every list's values belong to one port or All ports (admins choose and can move them); every dropdown offers the item's port + All-ports values | `2026-11-16-master-data-per-port-design.md` |
| 2026-11-16 | Project put under git; `CLAUDE.md` and this file written for future sessions | — |

## Decisions the user made (respect these)

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
- **Master data:** every list (OPR, POC, Agent, Hotel, Airport, Port) can be per port; admins choose (default All
  ports) and can move values; port users' values are their port's.
- **UI taste:** lean screens — no help paragraphs, no placeholders, no stat cards; compact controls.
- **Process:** the user chooses **Native** execution (built in-session, one fresh reviewer at the end).

## Next

- Merge `feature/master-data-per-port` into `main` (waiting for the user).

Ideas raised along the way:

- Run the test suite on the user's local PostgreSQL 17 (installed at `C:\Program Files\PostgreSQL\17`, not on PATH;
  the user must create the app's database role first — see README "PostgreSQL"). New tests have only run on SQLite.
- Exports of the Calculations page.

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
- The dialog's vessel search also matches OPR / POC / agent, not only names.
- `seed_demo` writes the flight month with the machine's locale.
- Test gaps: transfer cross-port access.

Master data per port:
- A PATCH without a `port` key moves the value to All ports (the page always sends one).
- Two admins moving the same value at once could hit the unique rule (500 instead of the duplicate message).
- The audit line for a move records the new port only.
- Changing the bulk-add port redraws the table, dropping any unapplied "Set on all rows" choices.
- Bulk add's "not in Master data" warning counts values of any port.
- The server does not check that a vessel's OPR / POC / Agent belongs to its port (only the dropdowns filter).

Calculations:
- Cash to Master no longer flags "no exchange rate" when only the amount handed to the master is in USD (share 0%);
  the live preview still flags it.
- The "Item" column sorts by service type, not by the label shown.
- The Summary hides the profit banner when no service has money (it used to show 0.00).
- Migration 0008 updates bookings one at a time (fine for the few rows that exist).
- Bookings migrated from a single price show only a cost, so they appear as a loss until a revenue is entered.

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
