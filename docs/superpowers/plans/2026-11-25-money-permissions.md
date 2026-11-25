# Money permissions (access rework piece 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `money.edit` decides who sees and types the money boxes of forms; `money.view` decides who gets money
overviews (totals, profit, money charts, money columns of exports). Without the permission the server never sends
those values, and saves keep what is stored.

**Architecture:** One new module, `sheet/moneyaccess.py`, holds every rule: which keys of a service / booking /
disposal row / customer are money, which export and report column heads are money, how to strip them from a
response and how to put stored money back into a save. Every module that builds a response or a file calls it at
the boundary; the internal maths (`finance`, `calculations`, `vessel_to_dict`) keeps working on full data. The front
end hides the boxes / panels with `config.can()` and never sends money keys without `money.edit` (a pure twin of the
service money keys in `js/moneyKeys.js`, unit-tested in `parsing_test.js`).

**Tech Stack:** Django 5.2, vanilla ES modules (no build), Node test scripts in `tools/`.

**Spec:** `docs/superpowers/specs/2026-11-24-access-rework-design.md`, section "Piece 3 — money in forms and in
overviews". Hand-off notes: `docs/NEXT-CHAT.md` "Next: piece 3".

## Global Constraints

- Branch `feature/money-permissions` (made). Merge only when the user agrees. Never commit `.env.example`, the two
  zips or `db.sqlite3`.
- Admins (superusers) have both permissions always (`Profile.can`). Tests use `tests.make_user(name, port,
  permissions=[...], pages=[...])`.
- "people type money as part of their work, but the overview is given out on purpose."
- Without `money.edit`: money boxes hidden, **server never sends them**, saves **keep the stored values** (absent ≠
  cleared), **sending them anyway → 403** with the message of `access.require(profile, "money.edit")` ("You don't
  have permission: Enter / edit prices and costs.").
- Quantities (Fresh Water `quantity`, Delivery Parcels `weight`, garbage m³, sludge t) are not money: always sent.
- A save that keeps stored money must not raise `version` nor write a History record (`conflicts.bump_if_changed`
  compares with `==`).
- Input is refused, never silently fixed (CLAUDE.md). LF line endings. Screens only through `dom.js` `h()`; no inline
  `style=`, no `innerHTML`. Minimal UI text: no help text replacing a hidden box.
- `cd tools && npm run check` green before the review; README / SECURITY test counts updated.

## Decisions taken here (builder's choices the spec left open)

1. **`money.edit` covers** (per record, the forms): `Service.data` money keys (table below), a booking's `cost*`,
   `revenue*`, `cost_currency`, `revenue_currency`, `exchange_rate`; the Garbage & Sludge page's per-row money
   (`revenue_* / cost_* / profit_*`, `rate_missing`, `price_missing`); customers' `rates`; the receipt's amounts;
   the vessel's month `rate` (needed by the dialog's live preview; also sent with `money.view`).
