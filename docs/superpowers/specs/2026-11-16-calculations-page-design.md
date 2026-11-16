# Calculations page

Date: 2026-11-16 · Status: draft for approval · Size: project

## Why

The company wants **its own profit picture**, including hotels and transport, and to see **every calculation behind
it**: what was paid, what was earned, in which currency, at which exchange rate, and the result in EGP. Today the
money is spread over each vessel's services; hotel and transport prices are stored but counted nowhere, and two
service types (Crew Change, Others / Remarks) carry no money at all.

Success: someone with edit rights opens **💰 Calculations**, picks a date range and an OPR, and sees one row per money
line with its working, plus total revenue, cost and profit for exactly those rows.

## Goals

- **Every service has cost and revenue** — including Crew Change and Others / Remarks (user: "all services have a
  revenue and costs").
- **Hotel stays and transfers have cost (what we pay) and revenue (what we get)** instead of today's single price.
- A **Calculations** page listing every money line — services, multi-entry service entries, hotel stays, transfers —
  for a **From–To range on the vessel date** and an **OPR**, with totals.
- Each row shows its **working**: original amount, currency, the rate used and where it came from, the EGP result,
  and the line's profit.

## Non-goals

- Invoicing / statements per OPR, supplier payables, exports (CSV / Excel), printing. (Possible later.)
- Changing what the vessel totals include for bookings: **hotel and transport money stays out of vessel totals, the
  Summary of services and the Dashboard** (earlier user decision). Crew Change / Others money, being services, does
  count in vessel totals from now on.
- Storing computed money anywhere (approach A: computed on each request).

## Anti-goals

- A number on this page that disagrees with the same service's figure on the vessel (one set of maths only).
- A read-only user being able to **change** anything (they may see all money — user decision, see below).
- A port user seeing another port's money.

## Who sees what

| Role | Calculations page |
|---|---|
| admin | all ports, port filter |
| port user | own port only |
| readonly | all ports, port filter, **view only** (user: "read only users can see money everywhere") |

## Approaches

| | What | Trade-off |
|---|---|---|
| **A. Compute on each request (chosen)** | Vessels in range / OPR / port → `finance` maths per service and per booking → rows and totals | Always matches the vessel figures; rate changes show at once; work grows with the range (fine for thousands of rows; cache later if needed) |
| B. Ledger table written on every save | Pre-computed rows, SQL sums | Every edit, delete and **exchange-rate change** must rewrite rows; any miss makes the page silently disagree |
| C. Sum in the browser | Download everything, add up client-side | Against "data from the server"; heavy |

The user picked **A**.

## Design

### 1. Money on every service

- `Crew Change` and `Others / Remarks` gain the standard single-service money fields (`cost`, `costCurrency`,
  `revenue`, `revenueCurrency`, `exchangeRate`) next to their existing data (crew lists / note).
- `NO_MONEY_TYPES` becomes empty (or is removed): `finance.compute`, `validators.clean_service_data`, `calc.js`
  (live preview), the service form, the Summary of services and the vessel dialog treat them like Medical Treatment
  (single cost / revenue). Existing saved Crew Change / Others services simply have no money until edited.
- Consequence (accepted): their money now counts in vessel totals and the Dashboard, like any service.

### 2. Cost and revenue on bookings

- `HotelStay`: `price_per_night` → `cost_per_night`; add `revenue_per_night`; `currency` → `cost_currency` and
  `revenue_currency`; keep one optional `exchange_rate`. Both amounts are **per room per night**; the stay's cost /
  revenue = amount × nights.
- `Transfer`: `price` → `cost`; add `revenue`; same two currencies and one optional `exchange_rate`. Per trip.
- Migration keeps any existing price as the cost and copies `currency` into both currencies (there are no bookings in
  the user's real database yet, but test / dev data may have some).
- Booking dialog: the Price section becomes **Cost** and **Revenue** (amount + currency each), rate field shown when
  either is USD. Hotels / Transport lists show **Cost** and **Revenue** columns instead of Price, **to every role**:
  read-only users now see booking money too (user decision; this reverses the earlier rule that hid booking
  prices from them — `logistics.booking_to_dict` stops leaving money out, and its test is updated).
- USD conversion as services: the booking's own rate if given, else the **vessel's month rate**; none → counted 1:1
  and flagged (as services are today).

### 3. One explanation function

`finance` gains a function that returns the **lines** of one service (one line for a single service, one per entry
for Delivery Parcels / Courier / Landing, one for Cash to Master), each with
`{label, cost: {amount, currency, rate, egp} | null, revenue: {...} | null, profit_egp, rate_source, rate_missing}`
where `rate_source` is `"own"` (the item's rate) or `"month"` (the vessel's month rate). `finance.compute` is
re-expressed on top of it so the vessel figures and this page **cannot** diverge. Bookings get the same line shape
(hotel: amount × nights shown in the working).

Cash to Master line: revenue = our share (percentage or fixed), shown as "5% of USD 1,000.00"; the remainder paid to the
master is shown as text, **not** as a cost (as today).

### 4. The page and its API

`GET /api/calculations/?from&to&opr&port&sort&dir&page&page_size` (every role; port users kept to their port):
- Range on **vessel date**, inclusive; empty ends open; default in the page: the current month.
- `opr`: exact OPR value, or empty for all. The page's OPR dropdown lists Master-data OPR values plus "All".
- Rows: every service line and booking line of every vessel in scope; **lines with neither cost nor revenue are left
  out** (e.g. a crew change with no money entered).
- Each row: `vessel {id, name, date, opr, port}`, `kind` (service type, "Hotel stay" or "Transfer"), `label` (e.g.
  "Fresh Water · 40 t", "Parcels · AWB 123 · 3 kg", "Hotel · Hilton · 2 nights", "Transfer · Airport → Hotel"),
  `cost`, `revenue`, `profit_egp`, `rate_missing`.
- `totals`: `revenue_egp`, `cost_egp`, `profit_egp`, `lines`, `rate_missing_lines` — over **all** filtered rows,
  not just the page.
- Sort: `date` (default, newest first), `vessel`, `opr`, `kind`, `cost`, `revenue`, `profit`. Paging 10 / 25 / 50 / 100
  as elsewhere.

Page layout (no cards — the user prefers lean screens):

```
💰 CALCULATIONS   From [01.11.2026] To [30.11.2026]   OPR [All ▾]   Port [All ▾]
Revenue LE 48,250.00 · Cost LE 31,900.00 · Profit LE 16,350.00 · 37 lines   ⚠ 2 lines use USD without a rate (counted 1:1)

Date        Vessel      OPR  Item                      Cost                         Revenue                       Profit LE
15.11.2026  MSC AURORA  MSK  Fresh Water · 40 t         EGP 2,000.00                 USD 100.00 × 50.00 = 5,000.00  3,000.00
15.11.2026  MSC AURORA  MSK  Hotel · Hilton · 2 nights   USD 80.00 × 2 × 50.00 = 8,000  EGP 4,500.00 × 2 = 9,000.00     1,000.00
```

Sidebar: **💰 Calculations** after Transport, shown to every role. Clicking a row's vessel name opens
that vessel's Summary of services.

## Testing

Backend: lines for each service type (single, multi per entry, Cash to Master, Crew Change / Others with and without
money); USD with own rate / month rate / no rate (flag); hotel × nights; transfer; totals over all rows not the page;
range on vessel date (a booking dated after the range but on an in-range vessel counts); OPR filter exact; port scoping;
read-only sees the page and booking money but cannot write anywhere; **page total for one vessel equals that vessel's `total_cost_egp` / profit for its services**; booking
money still absent from vessel totals; migration keeps old prices as cost. Front end smoke: read-only sees the page and the money columns;
totals line and rows render; a USD row shows its rate; OPR filter narrows; Crew Change money field in the service form;
booking dialog shows cost and revenue.

## Left to the builder

Module layout (e.g. a `calculations.py` next to `listing.py` and `logistics.py`), exact JSON keys within the shapes
above, label wording details, CSS within existing styles.
