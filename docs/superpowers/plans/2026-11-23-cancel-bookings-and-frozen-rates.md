# Cancelled bookings and frozen rates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Cancelling a crew change cancels its bookings (unless unticked); closing a line needs a rate and keeps it.

**Architecture:** `cancelled` on HotelStay / Transfer and kept rate / price on VesselDisposal (migration 0020);
`crewbookings.saved_bookings` / `cancel_bookings`; `accounting.set_closed` checks and writes the rate.

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test. **Spec:**
`docs/superpowers/specs/2026-11-23-cancel-bookings-and-frozen-rates-design.md`

## Global Constraints

Same as `2026-11-23-service-status.md` (input refused never fixed, dom.js only, tokens only, scoped, one transaction,
audited, LF endings, `npm run check` green, docs updated).

## Review Focus

1. `cancel_bookings` naming another vessel's / another crew change's booking, a closed one, or sent while not
   Cancelled: 400, nothing changed. Test: `test_cancel_bookings_refused`.
2. Closing a USD line twice / reopening: the written rate stays, version rises only when the rate was written.
   Test: `test_close_writes_month_rate_once`.
3. Garbage & sludge after closing, month price changed: figures unchanged. Test: `test_disposal_keeps_price_and_rate`.
4. A booking PUT from an old page without `cancelled`: keeps the stored value. Test: `test_put_without_cancelled_keeps_it`.
5. A cancelled booking with a fee: on Calculations with status cancelled. Test: `test_cancelled_booking_line_status`.

### Task 1: Cancelled bookings
Files: `models.py`, `migrations/0020_cancel_and_frozen.py`, `validators.py` (cleaners), `logistics.py`
(`booking_to_dict`, `save_booking`), `crewbookings.py` (`_INCOMPLETE`, `incomplete`), `calculations.py`; test
`tests_cancel_bookings.py`: `test_booking_cancelled_saved_and_returned`, `test_put_without_cancelled_keeps_it`,
`test_cancelled_booking_raises_no_alert`, `test_cancelled_booking_line_status`. Commit `feat(bookings): cancelled`.

### Task 2: Cancelling a crew change cancels its bookings
Files: `crewbookings.py` (`saved_bookings(service)`, `cancel_bookings(service, refs)`), `validators.py`
(`clean_booking_refs`), `views.py` (`service_bookings`, service PUT), `urls.py`; tests
`test_saved_bookings_listed`, `test_cancel_bookings_with_crew_change`, `test_cancel_bookings_refused`.
Commit `feat(services): cancelling a crew change cancels its bookings`.

### Task 3: Closing needs a rate and keeps it
Files: `accounting.py`, `disposal.py` (own rate / price); tests in `tests_accounting.py`:
`test_close_needs_a_rate`, `test_close_writes_month_rate_once`, `test_close_keeps_booking_rate`,
`test_disposal_keeps_price_and_rate`, `test_disposal_close_needs_price`. Commit `feat(accounting): closing keeps the rate`.

### Task 4: Screens
`js/modals/booking.js` (Cancelled tick, money 0), `js/pages/bookings.js` (label), `js/modals/service.js` +
`actions.js` (booking list on Cancelled, `cancel_bookings`), `tools/ui_smoke_test.js`. `npm run check` + smoke for
alex / admin / viewer / suez. Commit `feat(ui): cancelled bookings`.

### Task 5: Docs and review
STATUS, CLAUDE, README / SECURITY counts, DEPLOYMENT (migration 0020); fresh review; commit `docs: …`.
