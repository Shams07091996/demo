# Garbage & Sludge — design (approved 2026-11-19)

## Why

Almost every vessel has garbage and sludge removed. The user wants to type only the **quantities** and have the
money worked out from **monthly prices they set**, with the profit visible in **USD and EGP**.

## What the user decided

- Prices are **per m³, in USD, per month and per port** (Alexandria, Port Said, Damietta, Suez can differ): garbage
  cost, garbage revenue, sludge cost, sludge revenue.
- The service is **added by hand** to a vessel, like the other services (the exceptions simply don't get one).
- It counts in the vessel's figures, the Dashboard and the Summary **like any other service**.
- The **Calculations page** shows its lines in **USD and EGP**, with a USD total.

## Approaches considered

1. **A new service type + a monthly price table (chosen).** Quantities on the service; prices looked up from the
   vessel's port and month; EGP with the month's exchange rate. Same live maths as everything else (`finance.py`).
2. Copy the price into the service when it is saved. Freezes history, but a price fixed later never reaches services
   already entered, and it differs from how exchange rates work today. Rejected for now (the "keep the rate used by
   each service" idea in STATUS would cover both together).
3. A Fresh-Water-style service with cost / revenue typed each time. What the user wants to stop doing. Rejected.

## Design

- **Service type "Garbage & Sludge"**: `data = {"garbage": m³, "sludge": m³}` (numbers ≥ 0, refused otherwise). Needs an
  agent like every service.
- **`DisposalPrice`** (one row per month + port): `garbage_cost`, `garbage_revenue`, `sludge_cost`, `sludge_revenue`,
  USD per m³, ≥ 0. **Admins only** change them (like exchange rates); everyone may read (port users: their port).
  Recorded in the change history. Shown and edited on the **Exchange rates** page ("Garbage & Sludge prices").
- **Money** (`finance.py`): two lines, `Garbage · 3 m³` and `Sludge · 2 m³`; cost = price × quantity (USD), revenue
  likewise, converted with the vessel's month rate (missing → `rate_missing`, as today). A quantity with no price for
  that port / month gives a line flagged `price_missing` with no money, so it shows up instead of silently counting 0.
- **Calculations**: each row whose money is all in USD also carries its USD cost / revenue / profit; the totals add a
  USD total of those rows. The page shows the USD profit next to the EGP figures.
- **Live preview** in the service form uses the vessel's price and rate, same rounding (`calc.js`).

## Builder's calls

- Prices change live: editing a month's price changes that month's vessels (like exchange rates).
- Quantities in m³ with up to 2 decimals shown; price per m³ in USD.
- No automatic service on new vessels; no Missing-details alert for vessels without one.
