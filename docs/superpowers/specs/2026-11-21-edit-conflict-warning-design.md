# Edit-conflict warning — design

Date: 2026-11-21. Status: approach A chosen by the user; this document awaits the user's approval.

## Why

Today two people can open the same record, both change it, and the second **Save silently overwrites** the first
(`docs/DEPLOYMENT.md` §11 says so). The app is being sold to a company where several ports and the office work at the
same time, and security / data safety come first. The user wants the app to stop and say so instead of overwriting.

## What the person sees (user's choice: option 2)

When someone saves a record that another person (or the same person in another window) saved after it was opened,
**nothing is saved** and the dialog shows, above its buttons:

```
 ┌────────────────────────────────────────────────────────────────────────────┐
 │ Mona changed this vessel at 10:42 while you had it open.                   │
 │ They changed: Berthing time, Sailing agent.  Nothing of yours was saved.   │
 │                                   [ Show their version ]  [ Save mine anyway ] │
 └────────────────────────────────────────────────────────────────────────────┘
```

- **Show their version** reloads the dialog with the saved record (what was typed is dropped).
- **Save mine anyway** saves what is in the dialog over theirs. The History keeps both saves.
- If several saves happened meanwhile: the **latest** person and time, and the fields changed by **all** of them.
- If it was the same person (another window / tab): "You changed this … in another window".
- What was typed stays in the dialog while the warning shows, so nothing is lost by reading it.
- **Everyone who gets the warning sees the name, time and fields** (user's decision, 2026-11-21), port users included
  — even though the History page itself stays admin-only. They only ever get it for a record they may edit anyway,
  and the name tells them whom to call before choosing "Save mine anyway". Nothing else from the History is shown.

## Goals

- No silent overwrite of a **person's** save on: **Vessel** (vessel form), **Service** (service form, Crew Change
  included), **HotelStay** and **Transfer** (booking dialog, guests included), **PortClosure** (closure dialog).
- The warning names who, when, and which fields.
- The app's own automatic updates never trigger a warning.

## Non-goals

- Garbage & Sludge boxes (save on leaving each box, one number at a time), exchange rates and disposal prices
  (admin-only, one value per month), Master data (add / delete / move only), user accounts (Django admin pages).
- **Deletes** are not checked: deleting already asks for confirmation; a save after someone else's delete keeps
  answering "not found" as today.
- No live "someone else is editing this" presence indicator, no field-by-field merge (option 3, not chosen).

## Anti-goals

- A warning when nobody else changed anything (false alarms would teach people to click "Save mine anyway" blindly).
- Losing what the person typed.
- Any weakening of scoping, roles, validation or the append-only History.

## Approach (chosen: A — a change counter)

| | Approach | Trade-off | Chosen |
|---|---|---|---|
| A | A `version` number on each of the five models; +1 on every person save; the dialog sends the number it opened with | One migration; exact; independent of timing | **Yes** |
| B | A "last changed at" time instead | Same migration; two saves in one instant or a clock change could slip through | No |
| C | No new field: compare against the newest History entry | No migration, but the History also holds automatic updates — fiddly to tell apart, risk of false or missed warnings | No |

## How it works

### Server

- Migration: `version = PositiveIntegerField(default=1)` on `Vessel`, `Service`, `HotelStay`, `Transfer`,
  `PortClosure`. Existing rows start at 1.
- Every **read** the dialogs use returns `version` (`vessel_to_dict` and its services, `booking_to_dict`,
  `closure_to_dict`).
- Every **update** of those five (vessel `PUT`/`PATCH`, service `PUT`/`PATCH`, booking `PUT`, closure `PUT`) must
  carry `version` (a whole number). Inside the request's transaction the row is locked (`select_for_update`), then:
  - `version` missing or not a whole number → **400** "This page is out of date. Reload it and try again." (an old
    browser tab after an update can then never overwrite silently);
  - `version` ≠ stored → **409** with `{"error": "conflict", "conflict": {"who", "same_person", "at", "fields",
    "version"}}` and **nothing saved**;
  - equal → save as today, with `version + 1`, and return the new `version`.
- **A save that changes nothing does not raise `version`** (designer's call, from the anti-goal "no false alarms"):
  the update compares the cleaned new values with the stored ones — for a booking its guest list too (the guests are
  rebuilt on every save, so compare the list, not their History rows) — and only a real change counts. Such a save
  still answers 200 with the same `version`.
- **The Django admin pages** can also edit these five records (Vessel with its services inline, HotelStay, Transfer
  with guests, PortClosure). An admin-page save that changes something **also raises `version`** (`save_model` /
  `save_formset` hooks), so an open dialog warns about it too; `version` is read-only there (designer's call).
- "Save mine anyway" is simply the same save sent again with the `version` from the 409 (so a third save in between
  warns again).
- **Automatic updates never change `version`**: `crewbookings.sync` (draft bookings), the vessel-date-follows-sailing
  rule and any other system write leave it alone. Only the five update views and the admin-page saves increment it.
  Creating starts at 1.
- **Who / when / which fields** come from the History: the `ChangeRecord`s of that object whose `changes` contain
  `version` with a new value greater than the version the browser sent. `who` = the latest one's `username` (and
  `same_person` when it is the requesting user), `at` = its time (Cairo, `HH:MM`, with the date when not today),
  `fields` = the union of the changed field names of all of them, as people read them (the vessel form's labels;
  for a Service its type / agent plus the top-level keys of `data` that differ, e.g. "On-signers"; for a booking,
  "Guests" when only its guests changed). Never `version` itself.
- The History page does not show the `version` change (it is still stored in `ChangeRecord.changes`).

### Browser

- Each of the four dialogs (vessel form, service form, booking, closure) keeps the `version` it was opened with and
  sends it with every save; after a successful save it keeps the returned `version` (so "Save & add another" / a
  second save from the same dialog works).
- On a 409 the dialog shows the warning panel (built with `dom.js`, no new styling rules beyond tokens) with the two
  buttons as `data-act` actions; the status line says "Not saved".
- On the 400 "out of date" message: shown like any other error.

## Constraints

- Project rules (CLAUDE.md): JSON API through `json_api`, scoped queries, one transaction per write, validators
  refuse rather than fix, `dom.js` only, no inline style, LF line endings, docs kept up to date (STATUS, CLAUDE,
  README / SECURITY test counts, DEPLOYMENT §11 "two people edit").
- Works the same on PostgreSQL (row lock) and SQLite (development; the whole database is locked during a write).

## Left to the builder

- Exact label wording for each field (reuse the form labels), the warning panel's markup and placement, the error
  class for 409 (`errors.ApiError` subclass with `extra`), test names, smoke-test checks (two browser sessions are
  not available in jsdom: simulate the other save with a direct API call between opening and saving).
