# Garbage & Sludge Implementation Plan

> Executed inline (superpowers:executing-plans), test first, branch `feature/garbage-sludge`.

**Goal:** a "Garbage & Sludge" service whose money comes from quantities × monthly per-port USD prices.

**Spec:** `docs/superpowers/specs/2026-11-19-garbage-sludge-design.md`

## Global constraints

- Money is worked out only in `finance.py`; amounts rounded once in `finance.money`; the front end mirrors it in `calc.js`.
- Input refused, never silently fixed (`validators.py`); negative amounts refused.
- Admin-only writes for prices (`access.require_admin`), audit + change history like exchange rates.
- Screens built with `dom.js` only; no innerHTML / inline style strings; icons from the sprite.
- LF line endings; `npm run check` green; smoke test for admin / alex / viewer / suez on a scratch database.

## Tasks

1. **Prices** — `DisposalPrice` model + migration `0015_disposal_price`, history signal, admin registration;
   `GET/POST /api/disposal-prices/`, `DELETE /api/disposal-prices/<id>/`; validation (month, known port, four
   numbers ≥ 0); admin-only writes; port users read their port only. Tests: `tests_disposal.PriceApiTests`.
2. **Service + money** — `"Garbage & Sludge"` in `SERVICE_TYPES`; `clean_service_data` keeps `garbage` / `sludge`
   (≥ 0); `serializers.disposal_prices()`; `finance.service_lines` / `compute` take the vessel's prices; two lines with
   `times` = quantity; `price_missing`; `vessel_to_dict` attaches `disposal_price`; callers (listing, dashboard, views,
   calculations) pass the prices. Tests: `tests_disposal.MoneyTests`.
3. **Calculations** — USD cost / revenue / profit on all-USD rows, USD totals. Tests: `tests_disposal.CalculationsTests`.
4. **Front end** — prices section on the Exchange rates page (admin form, delete); the service form (two quantity
   fields, live preview incl. USD); Calculations USD figures; `calc.js` mirror.
5. **Seed, smoke test, docs** — `seed_demo` adds this month's Alexandria prices; smoke test: admin saves a price,
   alex adds the service and sees the figures, Calculations shows USD; README / SECURITY counts, STATUS, CLAUDE.md.

## Review focus

- A quantity without a price for that port / month (must be visible, not a silent 0).
- A vessel moved to another port or month (its prices follow).
- Port users trying to write or read other ports' prices.
- Rounding: lines add up to totals in USD and EGP.
- Deleting a price used by vessels (figures fall back to price missing).
