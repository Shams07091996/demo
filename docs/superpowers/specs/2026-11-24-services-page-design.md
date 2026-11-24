# Services page (in-progress work list) — design

Date: 2026-11-24. Second of the three pieces agreed on 2026-11-24 (ships & customers → **this** → accounts &
permissions). Approved approach: **A**.

## Why

Operators open it **every day as a to-do list** of the services still being worked on; managers use it to see
**what is still missing**. Today the only traces are the amber "N in progress" tag on a vessel row, the Status filter
on Calculations (money lines, inside a date range) and the Dashboard counts: nothing lists every open service across
all dates with what is missing.

## Goals

- One sidebar page listing **services** (not vessels or money lines), across all dates unless a range is chosen.
- **Filters, not tabs** (the user's call): Status tick boxes (In progress / Completed / Cancelled; opens with **In
  progress** only), a **Missing details only** tick, From–To, service type, agent, vessel-name search, port (admins).
- Each row says **what is missing** and marks **Sailed** when the vessel has sailed but the service is still open.
- Clicking a row opens the **existing service dialog** (edit roles); read-only roles get the vessel's dialog.
- A **Completed** view: tick only Completed and set a range → what got done in that range, with when it was done.
- An **Excel** export of every row the filters show (the user asked for it), like the other pages' Excel buttons.

## Non-goals / anti-goals

- No tabs (the user replaced them with filters).
- No new workflow data (no due dates, no "waiting for" notes, no assignment to a person).
- Not a second Calculations page: no money totals; cost / revenue only decide "missing".
- Never slows the existing pages: the list has its own endpoint; nothing is added to the vessel list query.

## Approaches (considered)

- **A. New services list on the server** — `GET /api/services/`, own module, one migration, one page. **Chosen**:
  the only one that is right across all dates without touching the other pages.
- B. Reuse Calculations rows — they are money lines (hotels, transport, garbage too), range-bound, and don't know
  what is missing; bending it would hurt both pages.
- C. Filter in the browser from the vessel list — slow with many vessels and breaks paging.

## Design

### Data: when a service was completed

- New `Service.completed_at` (DateTimeField, null). Migration **0022**: existing services stay null.
- Set by the server, never by the payload: when a save makes the status `completed` and it wasn't before (create
  included) → now; when the status leaves `completed` → null; otherwise unchanged. Done where the service is saved
  (the status is already cleaned by `validators.clean_service_status`).
- History records it like any field. It changes only together with `status`, so it adds nothing new to edit
  conflicts; the History page shows it.
- Display: "Completed" column = `completed_at` (Cairo date-time); for services completed before 0022 (null), the
  vessel date, marked as such (e.g. "≈ 23.11.2026"; exact wording left to the builder).

### What "missing" means (per service, never for Cancelled)

In this order, as short labels:
1. **Agent** — `Service.agent` empty.
2. **Cost** — a cost box of the service was left **empty**. **A typed 0 counts as filled in** (the user's
   decision, option B: so "this one costs nothing" can be said and leaves the list). Read from the stored
   `Service.data` per service type (empty / absent = missing), not from `finance.service_lines`, which drops 0
   lines. Multi-entry types: any entry with an empty cost. Which boxes each type has is the builder's mapping,
   following `clean_service_data` (e.g. Cash to Master's revenue is its percentage or fixed share).
3. **Revenue** — the same for the revenue boxes.
4. **Rate** — a line is `rate_missing` (USD with no own rate and no month rate).
5. **Bookings** — Crew Change only: one of its crew's bookings (linked by `Guest.crew_uid`, as
   `crewbookings.saved_bookings` / drafts do) is incomplete in the same sense as `crewbookings.booking_gaps`
   (draft, or no cost / revenue), not cancelled. Unlike the alert, **not** limited to sailed vessels.

**Sailed** (shown only while In progress): sailing time has passed, or no sailing time and the vessel date is before
today (Cairo) — the rule `booking_gaps` uses.

