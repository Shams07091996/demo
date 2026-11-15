# Server-side Vessel List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The vessel table, stat cards, Dashboard, OPR summary, alerts, bulk duplicate check and CSV all come from the
server, filtered by a From–To date range, with paging (10 / 25 / 50 / 100 rows).

**Architecture:** A new `sheet/listing.py` owns filtering, figures, sorting, paging and totals. The database narrows
by date range and port; each matching vessel's figures are computed once in Python (money can't be summed in SQL),
then search, bucket, exact OPR, sort and slice run on those dicts. The views stay thin. On the front end, `state`
holds one filter object and the current page only, plus a cache by id; every screen asks the server.

**Tech Stack:** Django 5.2, SQLite (dev) / PostgreSQL 16 (prod), vanilla ES modules, no build step.

**Spec:** `docs/superpowers/specs/2026-11-15-server-side-vessel-list-design.md` (approved). Read it before starting.

**This folder is not a git repository.** Where a task ends in "Checkpoint", run the full backend suite instead of
committing. If the user runs `git init` first, commit at each checkpoint instead.

Commands assume the venv is active (`venv\Scripts\activate` on Windows). `manage.py test` turns debug on by itself.

## Global Constraints

- Every new endpoint goes through `@json_api` and `access.scoped_vessels(profile, port)`; port users are always pinned to their own port, whatever `port` they send.
- `page_size` accepts whole numbers 1–200; the UI offers 10, 25, 50, 100; default 50.
- Date range is on `Vessel.date`, inclusive both ends; either end may be empty. The **server** treats a missing `from` / `to` as open-ended; the current-month default (Cairo local date) lives in the **browser**.
- Sort keys: `name, opr, poc, agent, port, date, total_cost_egp`; `dir` `asc`/`desc`; default `date desc`; ties by `-id`.
- `totals` cover date range + port only (not search, not bucket); `count` / `pages` cover the searched, bucket-filtered list.
- Search: trimmed, max 100 characters, case-insensitive substring on name, OPR, POC, agent or any service type. Whitespace-only = no search.
- Bucket rule = `oprClass` in `util.js`: OPR trimmed + upper-cased is `ARK` / `MSK`, else `OTH`; `SERVICES` = at least one service.
- Search request fires 300 ms after typing stops; older responses are dropped.
- No third-party scripts; every dynamic value inserted as HTML goes through `esc()`; `localStorage` access wrapped in try/catch.
- All 77 existing backend tests keep passing.

## Review Focus

1. **From after To** (e.g. `from=2026-12-01&to=2026-11-01`): the server answers 400 "From must be on or before To."; the page never sends it (Task 1 test, Task 5 step).
2. **Odd search text** (`"   "`, `"%"`, `"_"`, mixed case Arabic/Latin): whitespace-only means no search; `%` and `_` are literal characters, not wildcards (Task 1 test).
3. **Bad paging parameters** (`page=0`, `page=abc`, `page_size=500`, `page=99` past the end): the first three are 400; past the end returns an empty list with real totals (Task 1 test).
4. **"Today" near midnight**: alerts use Cairo's date (`timezone.localdate()`), not UTC (Task 3 test).
5. **Fast typing**: a slow earlier search response arriving after a later one must not overwrite the table (Task 5 step: request sequence number).

---

### Task 1: Listing logic (`sheet/listing.py`) + date index

**Files:**
- Create: `sheet/listing.py`
- Create: `sheet/migrations/0005_vessel_date_index.py` (via `makemigrations`)
- Modify: `sheet/models.py` (`Vessel.date` → `models.DateField(db_index=True)`)
- Test: `sheet/tests_listing.py` (new; imports `ApiTestCase`, `make_user` from `.tests`)

