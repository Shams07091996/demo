# Server-side vessel list with a From–To date range

Date: 2026-11-15 · Status: draft for approval

## Why

Today the page downloads **every** vessel the user may see (with all services and their money figures) in one
request, and the table, stat cards, Dashboard, OPR summary, alerts and bulk-add duplicate check all work on that
in-memory list. That is fine for a handful of vessels and gets slow as the history grows. The user wants:

1. a **From – To date range** to find vessels, and
2. **the data to come from the server**: the server filters, pages, sorts and totals; the browser only shows what it
   gets back.

Success: the vessel table loads one page at a time, filtered by date range and the existing filters; every total on
screen (stat cards, Dashboard, OPR summary) is computed by the server for the chosen range; nothing a user can see
changes in who-may-see-what.

## Goals

- From / To date inputs on the Vessels page and the Dashboard, filtering on the vessel's **date** field (inclusive at
  both ends). Either end may be empty (open-ended); both empty = all dates.
- Server-side search, OPR chip (ARK / MSK / Other / With services), port filter, sorting and pagination.
- Stat cards show totals for **everything matching** the filters (not just the visible page), computed by the server.
- Dashboard charts and OPR cards come from a server endpoint for the chosen range and port.
- OPR summary, today/tomorrow alerts and bulk-add duplicate check keep working without the full list in memory.
- CSV export exports everything matching the current filters.

## Non-goals

- Filtering on port-call times (arrived / berthed / sailed). The range is on the vessel date only.
- Preset buttons ("last 7 days", "this year"), saved filters, filters in the URL.
- Infinite scroll. Plain page controls only.
- Changing the money maths, roles or the data model beyond an index.

## Anti-goals (would make this a failure even if it works)

- A port user can see, count or total another port's vessels through any new endpoint or parameter.
- A total on screen disagrees with what the server would compute (e.g. the browser summing only the current page).
- Every keystroke in the search box fires a request.
- After editing a vessel or service, the table or totals show stale figures.

## Constraints (from the existing project)

- Django 5.2 + vanilla ES modules, no build step, no third-party scripts (strict CSP `script-src 'self'`).
- All access goes through `access.scoped_vessels(profile, port)`; port users are pinned to their own port.
- Money per service is computed in Python (`finance.compute`) from JSON data with per-service currency and exchange
  rate, so totals **cannot** be summed in the database. The server must compute figures for every matching vessel to
  produce totals and to sort by total cost.
- Front-end escaping rules (`esc()`), the `json_api` decorator, audit logging and the CSV formula-injection guard stay.
- Existing tests (77) must keep passing; the UI smoke test (`tools/ui_smoke_test.js`) is updated to the new flow.

## Approaches considered

| Approach | What it is | Trade-off |
|---|---|---|
| A. Server filters by date only | Server returns all vessels in the range; search, chips, sort and stats stay in the browser; Dashboard gets a server endpoint. | Smallest change, instant search, but no paging: a wide range still loads everything. |
| **B. Server does everything (chosen)** | One list request carries range, search, chip, port, sort and page; returns one page plus totals for all matches. Dashboard, OPR summary, alerts and bulk duplicate check get server endpoints. | More work; search waits for a short pause before querying. Scales and every number comes from the server. |

**Picked: B** (by the user), because they asked for pagination and for the data to come from the server; A would have
to be redone once the list grows.

## Design

### Shared filter

One filter object in `state` (replacing `filter`, `query`, `sort`, `port` as separate client-side concerns):

```
{ from: 'YYYY-MM-DD' | '', to: 'YYYY-MM-DD' | '', q: '', bucket: 'ALL'|'ARK'|'MSK'|'OTH'|'SERVICES',
  port: 'ALL'|<port key>, sort: <key>, dir: 'asc'|'desc', page: 1 }
```

- **Default range: the current calendar month** (1st to last day), in Cairo local date. *(my call: the list opens on
  what is current; the user can clear both fields to see all dates.)*
- The Vessels page and the Dashboard show the same From / To values; changing them on one page changes them on the
  other. *(my call: one range to think about.)*
- From after To → the server answers 400 with a clear message; the inputs also stop it in the browser.
- Any filter change resets `page` to 1.

### `GET /api/vessels/` (extended)

Query parameters (all optional): `from`, `to`, `q`, `bucket`, `port`, `sort`, `dir`, `page`, `page_size`.

- `from` / `to`: ISO dates, inclusive, filter on `Vessel.date`. Invalid → 400.
- `q`: case-insensitive "contains" match on name, OPR, POC, agent, **or** any of the vessel's service types.
  (Matching the date as text goes away: the range replaces it.) Trimmed, max 100 characters.
- `bucket`: same rule as the front end's `oprClass` today — OPR trimmed and upper-cased equals `ARK` / `MSK`, `OTH` is
  everything else (including blank); `SERVICES` = has at least one service.
- `port`: as today (ignored for port users).
- `sort`: one of `name, opr, poc, agent, port, date, total_cost_egp`; `dir`: `asc` / `desc`. Default `date desc`.
  Ties broken by `-id` so pages are stable.
- `page` (1-based), `page_size` default **50**, any whole number 1–200 (the page offers 10 / 25 / 50 / 100; the OPR
  summary uses 200). A page past the end returns an empty list with the real totals (not 404).
- Response:

```json
{ "vessels": [ ...one page, same shape as today... ],
  "page": 1, "page_size": 50, "count": 137, "pages": 3,
  "totals": { "vessels": 137, "ark": 40, "msk": 60, "oth": 37, "with_services": 90,
              "cost_egp": 123456.78, "profit_egp": 45678.9 } }
```

