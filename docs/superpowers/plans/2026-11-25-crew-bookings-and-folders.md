# Crew hotel / transport, LOG airlines, sidebar folders — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LOG "TO:" lists every airline; each crew member gets Hotel / Transport buttons whose typed details become
the Hotels / Transport drafts (transport only when pressed); the sidebar is grouped into three folders.

**Architecture:** Crew member data in `Service.data` grows `hotel` / `needsTransport` / `transport`; `crewbookings.sync`
turns them into drafts as today. The dialog learns which members' bookings were saved on their page from a new read
route. Folders are template groups toggled by a `data-act`.

**Tech Stack:** Django 5.2, vanilla ES modules (`dom.js` only), no new libraries.

**Spec:** `docs/superpowers/specs/2026-11-25-crew-bookings-and-folders-design.md`

## Global Constraints

- Input refused, never silently fixed (`validators.py`); Master-data names checked with `validators.listed` for the
  vessel's port, the saved value stays allowed.
- Screens only through `dom.js` `h()`; no `innerHTML`, no inline `style=`; show / hide with `hidden`; icons from the
  sprite via `icon(name)`; colours only as tokens in `app.css`.
- LF line endings. `npm run check` green before merge. Update STATUS / CLAUDE / README / SECURITY.
- Hotel / transport details are not money: `moneyaccess.py` and `moneyKeys.js` unchanged.

## Review Focus

- A member with Transport pressed whose booking was **saved** on the Transport page: re-saving the crew change must
  not change or duplicate it (sync test in Task 2).
- Un-pressing Hotel / Transport deletes only the draft, never a saved or accounting-closed booking (Task 2 test).
- A hotel name typed earlier that left Master data stays allowed on re-save (Task 2 validator test).
- Check-out empty but check-in typed → 1 night from the typed check-in (Task 2 test).
- A person without `money.edit` saving a crew change with hotel / transport details is not refused (Task 2 test).

---

### Task 1: LOG "TO:" lists every airline

**Files:** Modify `sheet/views.py` (`service_log`); Test `sheet/tests_logpdf.py`.

- [ ] Test `test_to_lists_every_airline_once`: on-signer with segments airlines `EGYPTAIR`, `TURKISH AIRLINES`,
  `EGYPTAIR   TUE 17 NOVEMBER 2026`, `""` → the fields passed to `logpdf.build` have
  `to == "EGYPTAIR / TURKISH AIRLINES"` (patch `logpdf.build` as the existing tests do, or read the PDF text).
- [ ] Run, see it fail. Implement `_airlines(segments) -> str` in `views.py` (clean each with `AIRLINE_DATE_TAIL`,
  drop empties and repeats, keep order, join `" / "`). Run `python manage.py test sheet.tests_logpdf`: pass. Commit.

### Task 2: Crew hotel / transport data and sync (backend)

**Files:** Modify `sheet/validators.py` (`_clean_crew_change`, new `check_crew_lists`), `sheet/views.py`
(`_read_service`, new `service_crew_bookings`), `sheet/urls.py`, `sheet/crewbookings.py`
(`_wanted`, `_when`, `_create`, `_refresh`, new `saved_by_member`), `sheet/management/commands/seed_demo.py`;
Create `sheet/migrations/0027_crew_transport.py`; Test `sheet/tests_crew.py` (or a new `tests_crew_bookings.py`).

**Interfaces — Produces:**
- Member keys: `needsHotel: bool`, `hotel: {name, checkIn, checkOut}` (strings, ISO date or ""), `needsTransport:
  bool`, `transport: {from, fromName, to, toName, at}` (`from`/`to` in `PLACE_KEYS` or "", `at` `YYYY-MM-DDTHH:MM`
  or ""). Always present after cleaning (empty strings), on both groups.
- `validators.check_crew_lists(data, port, existing_data=None)`: each non-empty `hotel.name` (kind `hotel`) and
  transport `fromName` / `toName` (kind by place: airport→`airport`, hotel→`hotel`, port→`port`) via `listed`, the same
  member's (by uid) saved value allowed.
