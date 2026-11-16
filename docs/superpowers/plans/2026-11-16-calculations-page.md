# Calculations Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every service and every hotel stay / transfer has cost and revenue, and a 💰 Calculations page lists every
money line with its working (amount × rate = EGP) for a vessel-date range, OPR and port, with totals.

**Architecture:** `finance.py` gains `service_lines()` — the single source of the money maths; `compute()` becomes a
sum over it, so vessel figures and the new page can't disagree. Bookings get cost / revenue fields and a matching
`booking_line()`. A new `sheet/calculations.py` gathers lines for vessels in scope (computed per request, approach A),
filters, sorts, pages and totals. Front end: one new page module plus small changes to the service form and booking
dialog.

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test. Git repo on `main`: work on a branch
`feature/calculations-page`, one commit per task.

**Spec:** `docs/superpowers/specs/2026-11-16-calculations-page-design.md` (approved). Read `CLAUDE.md` and `docs/STATUS.md`.

## Global Constraints

- Range is on the **vessel date**, inclusive, open ends allowed; the page defaults to the current month.
- Hotel / transport money appears **only** on the Calculations page (and the Hotels / Transport lists) — never in vessel
  totals, the Summary of services or the Dashboard. Crew Change / Others money **does** count in vessel totals (they are
  services).
- USD → EGP: the item's own rate if set, else the vessel's month rate (`ExchangeRate`), else 1:1 and flagged
  `rate_missing` — exactly as `finance.compute` does today.
- Every role sees the page and all money (user decision); read-only users still can't write anything.
- Port users are pinned to their port (`access.scoped_vessels`).
- Lines with neither cost nor revenue (both missing or 0) are left out.
- Page / rows-per-page 10 / 25 / 50 / 100; totals cover all filtered rows, not the page.
- Cash to Master: revenue = our share; the remainder to the master is shown as text, never as cost.

## Review Focus

1. **USD with no rate anywhere** → counted 1:1, the row and the totals line show the ⚠ count (Task 4 test).
2. **A line with only revenue or only cost** is shown; a line with neither is not (Task 2 test).
3. **OPR filter is exact** (`"ark "` ≠ `"ARK"`), like the vessel list's `opr` (Task 4 test).
4. **Rounding:** for one vessel, the sum of its service lines equals `total_cost_egp` / `total_profit_egp` to the cent (Task 2 test).
5. **A hotel stay checking in after the range on an in-range vessel** is counted (Task 4 test).

---

### Task 1: Money on Crew Change and Others / Remarks

**Files:** `sheet/constants.py`, `sheet/validators.py`, `sheet/finance.py`; test `sheet/tests_calculations.py` (new)

**Interfaces:** Produces: `NO_MONEY_TYPES` removed (no service type is money-free); `clean_service_data("Crew Change", raw)`
returns the crew lists **plus** `cost, costCurrency, revenue, revenueCurrency, exchangeRate`; `"Others / Remarks"` returns
`note` plus the same money keys.

- [ ] **Step 1: Failing tests**

```python
def test_crew_change_and_others_carry_money(self):
    data = clean_service_data("Crew Change", {"onSigners": [{"name": "A"}], "cost": "100", "revenue": "250",
                                              "revenueCurrency": "USD", "exchangeRate": "50"})
    self.assertEqual((data["onSigners"][0]["name"], data["cost"], data["revenue"], data["revenueCurrency"]), ("A", 100.0, 250.0, "USD"))
    self.assertEqual(finance.compute("Crew Change", data, None)["profit_egp"], 12400.0)
    note = clean_service_data("Others / Remarks", {"note": "x", "cost": "5"})
    self.assertEqual((note["note"], note["cost"], finance.compute("Others / Remarks", note, None)["cost_egp"]), ("x", 5.0, 5.0))

def test_crew_change_money_counts_in_vessel_totals(self):  # ApiTestCase
    Service.objects.create(vessel=self.alex_vessel, service_type="Crew Change", data={"cost": 10, "costCurrency": "EGP"})
    self.assertEqual(self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/")[1]["total_cost_egp"], 10.0)
```