**Interfaces:**
- Produces:
  - `@dataclass Filters: date_from: date|None, date_to: date|None, q: str, bucket: str, port: str|None, opr: str|None, sort: str, desc: bool, page: int, page_size: int`
  - `parse_filters(params: QueryDict, *, paged: bool = True) -> Filters` — raises `errors.BadRequest`. With `paged=False`, `page`/`page_size` are ignored.
  - `opr_bucket(opr: str) -> str` → `"ARK" | "MSK" | "OTH"`
  - `range_rows(profile, f: Filters) -> list[dict]` — `vessel_to_dict` for every vessel in range + port, scoped, ordered `-date, -id`.
  - `matching(rows: list[dict], f: Filters) -> list[dict]` — applies `q`, `bucket`, `opr`, then sort.
  - `totals(rows: list[dict]) -> dict` keys `vessels, ark, msk, oth, with_services, cost_egp, profit_egp` (money rounded to 2).
  - `list_response(profile, params) -> dict` keys `vessels, page, page_size, count, pages, totals`.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_listing.py`, class `ListingTests(ApiTestCase)`. In `setUpTestData` (call `super()` first) add Alexandria vessels: `"ARK ONE"` opr `"ark "` 2026-11-02 with a Fresh Water service cost 100 / revenue 150 EGP; `"MSK TWO"` opr `"MSK"` 2026-11-20 with no services; `"OLD SHIP"` opr `"CMA"` 2026-10-31 with a Landing service (one entry, cost 50 EGP). The base class already has `"ALEX SHIP"` (Alexandria,
2026-11-13, no services) and `"SUEZ SHIP"` (Suez, 2026-11-13, Fresh Water cost 10). Helpers: `get(user, **params)` logs
in, calls `/api/vessels/` with those params and returns the JSON; `status(user, **params)` returns the status code.

```python
def test_range_is_inclusive_and_open_ended(self):
    names = lambda d: sorted(v["name"] for v in d["vessels"])
    self.assertEqual(names(self.get("admin", **{"from": "2026-11-02", "to": "2026-11-20", "port": "alexandria"})),
                     ["ALEX SHIP", "ARK ONE", "MSK TWO"])
    self.assertIn("OLD SHIP", names(self.get("admin", to="2026-10-31")))
    self.assertNotIn("OLD SHIP", names(self.get("admin", **{"from": "2026-11-01"})))

def test_reversed_or_invalid_dates_are_rejected(self):
    for params in ({"from": "2026-12-01", "to": "2026-11-01"}, {"from": "13.11.2026"}):
        self.assertEqual(self.status("admin", **params), 400)

def test_search_matches_fields_and_service_types_literally(self):
    self.assertEqual([v["name"] for v in self.get("admin", q="fresh water")["vessels"]], ["ARK ONE"])
    self.assertEqual(self.get("admin", q="   ")["count"], self.get("admin")["count"])
    self.assertEqual(self.get("admin", q="%")["count"], 0)

def test_bucket_uses_trimmed_upper_case_opr(self):
    self.assertEqual([v["name"] for v in self.get("admin", bucket="ARK")["vessels"]], ["ARK ONE"])
    with_services = {v["name"] for v in self.get("admin", bucket="SERVICES")["vessels"]}
    self.assertEqual(with_services, {"ARK ONE", "OLD SHIP", "SUEZ SHIP"})

def test_totals_ignore_search_and_bucket_but_follow_range(self):
    full = self.get("admin", **{"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria"})
    narrowed = self.get("admin", **{"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria", "q": "MSK"})
    self.assertEqual(full["totals"], narrowed["totals"])
    self.assertEqual((narrowed["count"], full["totals"]["ark"], full["totals"]["cost_egp"]), (1, 1, 100.0))

def test_sorting_by_cost_and_stable_ties(self):
    rows = self.get("admin", port="alexandria", sort="total_cost_egp", dir="desc")["vessels"]
    self.assertEqual(rows[0]["name"], "ARK ONE")
    ids = [v["id"] for v in self.get("admin", sort="port", dir="asc")["vessels"] if v["port"] == "alexandria"]
    self.assertEqual(ids, sorted(ids, reverse=True))

