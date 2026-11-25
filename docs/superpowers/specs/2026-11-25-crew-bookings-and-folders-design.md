# Crew hotel / transport on the crew card, LOG airlines, sidebar folders — design

Date: 2026-11-25. Branch `feature/crew-bookings-folders`.

## Why

The user works crew changes from the crew card. Today "Needs hotel" makes an empty draft hotel stay (no hotel, 1 night)
and every member silently gets a draft transfer, so the Hotels / Transport pages fill with empty drafts that must be
completed elsewhere. The user's own HTML prototype (`ARKAS_EGYPT_AGENCY_V19_FINAL_INTEGRATED_TEST.html`) types the
hotel and check-in / check-out right under the person. The LOG letter's "TO:" names only the first leg's airline,
which is wrong for multi-airline journeys. The sidebar has 15 flat items; the user wants three folders.

## 1. LOG letter "TO:"

`views.service_log`: "to" = the airline of **every** flight leg of the on-signer, each cleaned with
`AIRLINE_DATE_TAIL`, empties dropped, **repeats dropped keeping the first order** (my call), joined with `" / "`.
`EGYPTAIR, TURKISH, EGYPTAIR` → `EGYPTAIR / TURKISH`. No legs → empty (as today).

## 2. Hotel and Transport buttons on the crew card (approach A, user's pick)

Approaches considered: **A** fields on the crew card, turned into the existing drafts by `crewbookings.sync`
(picked: keeps one dialog, reuses drafts, pages, alerts, Calculations unchanged); **B** buttons open the full booking
dialog (rejected: the app has one dialog, the crew change would have to be saved and closed first).

### What the user sees

Each crew card (on- and off-signers) gets two toggle buttons, **Hotel** and **Transport**, replacing the "Needs
hotel" tick. Pressed → its fields show under them (`hidden` attribute, no inline style):

- Hotel: Hotel (select from Master data Hotel list for the vessel's port + All ports, `optionChoices`),
  Check-in (date), Check-out (date).
- Transport: From (Airport / Hotel / Port) + which one (select from that Master data list), To (same), At (date + time).

Fields start empty; an empty field means "the automatic value" (shown nowhere, used by sync): check-in = today's rule
(on-signer landing date, else vessel date), check-out = check-in + 1 night; transport from/to = airport → port (on) /
port → airport (off), at = today's rule (landing / take-off, else vessel date 00:00); names empty. (My call: the form
pre-fills these defaults into the boxes when the button is first pressed, so the user sees and can change them; an
emptied box falls back to the automatic value.)

No money on the crew card: cost / revenue stay on the Hotels / Transport pages (draft until then; the missing-details
alert keeps asking). A member whose booking was **saved** on its page (`draft=False`) shows, instead of the fields,
one line "Saved on the Hotels page" / "Saved on the Transport page" — the crew card never changes a saved booking
(today's rule). The dialog learns this from a new per-member flag in the service JSON (builder's call how; e.g.
`saved: {hotel: bool, transport: bool}` added by the serializer from `saved_bookings`).

### Data (in `Service.data`, crew member)

- `needsHotel` (kept) — Hotel pressed.
- `hotel`: `{name, checkIn, checkOut}` — strings; dates ISO `YYYY-MM-DD`; all optional.
- `needsTransport` (new) — Transport pressed.
- `transport`: `{from, fromName, to, toName, at}` — `from`/`to` in `PLACES` (`airport`/`hotel`/`port`) or empty;
  `at` ISO local datetime `YYYY-MM-DDTHH:MM` (Cairo) or empty.

`validators._clean_crew_change` cleans them (whitelisted keys, refused, never fixed): bad dates / times → 400;
check-out not after check-in → 400; nights at most what HotelStay allows (builder: pick the existing booking limit);
from == to → 400 (if the booking validator already refuses it). Names must be in Master data for the vessel's port
(`listed`, kind by place); the value already saved stays allowed. These are not money: `moneyaccess` and
`moneyKeys.js` unchanged.

### Sync (`crewbookings`)

- `_wanted(kind, member)`: Transfer → `needsTransport`; HotelStay → `needsHotel`. Untick → the draft is deleted
  (today's rule for hotel, now also transport).
- `_create` / `_refresh` use the typed values, else the automatic ones: hotel `hotel` = name, `check_in`, `nights` =
  check-out − check-in; transfer `from_place`, `to_place`, `airport` / `hotel` / `port_name` (the name goes in the field
  matching the place; both ends' names), `at`. `_refresh` keeps updating only one-guest, not-closed drafts.
- The booking stays `draft=True` (incomplete: no money yet).

### Existing data (data migration 0027)

For every Crew Change member (on and off) that has a linked transfer (any guest with its `crew_uid`, draft or saved),
set `needsTransport = true`, so turning transport into opt-in removes nothing. Members without one stay false. Hotel
data unchanged (`needsHotel` keeps meaning what it meant). History: a migration writes no ChangeRecord (as 0019 did).
`seed_demo`: MSC AURORA's on-signers get Transport pressed (smoke test relies on their drafts).

## 3. Sidebar folders

`index.html` nav: three collapsible groups, items in this order:

- **Marine**: Vessels, Services, Port closures, Ships
- **Reports**: Dashboard, Garbage & Sludge, Hotels, Transport, Calculations
- **Master data**: Master data, Customers, Exchange rates, Ports, Accounts, History

Each item keeps its own `{% if %}` (pages / admin / superuser); a folder with no visible item is not rendered. A
folder head is a `<button data-act="toggle-nav-group">` with a chevron icon (sprite); open/closed per folder saved in
localStorage (try/catch), default open; the folder holding the current page is always opened on navigation. Collapsed
sidebar (if the app has one) and mobile: builder follows the existing nav styles. Colours via tokens only.

## Non-goals

Money on the crew card; more than one hotel / transfer per member; changing the Hotels / Transport pages or dialogs;
any change to permissions (the buttons need `services.edit` like the rest of the dialog).

## Tests

Backend: LOG "TO" (several legs, repeats, date tail); validators for the new keys; sync: transport only when pressed,
typed values used, untick deletes the draft, saved bookings untouched; migration 0027 sets the flag. Front end:
`parsing_test.js` for any pure helper (e.g. defaults); `tests_look` for the new icon; smoke test: press Hotel and
Transport on a crew member, save, see the rows on the Hotels / Transport pages; folders render and toggle.
Docs: STATUS, CLAUDE.md (Automatic crew bookings, LOG letter, Front end nav), README / SECURITY test counts.
