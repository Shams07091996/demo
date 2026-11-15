# Hotels and Transport pages

Date: 2026-11-16 · Status: draft for approval · Size: project

## Why

Crew coming or going on a crew change often need a hotel and / or a car between the airport, a hotel and the port.
The people who look after that are **not** vessel people: they need one place that shows every hotel stay and every
transfer — who, where, when, from which vessel — without digging through vessels. Today none of this is recorded.

Success: staff can open **🏨 Hotels** or **🚗 Transport**, pick a date range and port, and see every booking in it with
the guest and vessel; the people who arrange them enter each booking once, on that page, with its price, so the
upcoming calculations page can add the money up.

## The cases (from the user)

Per crew member of a crew change, any of:
1. transport only — airport → port;
2. hotel only — a hotel (from Master data) and a number of nights;
3. both — airport → hotel, the stay, then hotel → port;
4. off-signers the other way — port → airport, sometimes with a hotel night first.

## Goals

- Two new sidebar pages, **Hotels** and **Transport**, each a list with date range, port filter, search, sorting,
  paging (10 / 25 / 50 / 100), and **+ Add** / edit / delete for users who may edit.
- A booking is entered on its page: pick the **vessel**, then the **guest** from that vessel's crew change (or type a
  name), then the booking details and an optional price.
- **Hotels** become a Master data list (like OPR / POC / Agent).
- Prices are stored with each booking for the calculations page.

## Non-goals