def test_paging_and_bad_parameters(self):
    page = self.get("admin", page_size=2, page=2)
    self.assertEqual((page["page"], page["page_size"], len(page["vessels"])), (2, 2, 2))  # 5 vessels in all
    self.assertEqual(page["pages"], -(-page["count"] // 2))
    past = self.get("admin", page=99)
    self.assertEqual((past["vessels"], past["totals"]["vessels"] > 0), ([], True))
    for params in ({"page": "0"}, {"page": "abc"}, {"page_size": "500"}, {"sort": "data"}, {"bucket": "XYZ"}):
        self.assertEqual(self.status("admin", **params), 400)

def test_port_users_cannot_widen_their_port(self):
    data = self.get("suezuser", port="alexandria")
    self.assertEqual({v["port"] for v in data["vessels"]}, {"suez"})
    self.assertEqual(data["totals"]["vessels"], 1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test sheet.tests_listing -v 2`
Expected: FAIL / ERROR (the list endpoint ignores the new parameters and has no `totals`).

- [ ] **Step 3: Implement `sheet/listing.py`** with the interfaces above. Error messages: `"From must be on or before To."`, `"Enter dates as YYYY-MM-DD."`, `"Unknown sort."`, `"Unknown filter."`, `"Page must be a whole number from 1."`, `"Rows per page must be 1–200."`. `range_rows` uses `scoped_vessels(profile, f.port).filter(date__gte/lte…)` and `month_rates()` once. Search compares `q.casefold()` against each field's `casefold()` (plain substring, so `%` / `_` are literal). Sort: rows arrive `-id` within date; sort by key with `reverse=f.desc` (Python's sort is stable with `reverse`, so ties keep `-id`); string keys `casefold()`, `port` sorts by key. `pages = max(1, ceil(count / page_size))`.

- [ ] **Step 4: Point `GET /api/vessels/` at it.** In `views.vessels`, the GET branch becomes `return JsonResponse(listing.list_response(request.profile, request.GET))`. Add `db_index=True` to `Vessel.date` and run `python manage.py makemigrations sheet -n vessel_date_index` (needs `DJANGO_DEBUG=1` set in the shell).

- [ ] **Step 5: Run to verify they pass**

Run: `python manage.py test sheet.tests_listing -v 2`
Expected: PASS. Existing tests that read `data["vessels"]` from `GET /api/vessels/` still pass (default page size 50 covers their data).

- [ ] **Step 6: Checkpoint** — `python manage.py test sheet` → all OK.

---

### Task 2: Exact-OPR filter and filtered CSV

**Files:**
- Modify: `sheet/views.py` (`export_csv`)
- Test: `sheet/tests_listing.py` (class `CsvFilterTests(ApiTestCase)`)

**Interfaces:**
- Consumes: `parse_filters(params, paged=False)`, `range_rows`, `matching` from Task 1. `opr` (exact, case-sensitive, untrimmed equality with `Vessel.opr`) is already a `Filters` field; this task tests it.
- Produces: `/export.csv` accepts the same parameters as the list minus `page` / `page_size`.

- [ ] **Step 1: Write the failing tests**

```python
def test_exact_opr_filter(self):
    data = self.get("admin", opr="MSK")          # reuse ListingTests fixtures via a shared mixin
    self.assertEqual([v["name"] for v in data["vessels"]], ["MSK TWO"])
    self.assertEqual(self.get("admin", opr="msk")["count"], 0)

def test_csv_exports_all_matches_not_one_page(self):
    client = self.login("admin")
    body = client.get("/export.csv", {"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria",
                                      "page_size": "1"}).content.decode("utf-8-sig")
    self.assertEqual(len(body.strip().splitlines()), 1 + 3)  # header + ALEX SHIP, ARK ONE, MSK TWO
    self.assertEqual(client.get("/export.csv", {"from": "x"}).status_code, 400)
```

Put the Task 1 fixtures in a `ListingData` mixin with `setUpTestData` so both classes share them.

- [ ] **Step 2: Run to verify they fail** — `python manage.py test sheet.tests_listing -v 2` → CSV test FAILS (CSV ignores filters).

- [ ] **Step 3: Rewrite `export_csv`'s row source** as `matching(range_rows(profile, f), f)` with `f = parse_filters(request.GET, paged=False)`; a `BadRequest` returns `HttpResponse(str(error), status=400, content_type="text/plain")`. Rows are now dicts, so the date column uses `dmy` of `row["date"]` (format `%d.%m.%Y`). Keep `_csv_safe`, the BOM and the audit line.

- [ ] **Step 4: Run to verify they pass** — same command → PASS; `CsvTests` in `tests.py` still pass.

- [ ] **Step 5: Checkpoint** — `python manage.py test sheet` → all OK.

---

### Task 3: Alerts and Dashboard endpoints

**Files:**
- Modify: `sheet/listing.py`, `sheet/views.py`, `sheet/urls.py`
- Test: `sheet/tests_listing.py` (classes `AlertsTests`, `DashboardTests`)

**Interfaces:**
- Produces:
  - `alerts_response(profile, params) -> {"today": [vessel], "tomorrow": [vessel]}` — uses `timezone.localdate()`; honours `port` only.
  - `dashboard_response(profile, params) -> {"count": int, "oprs": [{"opr", "vessels", "services", "cost_egp", "profit_egp", "service_counts": {type: n}}]}` — `oprs` sorted by `opr`, blank OPR left out; `service_counts` splits Crew Change into `"Crew Change (On)"` / `"Crew Change (Off)"` counting signers, like `openOprSummary` does today.
  - Views `vessel_alerts` (`GET /api/vessels/alerts/`, name `api_vessel_alerts`, **before** the `<int:pk>` route) and `dashboard` (`GET /api/dashboard/`, name `api_dashboard`), both `@json_api` + `@require_http_methods(["GET"])`.

- [ ] **Step 1: Write the failing tests** (`from unittest import mock`)

```python
@mock.patch("sheet.listing.timezone.localdate", return_value=date(2026, 11, 13))
def test_alerts_use_cairo_today_and_ignore_the_range(self, _):
    data = self.call(self.login("admin"), "get", "/api/vessels/alerts/?from=2020-01-01&to=2020-01-31")[1]
    self.assertEqual({v["name"] for v in data["today"]}, {"ALEX SHIP", "SUEZ SHIP"})
    self.assertEqual(data["tomorrow"], [])

def test_port_user_alerts_are_scoped(self):  # same mock
    data = self.call(self.login("alex"), "get", "/api/vessels/alerts/?port=suez")[1]
    self.assertEqual({v["port"] for v in data["today"]}, {"alexandria"})

def test_dashboard_equals_sum_of_vessel_figures(self):
    client = self.login("admin")
    dash = self.call(client, "get", "/api/dashboard/?from=2026-11-01&to=2026-11-30")[1]
    rows = self.call(client, "get", "/api/vessels/?from=2026-11-01&to=2026-11-30&page_size=200")[1]["vessels"]
    for entry in dash["oprs"]:
        mine = [v for v in rows if v["opr"] == entry["opr"]]
        self.assertEqual(entry["vessels"], len(mine))
        self.assertAlmostEqual(entry["cost_egp"], sum(v["total_cost_egp"] for v in mine), places=2)
    self.assertNotIn("", [e["opr"] for e in dash["oprs"]])
    self.assertEqual(dash["count"], len(rows))

def test_dashboard_is_port_scoped_and_validates_dates(self):
    self.assertEqual(self.call(self.login("alex"), "get", "/api/dashboard/?port=suez")[1]["count"],
                     Vessel.objects.filter(port="alexandria").count())
    self.assertEqual(self.call(self.login("admin"), "get", "/api/dashboard/?from=bad")[0], 400)
```

Add a Crew Change service with 2 on-signers and 1 off-signer to an `"ARK"` vessel in the fixtures and assert `service_counts["Crew Change (On)"] == 2`.

- [ ] **Step 2: Run to verify they fail** — `python manage.py test sheet.tests_listing -v 2` → 404s.
- [ ] **Step 3: Implement** the two functions (dashboard reuses `range_rows`) and the two views/routes.
- [ ] **Step 4: Run to verify they pass** — same command → PASS.
- [ ] **Step 5: Checkpoint** — full suite OK.

---

### Task 4: Bulk duplicate check endpoint

**Files:**
- Modify: `sheet/listing.py`, `sheet/views.py`, `sheet/urls.py`
- Test: `sheet/tests_listing.py` (class `BulkCheckTests(ApiTestCase)`)

**Interfaces:**
- Produces: `existing_rows(profile, rows: list, port: str|None) -> list[int]` (0-based indexes) and view `vessels_bulk_check` at `POST /api/vessels/bulk/check/` (name `api_vessels_bulk_check`, before `<int:pk>`), body `{"rows": [{"name", "date"}], "port"}` → `{"existing": [...]}`. Target port = profile's port for port users, else body `port` (must be in `PORT_KEYS`, else 400). Match: `name.strip().upper()` and same date. Rows: list of ≤ `BULK_MAX_ROWS` dicts; a row with a bad date is simply not a match. Read-only → 403 via `require_edit`.

- [ ] **Step 1: Write the failing tests**

```python
def test_duplicates_are_found_in_the_target_port_only(self):
    admin = self.login("admin")
    rows = [{"name": " alex ship ", "date": "2026-11-13"}, {"name": "NEW", "date": "2026-11-13"}]
    self.assertEqual(self.call(admin, "post", "/api/vessels/bulk/check/", {"rows": rows, "port": "alexandria"})[1],
                     {"existing": [0]})
    self.assertEqual(self.call(admin, "post", "/api/vessels/bulk/check/", {"rows": rows, "port": "suez"})[1],
                     {"existing": []})

def test_port_user_checks_own_port_and_viewer_is_refused(self):
    rows = [{"name": "SUEZ SHIP", "date": "2026-11-13"}]
    self.assertEqual(self.call(self.login("alex"), "post", "/api/vessels/bulk/check/",
                               {"rows": rows, "port": "suez"})[1], {"existing": []})
    self.assertEqual(self.call(self.login("viewer"), "post", "/api/vessels/bulk/check/", {"rows": rows})[0], 403)
    self.assertEqual(self.call(self.login("admin"), "post", "/api/vessels/bulk/check/",
                               {"rows": rows * 201, "port": "suez"})[0], 400)
```

- [ ] **Step 2: Run to verify they fail** — 404.
- [ ] **Step 3: Implement** with one query: `scoped_vessels(profile, port, prefetch=False).filter(date__in=dates).values_list("name", "date")`.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Checkpoint** — full suite OK.

---

### Task 5: Front end — filter state, loading, table, stats, pager

**Files:**
- Modify: `sheet/templates/sheet/index.html` (vessels toolbar + pager + range notice container), `sheet/views.py` (`index`: drop `months`), `sheet/static/sheet/js/state.js`, `data.js`, `main.js`, `render/list.js`, `render/index.js`, `sheet/static/sheet/app.css`
- Create: `sheet/static/sheet/js/render/pager.js`

**Interfaces:**
- Produces:
  - `state.filter = { from, to, q, bucket, port, sort, dir, page, pageSize }`; `state.list = { count, pages, page, totals }`; `state.vessels` = current page; `state.cache: Map<id, vessel>`.
  - `state.js`: `getVessel(id) -> vessel|undefined` (reads `state.cache`), `rememberVessels(list)`.
  - `data.js`: `defaultRange() -> {from, to}` (current month via `localISO`), `filterParams(extra = {}) -> URLSearchParams` (drops empty values and `port=ALL`), `loadVessels() -> Promise` (current page; uses a request counter and ignores any response that isn't the latest), `ensureVessel(id) -> Promise<vessel|null>` (cache or `GET /api/vessels/<id>/`; on 404 shows "That vessel is no longer available." via `setStatus('error', …)` and returns null), `setFilter(patch)` (merges, resets `page` to 1 unless `patch.page` given, persists `pageSize`, reloads), `exportHref() -> string`.
  - `render/pager.js`: `renderPager()` — "Showing x–y of n vessels", Prev / "Page p of n" / Next (hidden when `pages === 1`), and a `#page-size` select with 10, 25, 50, 100 (always shown).
- Template ids: `#f-from`, `#f-to`, `#f-clear`, `#pager`, `#rangeNotice` (empty div above the table, used in Task 7).

- [ ] **Step 1: Template.** Add `<input type="date" id="f-from">`, `<input type="date" id="f-to">`, `<button id="f-clear">✕</button>` at the start of the vessels toolbar; change the search placeholder to "Search vessel, OPR, POC, agent, service…"; add `<div id="pager" class="pager"></div>` after `.table-wrap`; remove `#count` (the pager shows that line).
- [ ] **Step 2: State and loading.** Page size starts from `localStorage['sheet.pageSize']` if it is one of 10/25/50/100, else 50. `loadVessels` stores `vessels`, `list` and fills the cache.
- [ ] **Step 3: Wire controls in `main.js`:** chips → `setFilter({bucket})`; search `input` → debounce 300 ms → `setFilter({q})`; `th[data-sort]` → `setFilter({sort, dir})` (same column toggles `asc`/`desc`); From / To `change` → `setFilter({from, to})`, and set each input's `min` / `max` from the other so the browser can't pick From after To; `#f-clear` → `setFilter({from: '', to: ''})`; port select → `setFilter({port})`; `#exportBtn.href = exportHref()` after every load.
- [ ] **Step 4: Rendering.** `renderStats()` reads `state.list.totals` (cards: Vessels, ARK, MSK, Other, With services, Total cost, Total profit). `renderTable()` renders `state.vessels` as is (no client filter/sort) and shows `#empty` when the page is empty. `renderAll()` also calls `renderPager()`.
- [ ] **Step 5: Manual check.** `python manage.py runserver`, sign in, confirm: range defaults to this month; clearing shows all; changing rows per page reloads at page 1 and survives a reload; typing quickly in search ends on the last term's results.
- [ ] **Step 6: Checkpoint** — backend suite still OK.

---

### Task 6: Front end — Dashboard, OPR summary, alerts from the server

**Files:**
- Modify: `index.html` (Dashboard toolbar), `render/dashboard.js`, `modals/summary.js`, `render/notifications.js`, `data.js`, `main.js`, `actions.js`

**Interfaces:**
- Consumes: `filterParams`, `ensureVessel`, `rememberVessels` (Task 5); `/api/dashboard/`, `/api/vessels/alerts/` (Task 3).
- Produces: `loadDashboard() -> Promise` (stores `state.dashboard`), `loadAlerts() -> Promise` (stores `state.alerts = {today, tomorrow}` and caches them), `openSummary(id)` and `openVessel(id)` become async and call `ensureVessel` first.

- [ ] **Step 1:** Replace `#dash-year` / `#dash-month` with `#d-from` / `#d-to` bound to the same `state.filter.from/to` (changing either reloads the list and, if on the Dashboard, the dashboard). Remove the year/month logic in `dashboard.js`; render bars and cards from `state.dashboard.oprs`; `#dash-count` = `state.dashboard.count`. Load the dashboard when its page opens and after range/port changes while it is open.
- [ ] **Step 2:** `openOprSummary(opr)`: combined counts and totals from the matching `state.dashboard.oprs` entry; per-vessel list from `GET /api/vessels/?` + `filterParams({opr, page_size: 200, page: 1, q: '', bucket: ''})`; if `count > 200`, add "Showing the first 200 of N vessels." under the heading.
- [ ] **Step 3:** `buildNotifications()` reads `state.alerts`. Call `loadAlerts()` on start, on port change, and after any change (Task 7).
- [ ] **Step 4: Manual check:** Dashboard numbers for a month match the Vessels stat cards for the same range and port; clicking an alert for a vessel not on the current page opens its summary.
- [ ] **Step 5: Checkpoint** — backend suite OK.

---

### Task 7: Front end — refresh after changes, outside-range notice, bulk add

**Files:**
- Modify: `data.js`, `actions.js`, `quickAdd.js`, `pages/bulk.js`, `index.html` (`#rangeNotice`), `app.css`
- Create: `sheet/static/sheet/js/render/rangeNotice.js`

**Interfaces:**
- Produces: `data.js` `refreshAfterChange() -> Promise` (reload current page and alerts; if the page is now empty and `page > 1`, step back one page and reload); `widenRangeTo(fromIso, toIso = fromIso)` (moves `from` earlier / `to` later only as needed; an empty end stays empty; reloads); `render/rangeNotice.js` `showOutsideRange(dateIso)` / `hideRangeNotice()`.
- Replaces `replaceVessel` (delete it): every save path calls `rememberVessels([vessel])`, then `refreshAfterChange()`.

- [ ] **Step 1:** In `saveService`, `deleteService`, `saveVessel`, `deleteVessel`, `changeRate` and quick add, use the new refresh. After a vessel create/update, if its date is outside `state.filter.from/to`, call `showOutsideRange(vessel.date)`. Copy, exactly: `Saved — ${dmy(date)} is outside the current date range.` with a button `Show it` (`data-act="show-outside"`) that calls `widenRangeTo(date)` then `hideRangeNotice()`. Any filter change also hides the notice. The open dialog stays open (it reads from the cache).
- [ ] **Step 2:** Keep quick add's "switch port to All" rule, now via `setFilter({port: 'ALL'})`.
- [ ] **Step 3:** Bulk preview: after `parseBulk(text, defaults, [], known)`, call `POST /api/vessels/bulk/check/` with the parsed rows that have a name and date and the target port (`#bk-port` for admins); mark returned indexes as skipped with the existing duplicate warning text, then render. If the call fails, show its error and keep Create disabled. After a successful create, the "View them" link calls `widenRangeTo(minDate, maxDate)` of the created rows and goes to `#vessels`.
- [ ] **Step 4: Manual check:** quick-add a vessel dated 2020-01-15 → notice shows → Show it → From becomes 15.01.2020 and the row appears; bulk-paste a line that already exists → it is marked duplicate.
- [ ] **Step 5: Checkpoint** — backend suite OK.

---

### Task 8: Smoke test and docs

**Files:**
- Modify: `tools/ui_smoke_test.js`, `README.md`, `SECURITY.md` (test count line)

- [ ] **Step 1: Update the smoke test** for the new flow. The vessels it creates are dated 2020-01, outside the default range, so after each create assert the notice and press Show it:

```js
ok(await waitFor(() => $('#rangeNotice').textContent.includes('outside the current date range')), 'notice for a vessel outside the range');
click($('[data-act="show-outside"]'));
ok(await waitFor(() => rowFor('SMOKE') && $('#f-from').value === '2020-01-15'), 'Show it widens the range and shows the row');
ok($('#page-size') && [...$('#page-size').options].map((o) => o.value).join() === '10,25,50,100', 'rows-per-page choices');
ok($('#d-from') && !$('#dash-year'), 'dashboard uses the date range');
```

Replace the year/month dashboard steps with `type($('#d-from'), …)` equivalents, and the client-side search step with a wait for the debounced server result.
- [ ] **Step 2: Run it.** `cd tools && npm install` (project's own `package.json`), then in one terminal `set DJANGO_DEBUG=1` / `$env:DJANGO_DEBUG="1"` and `python ../manage.py seed_demo --password "a-long-password"` and `python ../manage.py runserver 8765`; in another `UI_TEST_PASSWORD="a-long-password" node ui_smoke_test.js alex`, then `admin`, then `viewer`. Expected: every check prints ✓. Note: `seed_demo` writes demo users into the local `db.sqlite3`.
- [ ] **Step 3: Docs.** README "Pages" table: Vessels row mentions the From–To range, server-side search and paging (10/25/50/100); Dashboard row says it follows the same range. Update both test-count lines (README and SECURITY.md §5) to the number `python manage.py test sheet` reports.
- [ ] **Step 4: Final check** — `python manage.py test sheet` → all OK; smoke test passes for all three roles.