- `GET /api/services/<id>/crew-bookings/` → `{"saved": {uid: {"hotel": bool, "transport": bool}}}`: per crew uid,
  whether a non-draft booking holds a guest with that `crew_uid`. Scoped, Crew Change only, needs `services.edit`
  (the dialog's own permission).

Steps:
- [ ] Tests for cleaning: bad `checkIn` → 400 "Enter a valid check-in date."; check-out ≤ check-in → 400
  "Check-out must be after check-in."; more than `MAX_NIGHTS` → 400; `from` not a place → 400 "Choose where from and
  where to."; `from == to` (both set) → 400 "From and To must be different."; bad `at` → 400 "Enter the date and
  time."; names not in Master data → 400 (listed's message); a saved name off the list stays allowed.
- [ ] Tests for sync: no `needsTransport` → no transfer; pressed with nothing typed → airport→port at landing (on) /
  port→airport (off) as today; typed values → transfer `from_place`/`to_place`/`airport`/`hotel`/`port_name`/`at`
  as typed (names go in the field of their place); hotel typed `checkIn 2026-11-20`, `checkOut 2026-11-22` →
  `check_in` 20th, `nights` 2, `hotel` name; only `checkIn` → 1 night; editing the typed values refreshes the draft;
  un-pressing deletes the draft; a saved (`draft=False`) or `acct_closed` booking is never changed; a user without
  `money.edit` can save these keys.
- [ ] Test the route: saved transfer for uid A → `{"A": {"hotel": false, "transport": true}}`; another port's service → 404.
- [ ] Test migration 0027 (forward function called directly): a member with a linked transfer gets
  `needsTransport: true`; one without stays false.
- [ ] Implement. `_when` takes the typed values first; `_refresh` updates every typed field (not only the date) and
  saves only on change. Migration 0027: `RunPython` over Crew Change services, members whose uid is a `Guest.crew_uid`
  on a transfer of that vessel; reverse no-op. `seed_demo`: MSC AURORA on-signers get `needsTransport: True`.
- [ ] Run `python manage.py test sheet`: all pass. `makemigrations --check --dry-run` clean. Commit.

### Task 3: Crew card buttons and fields (front end)

**Files:** Modify `sheet/static/sheet/js/modals/service.js` (crew card, `onModalInput`, open of a saved Crew
Change), `sheet/static/sheet/js/actions.js` (`crew-hotel`, `crew-transport`), `sheet/static/sheet/app.css`,
`tools/ui_smoke_test.js`; pure helper `crewBookingDefaults(member, group, vesselDate)` in a new
`sheet/static/sheet/js/crewBookings.js`, tested in `tools/parsing_test.js`.

**Interfaces — Consumes:** Task 2 member keys and `/crew-bookings/` route.

- [ ] `parsing_test.js`: on-signer whose last leg lands `2026-11-20 14:30` → hotel `{checkIn: '2026-11-20',
  checkOut: '2026-11-21'}`, transport `{from: 'airport', to: 'port', at: '2026-11-20T14:30'}`; off-signer first leg
  takes off `2026-11-25 09:00` → `{from: 'port', to: 'airport', at: '2026-11-25T09:00'}`; no flight → vessel date,
  `T00:00`. (Use the same leg / time fields `logistics.crew_leg` / `crew_moment` read.)
- [ ] Card: replace "Needs hotel" with two `btn ghost small` buttons `Hotel` / `Transport` (`aria-pressed`, class
  `on` when pressed; `data-act` `crew-hotel` / `crew-transport`). Pressed → a `.crew-booking` block: Hotel select
  (`optionChoicesEl('hotel', current, vessel.port)`), Check-in / Check-out date inputs (`data-crew` `hotel.name`,
  `hotel.checkIn`, `hotel.checkOut`); Transport: From place select + its name select (list follows the place),
  To the same, At `datetime-local` (`data-crew` `transport.*`). First press fills empty boxes from
  `crewBookingDefaults`. If `/crew-bookings/` says saved → the block is one line "Saved on the Hotels page" /
  "Saved on the Transport page", button disabled.
- [ ] Smoke test (alex): on a crew member press Hotel (pick the demo hotel) and Transport, save, open Hotels and
  Transport pages and `waitFor` the guest's row; un-press Transport, save, the transfer row is gone.
- [ ] Run `cd tools && npm run test:parsing`, the smoke test for alex / marine. Commit.

### Task 4: Sidebar folders

**Files:** Modify `sheet/templates/sheet/index.html`, `sheet/static/sheet/app.css`, `sheet/static/sheet/js/main.js`
(or a new `js/navGroups.js`), `sheet/static/sheet/js/router.js` (open the current page's folder),
`tools/ui_smoke_test.js`; Test `sheet/tests_look.py` or `tests_permissions` (template).

- [ ] Template test: admin page has three `.nav-group` with heads Marine / Reports / Master data, items in the spec's
  order; a User with only Vessels sees only the Marine group (other groups not rendered).
- [ ] Template: `<div class="nav-group" data-group="marine">` with a `<button class="nav-group-head"
  data-act="toggle-nav-group" aria-expanded="true">` (label + `i-chevron-down`) and a `.nav-group-items` div; a group
  renders only if one of its items does (Django `{% if %}` on the same conditions).
- [ ] JS: toggle sets `hidden` on items + `aria-expanded`; state in localStorage `sheet.navGroups` (try/catch);
  `showPage` opens the group holding the active item.
- [ ] Smoke test: admin clicks the Reports head, its items hide; navigating to `#dashboard` opens it again.
- [ ] Run `python manage.py test sheet`, smoke admin / viewer. Commit.

### Task 5: Checks and docs

- [ ] `cd tools && npm run check` green; smoke runs alex, admin, viewer, suez, marine on a fresh database.
- [ ] Update `docs/STATUS.md`, `CLAUDE.md` (Automatic crew bookings, LOG letter, Front end nav), README / SECURITY
  test counts, `DEPLOYMENT.md` only if a migration note is needed (0027). Commit.
