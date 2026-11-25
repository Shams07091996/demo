# New services from the manager's HTML — design (piece 1 of 8)

Date: 2026-11-25. Branch `feature/new-services`.

## Why

A manager drew an HTML prototype (`ARKAS_EGYPT_AGENCY_V19_FINAL_INTEGRATED_TEST.html`) with services the app lacks.
The user wants them in the app, in the app's own style (not copied box for box), Suez Canal being the important one.
This is piece 1 of 8 agreed pieces (then: parcels extras, collection, terminal / berth, crew extras, provider vs ARKAS
cost, document control, reports). The user watches token use: keep it lean.

## What

Five new service types, added to `constants.SERVICE_TYPES` after Fresh Water, before Cash to Master:

| Type | Fields (key, label, kind) | Line label detail | Agreed rate unit |
|---|---|---|---|
| Suez Canal Transit | direction "Direction" choice Northbound / Southbound; originPort "Origin port" text; destinationPort "Destination port" text; expectedTransit "Expected transit" date; etaSuez "ETA Suez" datetime; bookingRef "Booking reference" text; canalAgent "Canal agent" text; convoyNo "Convoy no." text; pilotBoarding "Pilot boarding" datetime; canalEntry "Canal entry" datetime; canalExit "Canal exit" datetime; scaInvoice "SCA invoice no." text | direction | service |
| Surveyors Attendance | count "Number of people" number; names "Names" text (500); attendanceAt "Date and time" datetime | count + " people" | service |
| Supply | description "Description" text (500); quantity "Quantity" number | description | service |
| SIM Cards | quantity "Number of cards" number | quantity + " cards" | unit (per card) |
| Tourism Tours | tour "Tour" text; passengers "Passengers" number; tourDate "Date" date | tour | service |

Suez Canal's Cost box is labelled **"SCA charges"** and starts in **USD**; everything else as today (one cost, one
revenue, currencies, own exchange rate). Cash to Master (= the HTML's CTM) gets two fields: reference "Reference"
text, beneficiary "Beneficiary" text. The HTML's transit status is left out (the service status covers it), as are
the surveyors' permit type / will travel and SIM purchase / other cost sums (the user types cost totals).

## Approach (user picked A)

**A. One field table per service type** (picked): `constants.SERVICE_FIELDS = {type: [(key, label, kind, extra)]}`
with kinds `text` (max 160, or the given max), `number` (≥ 0, like `_amount`), `date`, `datetime` (Cairo local
`YYYY-MM-DDTHH:MM`), `choice` (fixed list). The existing one-field services move into it with their keys unchanged
(Medical Treatment patientName, Certificates certName, Fresh Water quantity "Quantity (tons)"), so no data migration.
`SINGLE_EXTRAS` is replaced. Per type the table also names the line-label field and a unit suffix, the cost label /
default currency (Suez). The "unit" rate keeps multiplying the field `quantity` (Fresh Water, SIM Cards both use that key).
**B. Hand-built forms per service** — rejected: five times the code and tests, services drifting apart, more tokens.

## How it flows

- **One source:** the table is in Python; `views.index` sends it to the browser in a `json_script` (as other page
  context), read in `config.js` (replaces `SINGLE_EXTRA`). No JS twin list.
- **Validation** (`validators`): `_clean_details(service_type, raw)` cleans each field by kind (refused, never fixed:
  too long, not a number, negative, bad date / datetime, value not in the choice list → 400 naming the label); unknown
  keys dropped; empty = "". Used by single types and Cash to Master.
- **Money** (`finance`): single types unchanged except `_single_label` reads the table's label field (+ suffix).
- **Agreed rates:** `RATE_UNITS` gets the five types (`js/rates.js` unchanged: it already multiplies `quantity`).
- **Screens:** the service form draws the fields from the table (two per row; choice as a select; date / datetime
  inputs); the service card and the Summary list the filled fields as "Label: value" (dates as dd.mm.yyyy, times
  dd.mm.yyyy HH:MM); built with `dom.js` only.
- **Exports:** the money line label (Calculations, its export, the management Excel's service lines) carries the
  label field as today; no new columns. The Services page / export unchanged.
- **Permissions / money:** detail fields are not money (`moneyaccess`, `moneyKeys.js` unchanged). Statuses, billing,
  agent, accounting close, receipt (type label as its line) work as for any single service.
- **Dashboard / report:** `report.SERVICE_ORDER` follows `SERVICE_TYPES`; new types appear when they have data.

## Non-goals

The other seven pieces; Master-data lists for canal agents / ports (free text); computing SIM cost from unit
prices; a separate transit status.

## Tests

Validation per kind (each refusal message), unknown keys dropped, old Medical / Certificates / Fresh Water data still
valid and labelled as before; finance line labels for the five types; rate unit for SIM Cards; index page carries the
table; smoke test: add a Suez Canal Transit with direction, entry /
exit and SCA charges, see it on the card and the Summary. Docs: STATUS, CLAUDE.md (services), README / SECURITY counts.

## Left to the builder

Field order within a row, the exact table shape, the label suffix wording ("3 people", "5 cards").
