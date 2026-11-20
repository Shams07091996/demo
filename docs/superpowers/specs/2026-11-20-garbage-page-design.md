# Garbage & Sludge page — design

Replaces the "Garbage & Sludge" service of 2026-11-19 (`2026-11-19-garbage-sludge-design.md`), which the user found
the wrong shape: quantities belong on a page of their own, next to every vessel, and the prices are minimums plus an
extra per unit, not a flat price per m³. Also: the Master data lists fold shut.

## Why

Almost every vessel has garbage (m³) and sludge (tons). The user wants to go down the month's vessels typing the two
quantities and see revenue, cost and profit in EGP and USD at once, from prices set once a month per port.

## Decisions (the user's)

- Prices per **month and port** (ports charge differently), set on the Exchange rates page, admin only.
- Four price blocks: garbage revenue, garbage cost, sludge revenue, sludge cost. Each has its own **minimum quantity**,
  **minimum amount** with its **currency** (revenue USD, cost EGP by default; either can be switched) and an **extra
  amount per m³ / t above the minimum**.
- Amount of a block for quantity q: q empty or 0 → 0; q ≤ minimum quantity → minimum amount; else minimum amount +
  (q − minimum quantity) × extra. Below the minimum the full minimum is charged / paid.
- **Copy from last month**: fills the form with that port's most recent earlier month; the admin saves.
- New sidebar page **Garbage & Sludge**: the vessels of the shared From–To range and port; per vessel garbage m³,
  sludge t, revenue / cost / profit in EGP and USD, a Hide button. Filter: All / With garbage or sludge / Not entered
  yet / Hidden (with Bring back). Totals in EGP and USD.
- Hide = "no garbage or sludge": hidden from the page's normal views, counted 0.
- The money counts on this page and on **Calculations** only, not in the vessel's totals (like hotels and transport).
- Port users enter quantities for their port's vessels; read-only users look; admins everything.
- The old service and its prices are deleted (fake data).
- Master data: each of the 8 lists is folded shut and opens on a click on its name.

## My calls (told to the user)

- A quantity saves when the box is left (no Save button). Hiding clears the quantities.
- One `VesselDisposal` row per vessel (garbage, sludge, hidden), made on first edit, instead of columns on Vessel.
- Conversion with the vessel's month rate. On the page a figure that needs a missing rate is left blank and the row
  flagged; a missing price for that month and port flags the row and gives no money. On Calculations the lines follow
  that page's rule for every line (USD counted 1:1, flagged), so its totals stay sums.
- Each block's amount is rounded to the cent in its own currency, then converted and rounded again.
- No paging on the new page (a month is a few hundred vessels at most).
- The Master data lists use `<details>` / `<summary>`, closed by default.

## Approaches considered

1. **Separate table per vessel (chosen)**: keeps Vessel and its forms untouched, history per row, easy to remove.
2. Columns on Vessel: fewer joins but mixes this page into every vessel API and form.
3. Keep it a service type: what the user just rejected.