2. **`money.view` covers** (overviews): vessel `total_cost_egp` / `total_profit_egp`, every service's `calc`, list
   `totals.cost_egp` / `profit_egp`, sorting by `total_cost_egp` (403 without it), the Dashboard's money keys, the
   Garbage & Sludge page **totals**, export / report / CSV money columns, Services page `Cost` / `Revenue` / `Rate`
   tags (also in the `missing=1` filter and the export's Missing column).
3. **Delivery / Landing entries get a stable `uid`** (12 hex, like crew members) so stored money can be put back on
   the right line when someone without `money.edit` adds or removes lines. `validators._clean_multi` keeps a valid
   sent uid (once per service) or makes one; migration `0026_entry_uids` (data only, `RunPython`, reversible no-op)
   gives every stored entry one. A line with an unknown uid is new: its money starts empty.
4. Changing a service's type without `money.edit`: the new type's money starts empty (nothing to keep).
5. `crewbookings.cancel_bookings(service, refs, zero_money)`: sets the bookings' money to 0 only when
   `zero_money` (the caller passes `profile.can("money.edit")`); cancelled + version +1 either way.
6. Management Excel without `money.view`: money columns dropped from every table, the "Profit by service" sheet and
   the Summary's money notes left out; charts are named by column **head** (not index), so a chart whose series
   heads are gone is simply not drawn.
7. Not in this piece (STATUS "Left open", user to decide): Dashboard / Excel Open-Closed counts without the
   Calculations page.

### Service money keys (`moneyaccess.SERVICE_MONEY`)

| Type | Money keys |
|---|---|
| single-priced types, Crew Change, Others / Remarks | `cost`, `costCurrency`, `revenue`, `revenueCurrency`, `exchangeRate` |
| Crew Change on-signers (by `uid`) | `brokenVisa` (whole dict) |
| `MULTI_TYPES` | `exchangeRate`; per entry (by `uid`): `cost`, `costCurrency`, `revenue`, `revenueCurrency` |
| Cash to Master | `amount`, `amountCurrency`, `shareMode`, `percentage`, `fixedRevenue`, `exchangeRate` |

### Money column heads (`moneyaccess.MONEY_HEADS`, one frozenset)

CSV: `Total Cost LE`, `Total Profit LE`. Data export: `Cost per night`, `Revenue per night`, `Cost`, `Revenue`,
`Cost currency`, `Revenue currency`, `Exchange rate`, `Revenue EGP`, `Cost EGP`, `Profit EGP`, `Revenue USD`,
`Cost USD`, `Profit USD`, `Rate missing`, `Price missing`. Report: `Revenue (EGP)`, `Cost (EGP)`, `Profit (EGP)`,
`Broken visa revenue (EGP)`.

## Review Focus

1. A User without `money.edit` edits a Delivery Parcels service, **removes the middle line** and saves: the other
   two lines keep their own cost / revenue (uid match), nothing shifts → test in Task 1 and Task 2.
2. A User without `money.edit` opens and saves a vessel / service / booking / customer **without changing
   anything**: 200, `version` unchanged, no new `ChangeRecord` → tests in Tasks 2 and 3.
3. A User without `money.view` asks `/api/vessels/?sort=total_cost_egp` or the CSV with that sort → 403, not a
   leak through ordering → test in Task 2.
4. The vessel JSON reaches the browser by several routes (list, detail, alerts, every service / vessel write
   response): none may carry money the person lacks → test in Task 2 walks all of them.
5. Saved state in the browser: a person whose stored `state.filter.sort` is `total_cost_egp` (from before) loses
   that permission → the front end falls back to `date` instead of looping on 403 → step in Task 5.

---

### Task 1: `moneyaccess` rules for service data + entry uids

**Files:**
- Create: `sheet/moneyaccess.py`, `sheet/migrations/0026_entry_uids.py`, `sheet/tests_money.py`
- Modify: `sheet/validators.py` (`_clean_multi`)

**Interfaces:**
- Produces (in `sheet/moneyaccess.py`):
  - `EDIT = "money.edit"`, `VIEW = "money.view"`; `edits(profile) -> bool`, `views(profile) -> bool` (`profile`
    None → True: internal callers get everything).
  - `SERVICE_MONEY` (the table above), `strip_service_data(service_type, data) -> dict` (deep copy without the
    money keys; on-signers lose `brokenVisa`, entries lose their four keys, uids stay).
  - `service_money_sent(service_type, raw) -> bool` (any money key present in the raw payload's `data`, at the top,
    in an on-signer or in an entry; `None` values count as sent).
  - `keep_service_money(service_type, cleaned, stored_type, stored) -> dict`: `cleaned` with the money of `stored`
    put back (top keys; on-signers / entries matched by uid; unmatched → the cleaner's empty defaults); when
    `stored_type != service_type` or `stored` is None, `cleaned` unchanged.

- [ ] **Step 1: Write the failing tests** (`tests_money.py`, `SimpleTestCase` `ServiceMoneyRuleTests`):
  - `test_strip_single`: `strip_service_data("Fresh Water", {"quantity": 5, "cost": 10, "costCurrency": "USD",
    "revenue": 20, "revenueCurrency": "EGP", "exchangeRate": 50})` == `{"quantity": 5}`.
  - `test_strip_multi_keeps_awb_weight_uid`: entries keep `awb`, `weight`, `uid`; no `exchangeRate`.
  - `test_strip_crew_drops_broken_visa_only`: members keep name / uid / needsHotel.
  - `test_strip_cash_to_master_is_empty`: result `{}`.
  - `test_sent_detects_nested_keys`: True for `{"entries": [{"cost": None}]}` and for
    `{"onSigners": [{"brokenVisa": {}}]}`; False for `{"entries": [{"awb": "1"}], "quantity": 3}`.
  - `test_keep_matches_entries_by_uid`: stored lines a/b/c with costs 1/2/3, cleaned lines a/c (no money) → costs
    1/3; a new uid line → `cost` None, `costCurrency` "EGP".
  - `test_keep_matches_crew_by_uid` and `test_keep_type_change_keeps_nothing`.
  - `ValidatorTests`-style: `test_multi_entries_get_stable_uids`: `clean_service_data("Landing", {"entries": [{"uid":
    "abcdef012345"}, {"uid": "abcdef012345"}, {}]})` → first keeps it, the other two get new distinct 12-hex uids.
  - `TransactionTestCase` `test_migration_0026_gives_entries_uids` (pattern: `MigrationExecutor`, as in
    `tests_permissions`): a stored Landing with two uid-less entries gets two distinct uids; other types untouched.
- [ ] **Step 2:** `venv/Scripts/python.exe manage.py test sheet.tests_money` → FAIL (module missing).
- [ ] **Step 3:** Implement `moneyaccess.py` (service part), the uid in `_clean_multi` (reuse `UID_RE` and the
  crew's uid loop — pull it into one helper `_uid(item, seen)`), and migration 0026 (dependency
  `0025_profile_permissions`; `apps.get_model("sheet", "Service")`, only `MULTI_TYPES`, `.save(update_fields=["data"])`
  so no signal history from a live model; reverse = noop).
- [ ] **Step 4:** Tests pass; `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
  says no changes.
- [ ] **Step 5:** Commit `feat(money): money rules for service data, stable entry uids`.

### Task 2: Vessels and services follow the two permissions

**Files:**
- Modify: `sheet/moneyaccess.py`, `sheet/serializers.py`, `sheet/listing.py`, `sheet/views.py`
  (`_vessel_json`, `vessel_detail`, `_read_service`, `service_create`, `service_detail`, `export_csv`),
  `sheet/crewbookings.py` (`cancel_bookings`)
- Test: `sheet/tests_money.py` (`VesselMoneyApiTests(ApiTestCase)`)

**Interfaces:**
- Consumes: Task 1.
- Produces: `moneyaccess.vessel_out(row, profile) -> dict` (a copy: without `money.view` drops
  `total_cost_egp`, `total_profit_egp`, every service's `calc`; without `money.edit` strips each service's `data`;
  without both drops `rate`); `moneyaccess.totals_out(totals, profile)` (drops `cost_egp`, `profit_egp`);
  `moneyaccess.require_sort(profile, sort)` (`total_cost_egp` → `access.require(profile, VIEW)`);
  `moneyaccess.drop_columns(head, rows, profile) -> (head, rows)` (without `money.view` removes columns whose head
  is in `MONEY_HEADS`); `views._vessel_json(pk, profile, status=200)`;
  `crewbookings.cancel_bookings(service, refs, zero_money=True)`.

- [ ] **Step 1: Write the failing tests.** Users (port alexandria): `edit_only` (all permissions but `money.view`,
  pages without calculations / rates / history), `view_only` (all but `money.edit`), `neither`. A vessel with a
  Landing (two entries, USD cost) and a Crew Change with an on-signer's broken visa.
  - `test_every_vessel_route_hides_overviews_without_view`: for `edit_only`, GET list, detail, alerts and the
    responses of service POST / PUT and vessel PUT: no `total_cost_egp` / `total_profit_egp` / `calc` anywhere,
    list `totals` without `cost_egp`/`profit_egp`; service `data` still has `cost`; `rate` present.
  - `test_every_vessel_route_hides_boxes_without_edit`: same routes for `view_only`: `calc` and totals present,
    no money key in any `data`, `quantity` / `weight` / `awb` present.
  - `test_neither_gets_no_rate`.
  - `test_sort_by_money_needs_view`: list and `/export.csv` with `sort=total_cost_egp` → 403 for `edit_only`,
    200 for admin.
  - `test_csv_drops_money_columns`: `edit_only` CSV header has no `Total Cost LE` / `Total Profit LE`.
  - `test_save_without_money_keeps_it_and_changes_nothing`: `view_only` PUTs the service exactly as GET returned
    it → 200, `version` same, `ChangeRecord` count same, stored money unchanged.
  - `test_removing_a_line_keeps_the_others_money` (Review Focus 1, through the API).
  - `test_sending_money_without_edit_is_403`: PUT / POST with `data.cost` → 403 and nothing saved; same for an
    entry's `revenue` and an on-signer's `brokenVisa`.
  - `test_cancel_bookings_keeps_money_without_edit`: `view_only` cancels a crew change with `cancel_bookings` →
    bookings cancelled, money unchanged; admin → money 0 (existing behaviour).
- [ ] **Step 2:** Run `sheet.tests_money.VesselMoneyApiTests` → FAIL.
- [ ] **Step 3:** Implement. `listing.list_response` / `alerts_response` map rows through `vessel_out` and totals
  through `totals_out` after sorting; `list_response` calls `require_sort`. `export_csv` calls `require_sort` and
  `drop_columns`. `_read_service(request, vessel, existing, profile)`: without `money.edit`, `service_money_sent` →
  403, else `keep_service_money(type, cleaned, existing.service_type, existing.data)` (new service: cleaned as is).
  `service_detail` passes `zero_money=request.profile.can("money.edit")`.
- [ ] **Step 4:** `manage.py test sheet` → all pass (existing tests use full-permission users).
- [ ] **Step 5:** Commit `feat(money): vessels and services send and keep money by permission`.

### Task 3: Bookings, Garbage & Sludge, customers, receipt (the other forms)

**Files:**
- Modify: `sheet/moneyaccess.py`, `sheet/logistics.py` (`booking_to_dict`, `save_booking`), `sheet/disposal.py`
  (`response`, `save` callers in `views.disposal_list` / `disposal_update`), `sheet/customers.py`
  (`customer_to_dict`, `save_customer`), `views.customers_list` / `customer_detail`, `sheet/receipt.py`
  (`services_line`, `prefill`), `views.service_receipt`
- Test: `sheet/tests_money.py` (`FormMoneyApiTests`)

**Interfaces:**
- Produces: `moneyaccess.BOOKING_MONEY = {"hotels": (...), "transfers": (...)}` (the five keys per kind, from
  `logistics.MONEY_KEYS` + currencies + `exchange_rate`); `booking_out(kind, row, profile)`;
  `booking_money_sent(kind, data) -> bool`; `DISPOSAL_ROW_MONEY` (the six figures + `rate_missing`,
  `price_missing`), `disposal_out(response, profile)` (rows' money needs edit, `totals` needs view: absent key);
  `customer_out(row, profile)` (no `rates` without edit); `customers.save_customer(payload, existing=None,
  may_change_rates=True)` now: without it, `"rates" in payload` → 403 `RATES_NEED_MONEY`, absent → stored rates
  kept; `receipt.prefill(service, with_amounts)` / `services_line(service, with_amounts=True)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_booking_routes_hide_money_without_edit` (list, detail, POST / PUT responses, hotels and transfers).
  - `test_booking_save_without_money_keeps_it` (unchanged PUT → version same, no History) and
    `test_new_booking_without_edit_has_no_money` (cost None, currencies "EGP").
  - `test_booking_money_sent_without_edit_is_403`.
  - `test_disposal_rows_and_totals`: `edit_only` gets row money, no `totals`; `view_only` gets `totals`, rows with
    quantities only; PUT response follows the same rule.
  - `test_customer_rates_hidden_and_kept`: `view_only` GET has no `rates`; PUT without `rates` keeps them; PUT
    with `rates` (even unchanged) → 403. (Update the piece-2 test that allowed unchanged rates.)
  - `test_receipt_prefill_amounts_need_edit`: `view_only` with `documents` gets `"Landing"`, admin gets
    `"Landing with cost $120"`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `save_booking(kind, profile, data, existing)` puts the stored money back (new: the
  model defaults) before `bump_if_changed`.
- [ ] **Step 4:** `manage.py test sheet` → pass.
- [ ] **Step 5:** Commit `feat(money): bookings, garbage & sludge, customers and receipt follow money.edit`.

### Task 4: Overviews — Dashboard, Services tags, management Excel, data exports

**Files:**
- Modify: `sheet/moneyaccess.py`, `sheet/dashboard.py` (`response`), `sheet/services.py` (`filtered`),
  `sheet/report.py` (`data`, `_summary`, `CHARTS`, `_layout`), `sheet/dataexport.py` (`sheet`)
- Test: `sheet/tests_money.py` (`OverviewMoneyTests`)

**Interfaces:**
- Produces: `moneyaccess.dashboard_out(response, profile)` (without view: no `cost_egp` / `revenue_egp` /
  `profit_egp` in `totals`, each `months[]` and each `oprs[]`); `MONEY_TAGS = ("Cost", "Revenue", "Rate")`,
  `tags_out(tags, profile)`; `report.CHARTS` values become `(kind, title, table index, [series head names])`
  (e.g. `"summary": ("column", "Profit per port (EGP)", 0, ["Profit (EGP)"])`, `"agents": (..., ["Total"])`).

- [ ] **Step 1: Write the failing tests:**
  - `test_dashboard_money_needs_view` (jobs / counts / `status` still there).
  - `test_services_money_tags_need_view`: a service with no cost and no agent → `edit_only` row `missing ==
    ["Agent"]`, admin `["Agent", "Cost", "Revenue"]`; `missing=1` for `edit_only` drops a row whose only gap is
    Cost.
  - `test_excel_without_view` (read with `tests_dataexport.read` / `tests_management` helpers): no sheet titled
    "Profit by service", no money head in any sheet, no chart on Summary / By month / By line, Agents chart still
    there; admin's workbook byte-equal to before is not required, but its CHARTS still draw (existing
    `tests_management` stays green).
  - `test_data_export_without_view`: hotels / transport / disposal sheets have no `MONEY_HEADS` column; quantities
    and ids stay.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `report.data` drops `"services"` and runs `drop_columns` on each table (head, rows and
  total, same indexes) when `not views(profile)`; `_summary` adds its money notes only with view. `_layout` maps
  series head names to indexes and skips the chart when any is missing. `dataexport.sheet` runs `drop_columns`.
- [ ] **Step 4:** `manage.py test sheet` → pass.
- [ ] **Step 5:** Commit `feat(money): overviews and exports need money.view`.

### Task 5: Front end hides what isn't sent and never sends it back

**Files:**
- Create: `sheet/static/sheet/js/moneyKeys.js` (pure: `SERVICE_MONEY`, `stripMoney(type, data)` — same table
  as the server)
- Modify: `modals/service.js` (money fields, `rateField`, preview, agreed-rate note / `applyRate`, Cancelled → 0,
  `readServiceForm` via `stripMoney`; entry rows carry `dataset.uid` and send `uid`), `modals/booking.js` (money
  section, Cancelled → 0, save omits the five keys), `pages/bookings.js` (Cost / Revenue columns need
  `money.edit`), `pages/disposal.js` (money columns `money.edit`, totals line `money.view`), `modals/customer.js` /
  `pages/customers.js` (rates section and "Agreed rates" column need `money.edit`; save omits `rates`),
  `modals/vessel.js` (total pills, `moneyPillsEl`, rate warning need `money.view`), `modals/summary.js` (calc and
  totals need view, typed amounts need edit), `render/dashboard.js` + `templates/sheet/index.html` (money panels
  `#tbl-money`, `#chart-cost`, `#chart-profit`, the OPR card's cost line rendered only with `money.view`; JS skips
  absent elements), `state.js` / `data.js` (a stored `sort: 'total_cost_egp'` without view → `date`),
  `tools/parsing_test.js`, `tools/ui_smoke_test.js` (marine run)

- [ ] **Step 1: Write the failing parser tests** in `parsing_test.js`: `stripMoney` gives the four server cases of
  Task 1 Step 1 (same inputs, same results).
- [ ] **Step 2:** `cd tools && npm run test:parsing` → FAIL.
- [ ] **Step 3:** Implement `moneyKeys.js` and the screens. Without `money.edit` the service dialog shows type,
  agent, status, billing, quantities / AWB / weight / crew, no preview; Cash to Master shows no money fields.
- [ ] **Step 4:** Extend the smoke run `marine` (has `money.edit`, not `money.view`): the vessel dialog has no
  "Total cost" pill, a service dialog shows the Cost box and the preview, `/api/vessels/?sort=total_cost_egp` →
  403, `/api/dashboard/` is refused (no page). (No demo user for "money.view without money.edit": the Accounts
  employee template is cancelled, Task 6; the backend tests of Tasks 2–4 cover that case.)
- [ ] **Step 5:** `npm run test:parsing`, `npm run test:dom` pass; smoke runs (CLAUDE.md recipe, scratch database,
  `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) for alex, admin, viewer, suez, marine all pass.
- [ ] **Step 6:** Commit `feat(money): screens follow money.view / money.edit`.

### Task 6: Accounts employee template cancelled; docs, full check, review

The user cancelled the Accounts employee template (2026-11-25). Accounts already made with it keep their ticks
(nothing links a person to a template).

**Template files:** `sheet/constants.py` (`TEMPLATES`: remove the `("accounts", "Accounts employee", …)` row),
`tools/ui_smoke_test.js` (admin's Accounts step, ~line 1632: pick template `manager` instead; expect every tick on,
Can column `16 of 16`, saved check `exports` and `vessels.delete` ticked; the "unticking See money" check stays),
`sheet/tests_permissions.py:474` (docstring: say "someone with History but no Hotels / Transport / Port closures
page"), plus any test asserting the template count / keys.

- [ ] **Step 0:** Add `test_templates_are_marine_operations_manager` (`[key for key, *_ in TEMPLATES] ==
  ["marine", "operations", "manager"]`) to `tests_permissions`; run → FAIL; remove the row and fix the smoke step;
  run → PASS; commit `feat(permissions): drop the Accounts employee template`.

**Doc files:** `CLAUDE.md` ("Money permissions" paragraph naming `moneyaccess` and the two tables; Permissions
paragraph: piece 3 built, three templates), `docs/STATUS.md` (piece 3, migration 0026 for the user's database,
left-open item from Decision 7, decision "Accounts employee template cancelled"), `README.md:132` / `SECURITY.md`
(roles, templates, test count), `docs/DEPLOYMENT.md` (what the two money ticks do; remove the Accounts employee
row ~line 310), `docs/NEXT-CHAT.md` (refresh). Leave the dated spec / piece-2 plan as history.

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2:** `cd tools && npm run check` → everything green.
- [ ] **Step 3:** Commit `docs: money permissions`; then one fresh review (opus) of the branch, fix what it finds,
  and ask the user before merging.