- [ ] **Step 2:** `python manage.py test sheet.tests_calculations` → FAIL. **Step 3:** implement (reuse `_clean_single`'s money keys; drop `NO_MONEY_TYPES` from `finance.compute`). **Step 4:** PASS + full suite. **Step 5:** commit `feat: cost and revenue on Crew Change and Others`.

---

### Task 2: `finance.service_lines` — one source of the money maths

**Files:** `sheet/finance.py`; test `sheet/tests_calculations.py`

**Interfaces:**
- Produces `service_lines(service_type, data, month_rate) -> list[dict]`. A line:
  `{"label": str, "note": str, "cost": Money|None, "revenue": Money|None, "cost_egp": float, "revenue_egp": float,
  "profit_egp": float, "rate_source": "own"|"month"|"", "rate_missing": bool}` with
  `Money = {"amount": float, "currency": "EGP"|"USD", "times": int, "rate": float|None, "egp": float}` (`rate` only for USD;
  `times` is 1 for services). `cost_egp` etc. are **unrounded**; JSON rounding happens in Task 4.
- Labels: single types `"Fresh Water · 40 t"`, `"Medical Treatment · <patient>"`, `"Certificates · <cert>"`, others just
  the type; multi entries `"Delivery Parcels · AWB 123 · 3 kg"` (AWB / weight parts only when present); Cash to Master
  `"Cash to Master"` with `note` `"5% of USD 1,000.00 · USD 950.00 to the master"` (or `"fixed USD 50.00 · …"`).
- `compute()` keeps its return shape but sums `service_lines` (per-entry `entries` from the multi lines; `to_master_egp`
  from Cash to Master as today).

- [ ] **Step 1: Failing tests**

```python
def test_lines_show_the_working(self):
    [line] = service_lines("Fresh Water", {"quantity": 40, "cost": 2000, "costCurrency": "EGP", "revenue": 100,
                                           "revenueCurrency": "USD"}, Decimal("50"))
    self.assertEqual((line["label"], line["revenue"]["rate"], line["revenue"]["egp"], line["rate_source"], line["profit_egp"]),
                     ("Fresh Water · 40 t", 50.0, 5000.0, "month", 3000.0))
    own = service_lines("Fresh Water", {"revenue": 1, "revenueCurrency": "USD", "exchangeRate": 48}, Decimal("50"))[0]
    self.assertEqual((own["rate_source"], own["revenue"]["egp"]), ("own", 48.0))
    flagged = service_lines("Landing", {"entries": [{"revenue": 10, "revenueCurrency": "USD"}]}, None)[0]
    self.assertEqual((flagged["rate_missing"], flagged["revenue"]["egp"]), (True, 10.0))

def test_multi_entries_and_cash_to_master(self):
    lines = service_lines("Delivery Parcels", {"entries": [{"awb": "123", "weight": 3, "cost": 10}, {"cost": 5}]}, None)
    self.assertEqual([l["label"] for l in lines], ["Delivery Parcels · AWB 123 · 3 kg", "Delivery Parcels"])
    [cash] = service_lines("Cash to Master", {"amount": 1000, "amountCurrency": "USD", "percentage": 5}, Decimal("50"))
    self.assertEqual((cash["cost"], cash["revenue_egp"]), (None, 2500.0))
    self.assertIn("to the master", cash["note"])

def test_empty_lines_are_dropped_but_one_sided_lines_stay(self):
    self.assertEqual(service_lines("Others / Remarks", {"note": "hello"}, None), [])
    self.assertEqual(len(service_lines("Certificates", {"revenue": 5}, None)), 1)

def test_compute_equals_the_sum_of_lines_to_the_cent(self):
    data = {"entries": [{"cost": 0.333, "revenue": 0.335}] * 3}
    lines = service_lines("Landing", data, None)
    self.assertAlmostEqual(finance.compute("Landing", data, None)["profit_egp"], round(sum(l["profit_egp"] for l in lines), 2), places=2)
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + full suite (all existing finance tests must still pass unchanged). **Step 5:** commit `refactor: money maths as lines (service_lines)`.

---

### Task 3: Cost and revenue on bookings

**Files:** `sheet/models.py`, migration `0008_booking_cost_and_revenue.py`, `sheet/validators.py`, `sheet/logistics.py`; tests `sheet/tests_logistics.py`, `sheet/tests_calculations.py`

**Interfaces:**
- `HotelStay`: `cost_per_night`, `revenue_per_night` (Decimal 12,2, null), `cost_currency`, `revenue_currency` (EGP/USD), `exchange_rate`. `Transfer`: `cost`, `revenue`, same currencies, `exchange_rate`. Migration: `price_per_night` → `cost_per_night`, `price` → `cost`, `currency` copied into both currencies then removed.
- Cleaners accept `cost_per_night` / `revenue_per_night` (hotels) or `cost` / `revenue` (transfers) with `cost_currency`, `revenue_currency`, `exchange_rate`; same errors as today (`"Prices cannot be negative."`, `"Exchange rate must be a positive number."`).
- `booking_to_dict` returns these keys **for every role** (remove the read-only hiding).
- `logistics.booking_line(kind, obj, month_rate) -> line` (Task 2 shape): hotel label `"Hotel · <hotel> · <n> nights"`, Money `times = nights`; transfer label `"Transfer · Airport → Hotel"`.

- [ ] **Step 1: Failing tests** — update `BookingData` / `payload` to the new keys; replace `test_read_only_sees_no_prices_and_cannot_write` with `test_read_only_sees_booking_money_but_cannot_write` asserting `cost_per_night == 80.0` for `viewer` and 403 on POST; add:

```python
def test_hotel_line_multiplies_by_nights(self):
    stay = HotelStay(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=2,
                     cost_per_night=Decimal("80"), cost_currency="USD", revenue_per_night=Decimal("4500"), revenue_currency="EGP")
    line = booking_line("hotels", stay, Decimal("50"))
    self.assertEqual((line["label"], line["cost"]["times"], line["cost_egp"], line["revenue_egp"], line["profit_egp"]),
                     ("Hotel · HILTON · 2 nights", 2, 8000.0, 9000.0, 1000.0))
```

- [ ] **Step 2:** FAIL. **Step 3:** implement + `DJANGO_DEBUG=1 python manage.py makemigrations sheet -n booking_cost_and_revenue` (edit in the data step). **Step 4:** PASS + full suite. **Step 5:** commit `feat: cost and revenue on hotel stays and transfers`.

---

### Task 4: Calculations API

**Files:** create `sheet/calculations.py`; modify `sheet/views.py`, `sheet/urls.py`; test `sheet/tests_calculations.py`

**Interfaces:**
- `calculations.response(profile, params) -> {"rows", "page", "page_size", "count", "pages", "totals"}`; route `GET api/calculations/` (name `api_calculations`, `@json_api`, all roles).
- Params: `from`, `to`, `opr` (exact; empty = all), `port`, `sort` in `date, vessel, opr, kind, cost, revenue, profit` (default `date`, `dir` default `desc`), `page`, `page_size` — via `listing.date_param` / `int_param`; same 400 messages.
- Row: `{"vessel": {"id","name","date","opr","port"}, "kind": <service type> | "Hotel stay" | "Transfer", "label", "note", "cost", "revenue", "cost_egp", "revenue_egp", "profit_egp", "rate_source", "rate_missing"}` with money rounded to 2 for JSON.
- Totals: `{"revenue_egp", "cost_egp", "profit_egp", "lines", "rate_missing_lines"}` from unrounded values, then rounded.
- Order inside a vessel: its services in id order, then hotel stays, then transfers; default sort `date desc` then vessel id desc.

- [ ] **Step 1: Failing tests** (fixtures, **no** `ExchangeRate` rows: ALEX SHIP with Fresh Water in USD using its own `exchangeRate`, Landing (2 EGP entries), and Certificates with a USD revenue and no rate (the one flagged line); a hotel stay on ALEX SHIP checking in **after** `to`; SUEZ SHIP with one service)

```python
def test_rows_and_totals(self):
    data = self.get("admin", **{"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria"})
    self.assertEqual(data["count"], 5)                         # fresh water, 2 landing entries, usd line, late hotel stay
    self.assertEqual(data["totals"]["rate_missing_lines"], 1)
    self.assertAlmostEqual(data["totals"]["profit_egp"], sum(r["profit_egp"] for r in data["rows"]), places=2)

def test_service_lines_match_the_vessel_figures(self):
    vessel = self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/")[1]
    rows = [r for r in self.get("admin", page_size=200)["rows"] if r["vessel"]["id"] == self.alex_vessel.id
            and r["kind"] not in ("Hotel stay", "Transfer")]
    self.assertAlmostEqual(sum(r["cost_egp"] for r in rows), vessel["total_cost_egp"], places=2)
    self.assertAlmostEqual(sum(r["profit_egp"] for r in rows), vessel["total_profit_egp"], places=2)

def test_opr_is_exact_and_port_users_are_pinned(self):
    self.assertEqual(self.get("admin", opr="ark")["count"], 0)
    self.assertEqual({r["vessel"]["port"] for r in self.get("alex", port="suez")["rows"]}, {"alexandria"})

def test_every_role_can_read_and_paging_totals_cover_everything(self):
    page = self.get("viewer", page_size=1)
    self.assertEqual((len(page["rows"]), page["totals"]["lines"]), (1, page["count"]))
    self.assertEqual(self.status("admin", sort="price"), 400)
```

- [ ] **Step 2:** FAIL. **Step 3:** implement (scoped vessels in range / port, `opr` exact, prefetch services, hotel_stays, transfers; `service_lines` + `booking_line`; sort and slice in Python as `listing.py` does). **Step 4:** PASS + full suite. **Step 5:** commit `feat: calculations API`.

---

### Task 5: Front end — service money, booking cost / revenue

**Files:** `js/config.js` (drop `NO_MONEY`), `js/calc.js`, `js/components.js`, `js/modals/service.js` (Crew Change: crew editor then Revenue / Cost / rate / preview; Others: note then the same), `js/modals/summary.js`, `js/modals/booking.js` (Cost and Revenue rows, rate shown when either is USD), `js/pages/bookings.js` (Cost and Revenue columns for every role); test `tools/ui_smoke_test.js`

- [ ] **Step 1: Failing smoke checks** — Crew Change form has `[name=revenue]` and `[name=cost]` and saving 100 EGP cost shows `LE 100.00` in the vessel dialog; hotel dialog has `[data-bf="cost"]`, `[data-bf="revenue"]`, `[data-bf="cost_currency"]`, `[data-bf="revenue_currency"]`; Hotels list header has `Cost/night` and `Revenue/night` for **viewer** too; Transport has `Cost`, `Revenue`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** smoke ×3 roles + parser tests PASS. **Step 5:** commit `feat: money fields for every service and booking`.

---

### Task 6: Front end — the Calculations page

**Files:** create `js/pages/calculations.js`; modify `index.html` (nav item `💰 Calculations` after Transport, page section `page-calculations` with `c-from`, `c-to`, `c-clear`, `c-opr`, `c-port`, `c-totals`, `c-head`, `c-tbody`, `c-empty`, `c-pager`), `router.js` (`TITLES.calculations`), `actions.js` (`calc-page` step), `app.css`; test `tools/ui_smoke_test.js`

**Interfaces:** `calculationsPage.load()`; OPR dropdown = `optionValues('opr')` plus "All"; money cells render `Money` as `USD 100.00 × 50.00 = 5,000.00` (with `× n` for nights, no rate part for EGP); ⚠ on rows with `rate_missing`; totals line `Revenue LE … · Cost LE … · Profit LE … · N lines` plus `⚠ N lines use USD without a rate (counted 1:1)` when N > 0; the vessel name is a `data-act="summary"` link.

- [ ] **Step 1: Failing smoke checks** (all roles) — sidebar now 8 pages (7 for viewer) with `calculations` after `transport`; page shows the totals line and at least one row for MSC AURORA's Fresh Water with `USD` and `×`; choosing OPR `MSK` keeps MSC AURORA rows, choosing `ARK` shows ARKAS STAR only (or the empty text); rows-per-page 10/25/50/100.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** all roles PASS. **Step 5:** commit `feat: calculations page`.

---

### Task 7: Docs

`README.md` (Pages table row, test count), `SECURITY.md` (test count), `CLAUDE.md` (Architecture: `finance.service_lines`, `calculations.py`), `docs/STATUS.md` (move Calculations to "Built"). Final run: backend suite, parser tests, smoke ×3. Commit `docs: calculations page`.
