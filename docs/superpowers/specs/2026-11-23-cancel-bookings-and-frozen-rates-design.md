# Cancelled bookings and frozen rates — short design

Date: 2026-11-23. Branch: `feature/service-status` (same branch, before its merge). Approved by the user ("Yes,
build both") after the proposal in the conversation.

## Why

1. A crew change that is cancelled should cancel its hotel stays and transfers too, unless someone says otherwise
   (user: "if a crew is cancelled then we should cancel all hotel and transportation unless said otherwise").
2. A line accounting has closed must keep its numbers: "accounting cannot close it unless there is a rate either
   global or written manually and yes keep the rate till someone change it as the change might be in the amount so
   there is no changing the exchange rate".

## Approaches

- Bookings: **delete** them on cancel (loses the record when a hotel bills a late cancellation), or **a Cancelled
  state on the booking** like the service status (chosen: kept, money 0 until a fee is typed, no alert).
- Frozen rate: a separate "frozen rate" used only while Closed, or **write the rate onto the line as if typed by
  hand** (chosen: it then stays after reopening and only a person changes it, the user's wording; no new money rules).

## Design

**Bookings (HotelStay, Transfer):** new `cancelled` (bool, migration 0020). Booking dialog: a Cancelled tick;
ticking it sets the money to 0 (a fee can still be typed). A cancelled booking: "Cancelled" label on Hotels /
Transport, no missing-details alert, its Calculations line (only when it has money) has status `cancelled` (so the
Status filter treats it like a cancelled service). A PUT without `cancelled` keeps the stored value.

**Cancelling a crew change:** choosing Cancelled on a saved Crew Change lists its saved (non-draft) bookings — those
with a guest copied from one of its crew (`Guest.crew_uid`) — each ticked "cancel this too"; closed ones are shown
but can't be ticked. `GET /api/services/<id>/bookings/` gives the list. The service PUT may send
`cancel_bookings: [{kind: hotel|transfer, id}]` (only when the saved status is Cancelled, only that crew change's
bookings, none closed): each gets `cancelled`, money 0, version +1, history, in the same transaction. Drafts are
deleted as before. Un-cancelling the crew change leaves bookings as they are (untick in the booking dialog).

**Closing needs a rate and keeps it:** closing (`/api/accounting/`) is refused when the line uses USD with no rate
anywhere ("Add this month's exchange rate (or write one on the line) first.") or garbage & sludge has no price
("Add this month's Garbage & Sludge price first."). When a line used the month rate, closing writes it onto the
line: the service's `exchangeRate`, the booking's `exchange_rate` (version +1, as a real change), or the vessel's
garbage & sludge (new `VesselDisposal.exchange_rate` and `frozen_price`, the month's price copied). Reopening keeps
them. Garbage & sludge uses its own rate / price when set, else the month's.

## Left to the builder

Labels and layout follow the existing status label and closed note. Garbage & sludge has no screen to change its
kept rate / price (admin pages only).