- Who performs a transfer (driver, company, car, plate) — not recorded (user: "from, to, when, who and which vessel
  is enough").
- Hotel / transfer money in vessel totals, the Summary of services, the Dashboard or the CSV — **calculations page
  only** (user decision).
- The calculations page itself; exports / printing of these lists; changes to the Crew Change editor.

## Anti-goals

- A port user sees or edits another port's bookings.
- A read-only user sees prices.
- Editing or removing a crew member later silently changes or breaks bookings already made.

## Who sees what

| Role | Sees | Can add / edit / delete | Sees prices |
|---|---|---|---|
| admin | all ports (port filter) | everything | yes |
| port user | own port only | own port's bookings | yes |
| readonly | all ports (port filter) | nothing | **no** |

A booking's port is its vessel's port; every query goes through `access.scoped_vessels` (via the vessel).

## Approaches

| | What | Trade-off |
|---|---|---|
| **A. Two tables, one per page (chosen)** | `HotelStay` and `Transfer` models, each with its own API and page | Exact fields and simple checks per kind; two similar sets of code, sharing the list machinery |
| B. One "booking" table with a type | One model / API for both, unused fields empty | Every check and query branches on type; half-empty rows; tangles as the pages diverge |
| C. Inside the Crew Change JSON | Bookings stored per crew member in `Service.data` | Doesn't fit entry on separate pages: two editors writing the same data |

The user picked **A**.

## Design

### Data

**Rooms and cars can be shared (user: crew "sometimes" share a room).** So a hotel stay is **one room** with
**one or more guests**, and its price is **per room per night**, entered once. A transfer is likewise **one car trip**
with one or more guests and one price. *(The car part is my call by the same logic: crew arriving together usually
share a car; a one-guest booking still works exactly as before.)* All guests of one booking belong to the booking's
vessel; up to 6 guests per booking *(my call)*.

`Guest` (shared by both kinds; ordered list per booking)
- `name` (required, ≤120, upper-cased like vessel names), `rank`, `nationality` (≤60), `group` — `on`, `off` or empty
  (typed guest), `flight` (≤20, optional)
- belongs to exactly one `HotelStay` or one `Transfer` (two nullable foreign keys with a check constraint, or two
  small tables `HotelGuest` / `TransferGuest` — left to the builder)

`HotelStay`
- `vessel` → `Vessel` (on vessel delete: delete its bookings — *my call*; the vessel delete confirmation already
  says "and all of its services"; extend it to "services, hotel stays and transfers")
- guests: 1–6
- `hotel` — text, ≤100 (chosen from Master data "Hotel"; any text accepted, like OPR today)
- `check_in` — date; `nights` — whole number 1–60 (*my call on the cap*); check-out = check-in + nights (computed)
- `price_per_night` — **per room** (optional, ≥ 0) + `currency` (EGP / USD)
- `created_at`

`Transfer`
- `vessel`, guests: 1–6 (each with their own `flight`)
- `from_place`, `to_place` — each one of `airport`, `hotel`, `port`; must differ
- `hotel` — text ≤100 from Master data; **required when either end is `hotel`**, empty otherwise. In the dialog it is
  pre-filled with the hotel of a stay on the same vessel that has the first guest, when there is one. Shown in the list as
  "Airport → Hotel (Hilton Alexandria)" and matched by search. *(my call: the driver must know which hotel.)*
- `at` — date and time (Cairo), required
- `price` (optional, ≥ 0) + `currency` (EGP / USD)
- `created_at`

**Exchange rate (both models):** an optional `exchange_rate` per booking, like services have. A USD price is
converted with that rate if given, otherwise with the **vessel's month rate** — the same rule `finance.py` uses for
services, so the calculations page treats all money alike. The dialog shows the rate field only when USD is chosen.
*(my call: consistency with services.)*

Indexes on `HotelStay.check_in` and `Transfer.at`.

**Guest copy:** when guests are picked from the crew list, their name, rank, nationality, group and flight are
copied into the booking. Later edits to the crew change do not change the booking (anti-goal 3).
A typo can be fixed by editing the booking.

**Hotel Master data:** new `Option` kind `hotel` (label "Hotel"), port-scoped exactly like the existing kinds, shown as
a fourth list on the Master data page with "used by N" counting bookings.

### API

`/api/hotels/` (GET list, POST create), `/api/hotels/<id>/` (PUT, DELETE), and the same for `/api/transfers/`.
All through `json_api`; writes need `require_edit` and a vessel inside the user's scope (port users can only pick
their own port's vessels; a vessel outside scope is a 404). Every change is audited.

List parameters, mirroring the vessel list: `from`, `to` (inclusive dates), `q`, `port`, `sort`, `dir`, `page`,
`page_size` (1–200). Same 400 errors for bad values.
- **Hotels** in range = stays that **overlap** the range: `check_in ≤ to` and `check_out > from` (a stay from
  14.11 for 3 nights shows when looking at 15.11). Default sort: check-in ascending.
- **Transport** in range = `at` on a date within the range. Default sort: date-time ascending.
- `q` matches any guest's name, the vessel name and the hotel (both pages) / flight (transport), case-insensitive,
  literal.
- One row per booking; the Guest column lists every guest (`AHMED TEST (2/E), ALI SAYED (OS)`); Rank / Nationality /
  Flight move into that cell for shared bookings.
- Response rows include `vessel` `{id, name, port}`; the price fields are **left out entirely** for read-only users.

Helper for the add form: `GET /api/vessels/<id>/crew/` → the guests of that vessel's Crew Change services:
`[{group: "on"|"off", name, rank, nationality, flight, arrival, departure}]`. Which flight leg: for an **on-signer the
last segment** (the one arriving in Egypt), for an **off-signer the first** (the one leaving Egypt). Stored times are
text without a year ("13 NOV 10:00"); the year is taken from the vessel date (the nearest date to it). Anything that
can't be read is left empty, and the user fills it in. *(my call; best effort.)*

### Pages

Sidebar order: Vessels · Bulk add · **Hotels** · **Transport** · Dashboard · Master data · Exchange rates.

Both pages: From / To (own range per page, defaulting to the current month — *my call*: the Vessels range is about
vessel dates, these are about stay / travel dates), port selector for admin and read-only, search (300 ms pause),
sortable headers, pager with rows per page (10 / 25 / 50 / 100, remembered per page). Rows are not clickable for
read-only users; for editors a row opens the edit dialog, with **Delete** in the dialog.

```
🏨 HOTELS   From [..] To [..]  [port ▾] [search…]                              [+ Add hotel stay]
 Check-in    Nights  Check-out   Hotel              Guest        Rank  Nationality  Vessel       Price/night
 15.11.2026  2       17.11.2026  Hilton Alexandria  AHMED TEST   2/E   Egyptian     MSC AURORA   USD 80.00

🚗 TRANSPORT  From [..] To [..]  [port ▾] [search…]                              [+ Add transfer]
 Date & time        From → To         Guest        Flight   Vessel       Price
 15.11.2026 14:30   Airport → Hotel   AHMED TEST   TK 689   MSC AURORA   EGP 900.00
```

(The price column is not shown to read-only users.)

**Add / edit dialog:**
1. **Vessel** — a search box that finds vessels by name in the user's scope (`/api/vessels/?q=`, any date) and shows
   name · date · port; the chosen vessel is fixed when editing.
2. **Guests** — a checklist of the vessel's crew (`↑ On` / `↓ Off` · name · rank) plus "+ Other guest" to type a
   name; each chosen guest appears as an editable line (name, rank, nationality, flight) with a remove button.
3. **Hotel stay:** hotel (Master data dropdown), check-in (date, pre-filled from an on-signer's flight arrival date
   when it can be read), nights; shows the check-out date. **Transfer:** from, to, date & time (pre-filled from the
   flight arrival for an on-signer leaving the airport, departure for an off-signer going to it, when readable),
   flight.
4. **Price** (optional) with EGP / USD.

Validation messages are shown in the dialog like the other forms; server rules are the source of truth.

## Testing

Backend (`sheet/tests_logistics.py`): create / edit / delete for both kinds; port user cannot see, create on, edit or
delete another port's bookings (404); read-only gets lists without price fields and 403 on writes; overlap rule at the
edges (stay ending the day `from` starts is out; starting on `to` is in); transfer date range inclusive; validation
(nights 1–60, from ≠ to, places in the list, bad dates, negative price, unknown currency → EGP like services);
guest copy survives editing / deleting the crew change; a shared room with 2 guests counts one price;
1–6 guests enforced; vessel delete removes its bookings; crew helper returns
on / off signers; hotel Master data kind. Smoke test: add a shared stay (two picked guests) and a transfer via the dialog,
see them listed, read-only sees no price column and no Add button.

## Left to the builder

Module layout (e.g. `sheet/logistics.py` for list logic, shared helpers with `listing.py` where it reduces
duplication), exact markup and CSS within the existing styles, how flight times are parsed for pre-filling (best
effort; empty if unreadable), migration naming.