### API: `GET /api/services/`

- `json_api`, every role; vessels only through `access.scoped_vessels(profile, port)` (port users pinned to theirs).
- Query: `status` (comma list of in_progress / completed / cancelled; empty items ignored; unknown → 400; default
  `in_progress`), `missing=1`, `from` / `to` (ISO dates, optional), `type` (a SERVICE_TYPES value, unknown → 400),
  `agent` (exact; `__none__` = empty agent, as on the Dashboard), `q` (literal, case-insensitive, on the vessel
  name), `port` (admins), `page`, `page_size` (10 / 25 / 50 / 100, like the other pages).
- **Date range**: on the vessel date; **when the status filter is exactly `completed`, on the completed date**
  (`completed_at` in Cairo time, else the vessel date).
- Rows: `{id, vessel {id, name, date, port}, type, agent, status, cancel_reason, completed_at, completed_guess,
  sailed, missing: [...], billing, billing_party}`; plus `count`, `pages`, `page`, and `agents` (the agents present
  for the dropdown, like Calculations' `oprs`).
- Order: vessel date oldest first, then id (operators work oldest first). When the status filter is exactly
  `completed`: completed newest first.
- The database narrows by port, status, type, agent and (vessel) date; missing / sailed / completed-date filters and
  paging run in Python (as `listing.py` does), computing each candidate service's money lines once. Prefetch so the
  list is a fixed number of queries.

### Page (front end)

- Sidebar item **"Services"** right after Vessels (my call), page `js/pages/services.js`, built with `dom.js` only.
- Filter bar: the Status tick filter (same component as Calculations' `tick-filter`), "Missing details only" tick,
  From–To (its own, **empty by default** — not the shared vessel range, since a to-do list spans all dates), Type,
  Agent, Search, Port (admins), **Excel** button. The chosen filters are remembered in this browser only
  (`localStorage`, wrapped in try/catch; a broken store just starts from the defaults).
- Table: Vessel, Date, Service, Agent, Status (the existing status label), Completed (only shown when Completed is
  ticked), Missing (labels), plus a "Sailed" amber mark. Pager 10 / 25 / 50 / 100.
- A row click (edit roles) opens the vessel's service dialog (`ensureVessel`, then `openServiceForm` for that
  service). **After a save or delete started from this page, the dialog closes and the reloaded list shows** (my
  call: it is a to-do list; from the Vessels page the dialog still goes back to the vessel as today).
- **Read-only roles** (my call): a row click opens the vessel's dialog, which they can already see (service cards
  without Edit). No new read-only mode of the service form is built.
- Empty state: one short line (the user likes minimal screens: no help text, no stat cards).

### Excel export

- `GET /api/export/services/?<the page's list query>` through the existing data-export path (`dataexport`): one
  header row, one row per service, every page of the filtered list, numbers as numbers, real dates. Every role;
  port users only their port; rate limited with the exports; audit `data.export` (which filters, not their values).
- Columns: Service id, Vessel id, Vessel, Port, Vessel date, Service, Agent, Status, Cancel reason, Completed,
  Sailed (Yes / No), Missing (labels joined with ", "), Billing party, Billing.
- **Not** added to the Dashboard's "All data" file (its five sheets stay as they are; my call).

## Constraints

- Project rules in `CLAUDE.md`: `json_api`, scoped queries, validators refuse bad input (unknown status / type / page
  size → 400), money only from `finance.py`, screens only via `dom.js`, CSP, LF line endings, docs updated
  (STATUS / CLAUDE / README / SECURITY counts).
- Tests first; `npm run check` green; smoke test extended for alex / admin / viewer / suez.

## Left to the builder

Exact wording of labels and the "completed before tracking" marker, CSS, how the Status tick component is shared with
Calculations, query shape as long as it stays a fixed number of queries.