`totals` are over the **date range and port only** — **not** narrowed by search or `bucket` — so the stat cards
describe the chosen period and stay steady while someone types or picks a chip; `count` / `pages` describe the
searched, bucket-filtered list being paged. *(my call: today the cards ignore both search and chips, and this keeps
that, with the range added. It means totals need a second query without `q` and `bucket`.)*

Implementation note: filter in the database (range, port, `q`, and bucket where it can be expressed with
`Upper(Trim("opr"))`), then compute figures in Python for the matched set (needed for totals and cost sorting), sort,
and slice. Add a database index on `Vessel.date` (migration). This keeps the server work proportional to the range,
which is small by default; denormalising totals onto `Vessel` is a later step if ranges of many thousands become
common.

### `GET /api/vessels/alerts/` (new)

Vessels dated today or tomorrow (Cairo date), scoped like the list and honouring the port selector, **independent of
the date range and search**. Returns `{ "today": [...], "tomorrow": [...] }` in the normal vessel shape. The bell
and banner use only this. Refreshed when the page loads, when the port changes, and after any change to a vessel.

### `GET /api/dashboard/` (new)

Parameters: `from`, `to`, `port`. Returns the vessel count and, per non-blank OPR (exact value, sorted):
`vessels, services, cost_egp, profit_egp, service_counts` (with Crew Change split into on / off signers as the OPR
summary does today). The Dashboard's year / month selects are **replaced** by the shared From / To inputs.

### OPR summary popup

Opened from a Dashboard bar or card. Uses the dashboard response for the combined service counts and totals, and
fetches the per-vessel breakdown with `GET /api/vessels/?opr=<exact value>&from&to&port&page_size=200`. If there are
more than 200, it shows the first 200 and says so. *(my call; add an exact `opr` parameter to the list endpoint for
this.)*

### Vessel lookups in dialogs

`state.vessels` becomes the current page only, plus a small cache by id. Anything that opens a vessel not in the
cache (an alert, the OPR summary, a link) fetches `GET /api/vessels/<id>/` first. Existing dialog code keeps calling
`getVessel(id)` but on a cache that may be filled on demand.

### After a change

Saving or deleting a vessel or service updates the cache from the API response (as today) **and** re-fetches the
current list page and the alerts, so totals and paging stay right. Quick-add and bulk-add re-fetch the list too.
Deleting the last row of a page falls back to the previous page.

**Saved outside the range (decided by the user):** when a vessel is created or re-dated and its date falls outside
the current From–To range, the range is **not** changed. A notice appears — "Saved — 03.12.2026 is outside the
current date range" — with a **Show it** button that widens the range just enough to include that date (moves From
earlier or To later) and reloads. The vessel's dialog stays open as today. This applies to the quick-add bar, the
vessel form and "save and add another". Bulk add: after creating, its "View them" link widens the range to cover
the earliest and latest pasted dates. The existing rule that switches the port selector to "All" for a vessel in
another port stays.

### Bulk add duplicate check

New `POST /api/vessels/bulk/check/` with `{ rows: [{name, date}], port }` → `{ existing: [indexes of rows that
already exist] }`, matching on name trimmed and upper-cased + same date **in the target port** (the port the rows
will be created in: the port user's own port, or the admin's choice in the bulk form). The same name and date in
another port is a different port call and is not a duplicate. *(my call: today's check compares against whatever
the top-bar port selector happens to show, which is accidental.)*
Bulk preview calls it after parsing; same 200-row limit; read-only users get 403 like bulk create.

### UI

```
[ From 01.11.2026 ] [ To 30.11.2026 ] [ ✕ clear ]   ALL  ARK  MSK  Other  With services   [port ▾] [search…] [CSV] [+ Add]
Showing 51–100 of 137 vessels                 Rows per page [50 ▾]   ‹ Prev   Page 2 of 3   Next ›
```

- **Rows per page (decided by the user):** a selector with **10, 25, 50, 100**, default 50. Changing it goes back to
  page 1. The choice is remembered in this browser (`localStorage`, wrapped in try/catch; falls back to 50).
  *(remembering it is my call.)*

- Search sends its request 300 ms after the user stops typing; a newer request supersedes an older one (drop stale
  responses).
- Column headers still sort, now on the server.
- Pager under the table (also shows the "Showing x–y of n" line). Prev / Next and the page count are hidden when
  there is one page; the rows-per-page selector always shows.
- Loading uses the existing status chip ("Loading…" / "Synced").

### CSV export

`/export.csv` accepts the same filter parameters as the list (minus paging) and exports all matches. The CSV button's
link is rebuilt whenever the filter changes.

## Testing

Backend tests for: range filtering (inclusive ends, open ends, invalid / reversed dates), search across fields and
service types, buckets, sorting including `total_cost_egp`, paging edges, totals over all matches, port scoping on
**every** new endpoint and parameter (port users cannot widen via `port`, `opr`, alerts, dashboard or bulk check),
alerts independent of the range, dashboard figures equal to the sum of per-vessel figures, bulk duplicate check, CSV
honouring filters. Update the UI smoke test for the date inputs, pager and server-side search.

## Left to the builder

- Module layout (e.g. a `listing.py` for the query/sort/total logic), naming, how the cache is structured.
- Exact pager markup and styling, within the existing CSS.
- Whether the bucket filter runs in SQL or after the Python pass, as long as totals and paging are correct.
