# Crew bookings, sailing date, early arrival, LOG letter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatic draft hotel / transport bookings per crew member, the vessel date following the sailing time,
an Early arrival alert with a Broken visa charge, and a hand-written LOG PDF per on-signer.

**Architecture:** Crew members get a stable `uid` in `Service.data`; a new `crewbookings.sync(service)` keeps draft
bookings (linked by `Guest.crew_uid`) in step after every Crew Change write. Alerts extend `listing.py`. The PDF is
written by `logpdf.py` with the standard library only (JPEGs embedded raw, built-in fonts).

**Tech Stack:** Django 5.2, vanilla ES modules (`dom.js`), no new packages.

**Spec:** `docs/superpowers/specs/2026-11-19-crew-bookings-early-arrival-log-design.md`

## Global Constraints

- No new dependency (Python or npm); `requirements.in` / `requirements.txt` unchanged.
- No `innerHTML` / inline style / `eval`; screens only through `dom.js`; icons only from the sprite.
- Every vessel / service / booking read through `access.scoped_vessels`; writes through `require_edit`.
- Validators refuse, never silently fix (except pasted crew text, which is trimmed as today).
- LF line endings. Migration `0014_crew_bookings`; hand-written data step.
- Letterhead images never in git, never under `static/`; folder from `DJANGO_LETTERHEAD_DIR`
  (`logo.jpg`, `stamp.jpg`, `footer.jpg`); missing → letter without that image.
- The PDF never contains `{{`, `}}` or placeholder labels.
- `cd tools && npm run check` green at the end; smoke test alex / admin / viewer / suez.

## Review Focus

1. Saving a booking in the Hotels / Transport dialog replaces its guests — the `crew_uid` must survive, or the next
   crew-change save creates a duplicate draft. Test in Task 3.
2. Two crew members with the same name, or a crew member renamed — linking is by `uid`, never by name. Test in Task 3.
3. Flight text that can't be parsed (empty segments, "TBA") — drafts fall back to the vessel date, early arrival is
   simply not raised. Tests in Tasks 3 and 4.
4. Crew text containing `(`, `)`, `\`, `%PDF`, `{{x}}`, non-Latin letters or very long lines — the PDF stays valid and
   prints it literally (WinAnsi fallback). Tests in Task 5.
5. A sailing time entered for a vessel shown in the current month that sails next month — the vessel moves and the
   save still succeeds (outside-range notice shows). Test in Task 2.

---

### Task 1: Crew member data and broken-visa money

**Files:**
- Modify: `sheet/validators.py` (`_crew_member`, `_clean_crew_change`)
- Modify: `sheet/finance.py` (`_all_lines` Crew Change branch)
- Modify: `sheet/static/sheet/js/calc.js`
- Test: `sheet/tests_crew.py` (new), `tools/parsing_test.js` only if `calc.js` is already covered there (else no JS test)

**Interfaces:**
- Produces: crew member dict keys `uid` (12 lowercase hex), `needsHotel` (bool), on-signers only
  `brokenVisa` = `{cost, costCurrency, revenue, revenueCurrency}` (amounts `None` when empty).
- Produces: `validators.UID_RE = re.compile(r"^[0-9a-f]{12}$")`.

- [ ] **Step 1: Failing tests** in `CrewDataTests(SimpleTestCase)`:
  - `test_new_member_gets_uid`: `clean_service_data("Crew Change", {"onSigners": [{"name": "A"}]})` → `uid` matches `UID_RE`.
  - `test_valid_uid_kept_duplicate_replaced`: two members sent with uid `"abcdef123456"` → first keeps it, second gets a new one; `"XYZ"` → replaced.
  - `test_needs_hotel_is_bool`: `"needsHotel": "yes"` → `True`; missing → `False`.
  - `test_broken_visa_on_signers_only`: on-signer `brokenVisa {"cost": "50", "costCurrency": "USD"}` kept as cost 50.0 USD; off-signer's `brokenVisa` dropped.
  - `test_negative_broken_visa_refused`: cost `-1` → `BadRequest`.
  - `test_broken_visa_adds_money_lines`: data with service cost 100 EGP and one on-signer "J SMITH" broken visa cost 10 USD revenue 20 USD, month rate 50 → `finance.compute` cost 600, revenue 1000; `service_lines` labels include `"Broken visa · J SMITH"`.
  - `test_zero_broken_visa_has_no_line`: cost 0 → no extra line in `service_lines`.
- [ ] **Step 2:** `venv/Scripts/python.exe manage.py test sheet.tests_crew` → FAIL.
- [ ] **Step 3:** Implement. Uniqueness of uids is per Crew Change payload (both groups together). `brokenVisa` amounts
  via `_amount` / `_currency`. In `_all_lines`, Crew Change appends one `line(f"Broken visa · {name}", …)` per
  on-signer (same `rate`, `own_rate`); `service_lines` already drops empty lines. `calc.js`: Crew Change adds each
  on-signer's broken visa through `toEgp`.
- [ ] **Step 4:** Tests pass; `manage.py test sheet` still green.
- [ ] **Step 5:** Commit `feat(crew): uid, needs hotel and broken visa on crew members`.

### Task 2: Migration and vessel date = sailing date

**Files:**
- Modify: `sheet/models.py` (`Guest.crew_uid = CharField(max_length=12, blank=True, db_index=True)`,
  `HotelStay.draft`, `Transfer.draft` = `BooleanField(default=False)`)
- Create: `sheet/migrations/0014_crew_bookings.py` (fields + `RunPython` setting `date` to the Cairo date of
  `sailing_at` for every vessel that has one; reverse = noop)
- Modify: `sheet/validators.py` (`clean_vessel`)
- Test: `sheet/tests_crew.py`

**Interfaces:**
- Produces: models fields above; `clean_vessel` returns `date = timezone.localdate(sailing_at)` when `sailing_at` set.

- [ ] **Step 1: Failing tests** `SailingDateTests(ApiTestCase)`:
  - `test_sailing_time_sets_vessel_date`: PUT ALEX SHIP (date 13.11) with arrival `2026-11-13T08:00`, sailing `2026-11-15T23:30` (all five times in order) → vessel `date` == 2026-11-15.
  - `test_sailing_after_midnight_cairo`: sailing `2026-11-30T23:30` local → date 30.11 (not UTC-shifted), and a sailing `2026-12-01T00:10` → 01.12 (moves month, save returns 200).
  - `test_without_sailing_posted_date_kept`.
  - `test_migration_step` not needed as a test; check by hand with `migrate` on a scratch DB (Step 4).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations sheet -n crew_bookings`, then add the `RunPython` step by hand.
- [ ] **Step 4:** Tests pass; `makemigrations --check --dry-run` clean; `migrate` on a scratch DB works.
- [ ] **Step 5:** Commit `feat(vessels): the vessel date follows the sailing time`.

### Task 3: Automatic draft bookings

**Files:**
- Create: `sheet/crewbookings.py`
- Modify: `sheet/views.py` (`service_create`, `service_detail`: call `crewbookings.sync(service)` after save;
  before DELETE call `crewbookings.drop_drafts(service)`)
- Modify: `sheet/logistics.py` (`_crew_entry` adds `"uid"`; `_guest_dict` adds `"crew_uid"`; `booking_to_dict` adds
  `"draft"`; `save_booking` sets `draft=False`, keeps `crew_uid` from the cleaned guest)
- Modify: `sheet/validators.py` (`clean_guests` keeps `crew_uid` when it matches `UID_RE`, else `""`)
- Test: `sheet/tests_crew.py`

**Interfaces:**
- Consumes: Task 1 member keys, Task 2 fields, `logistics._crew_entry(member, group, near)` (returns `arrival` /
  `departure` local ISO or `""`).
- Produces: `crewbookings.sync(service) -> None`, `crewbookings.drop_drafts(service) -> None`,
  `crewbookings.incomplete(booking) -> bool` (draft, or cost is None, or revenue is None).

- [ ] **Step 1: Failing tests** `DraftBookingTests(ApiTestCase)` (POST / PUT through the API as `alex`):
  - `test_every_member_gets_a_draft_transfer`: crew change with 1 on-signer (landing "15 NOV 10:00") and 1 off-signer → 2 transfers, `draft=True`; on: `from_place="airport"`, `to_place="port"`, `at` 15.11 10:00 Cairo; off: port → airport.
  - `test_needs_hotel_creates_draft_stay`: on-signer with `needsHotel` → one HotelStay `draft=True`, hotel `""`, nights 1, check-in 15.11, one guest with that `crew_uid`; off-signer with `needsHotel` → check-in = vessel date.
  - `test_unparsed_flight_falls_back_to_vessel_date`: no segments → transfer at vessel date 00:00, stay check-in vessel date.
  - `test_resave_is_idempotent`: PUT the same data twice → still 2 transfers.
  - `test_draft_follows_member`: rename member → draft guest renamed; change landing → draft time changed.
  - `test_switch_off_or_remove_deletes_draft_only`: complete the stay via PUT `/api/hotels/<id>/` (hotel listed with `tests.allow`), switch `needsHotel` off → stay kept; a still-draft stay of another member is deleted when the member is removed.
  - `test_dialog_save_keeps_link`: PUT the draft transfer through `/api/transfers/<id>/` with the guest's `crew_uid` → `draft=False`, uid kept; re-save crew change → no new transfer.
  - `test_same_name_two_members`: two on-signers both "JOHN DOE" → two transfers.
  - `test_deleted_transfer_comes_back`: DELETE the draft transfer, re-save crew change → a new draft.
  - `test_delete_service_drops_drafts_keeps_completed`.
  - `test_history_records_drafts`: a `ChangeRecord` for the created HotelStay with the request's user.
  - `test_other_port_and_viewer`: viewer cannot PUT (403, no bookings created).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `sync`: read members of this service (`onSigners` → "on", `offSigners` → "off");
  existing links = guests with `crew_uid` in this vessel's stays / transfers. Create missing drafts (with
  `Guest.crew_uid`), refresh drafts that hold exactly one guest, delete drafts whose member is gone (or, for stays,
  `needsHotel` off). Created objects use normal `.create()` so history signals fire. Completed bookings untouched.
- [ ] **Step 4:** Tests pass; whole suite green.
- [ ] **Step 5:** Commit `feat(bookings): automatic draft hotel and transport bookings for crew members`.

### Task 4: Alerts — booking gaps and early arrival

**Files:**
- Modify: `sheet/listing.py` (`missing_details`, `alerts_response` adds `"early"`)
- Modify: `sheet/static/sheet/js/render/notifications.js` (Early arrival group in bell and banner)
- Test: `sheet/tests_crew.py`

**Interfaces:**
- Consumes: `crewbookings.incomplete`, `logistics.parse_flight_time`.
- Produces: `alerts["early"]` = list of `{"id", "name", "date", "crew", "lands"}` (ISO dates), ordered by vessel date, id.
  `missing` entries gain `"Hotel: <guest>"` / `"Transport: <guest>"` items (after the agent items).

- [ ] **Step 1: Failing tests** `AlertTests(ApiTestCase)` (freeze "now" with `unittest.mock.patch("django.utils.timezone.now")`):
  - `test_incomplete_booking_listed_after_sailing`: vessel with `sailing_at` 1 hour ago and a draft transfer → its `missing` contains `"Transport: J SMITH"`.
  - `test_not_listed_before_sailing`: sailing tomorrow → not listed.
  - `test_completed_but_no_price_listed`: non-draft stay with `cost_per_night=None` → `"Hotel: …"`.
  - `test_early_arrival`: vessel 19.11, on-signer lands "17 NOV 10:00" → in `early`; lands 18.11 → not; off-signer landing early → not.
  - `test_broken_visa_zero_clears_early`: `brokenVisa.cost = 0` → not in `early`.
  - `test_early_port_scoped`: suez user doesn't see Alexandria rows.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Sailed = `sailing_at <= now` or (`sailing_at is None` and `date < today`). Booking gaps
  need their own query (vessels with incomplete stays / transfers, sailed), merged into the per-vessel entries.
  Early: Crew Change services of scoped vessels with `date >= today - 60 days`. Front end: one group **Early arrival**
  (row: vessel, crew, `lands dd/mm · vessel dd/mm`), click opens the vessel (`data-act="summary"`).
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit `feat(alerts): booking gaps after sailing and early-arrival on-signers`.

### Task 5: LOG PDF

**Files:**
- Create: `sheet/logpdf.py`
- Modify: `sheet/views.py` (`service_log`), `sheet/urls.py` (`api/services/<int:pk>/log/<str:uid>/`)
- Modify: `config/settings.py` (`LETTERHEAD_DIR = os.environ.get("DJANGO_LETTERHEAD_DIR", "")`), `.env.example`, `.gitignore` (`letterhead/`)
- Test: `sheet/tests_logpdf.py`

**Interfaces:**
- Produces: `logpdf.build(fields: dict, images: dict[str, bytes | None]) -> bytes`; fields keys
  `to, date, vessel, flight, personal`; images keys `logo, stamp, footer`.
- Produces: `logpdf.to_winansi(text: str) -> bytes`, `logpdf.jpeg_size(data: bytes) -> tuple[int, int] | None`.

- [ ] **Step 1: Failing tests:**
  - `test_pdf_structure`: `build(...)` starts with `b"%PDF-1.4"`, ends with `b"%%EOF\n"`, `startxref` offset points at `b"xref"`.
  - `test_fields_present_no_braces`: uncompressed content streams contain `TO:`, the airline, `OUR REF.:`, the vessel, `XXXXXXXXXXXXXXXXX.`, `VISA UPON ARRIVAL IN EGYPT`; no `{{`, `}}`, `PERSONAL DETAILS`.
  - `test_text_escaped`: flight `"a(b)c\\d {{x}} %PDF"` → appears as `a\(b\)c\\d {{x}} %PDF` inside a string; the PDF has the same object count.
  - `test_winansi_fallback`: `to_winansi("ŞĞİ Žž Иван")` == `b"SGI \x8e\x9e ????"`.
  - `test_long_text_adds_page`: 200 lines of flight text → `/Count 2` or more; every page references the logo when given.
  - `test_jpeg_size`: a minimal JPEG built in the test (SOI + SOF0 with 20×10 + EOI) → `(20, 10)`; PNG bytes → `None`.
  - `LogViewTests(ApiTestCase)`: alex GET on an Alexandria crew change on-signer → 200, `application/pdf`, `attachment; filename="LOG ALEX SHIP J SMITH.pdf"`; viewer → 403; suezuser → 404; off-signer uid → 404; unknown uid → 404; audit / rate limit: 21st call in the window → 429 (with `DJANGO_RATE_LIMIT_EXPORTS_PER_USER` default 20, use `override_settings` to 2).
  - `test_images_from_folder`: `override_settings(LETTERHEAD_DIR=<tmp with a test logo.jpg>)` → PDF contains `/DCTDecode`; empty setting → no image objects.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `logpdf.py` (A4 595×842 pt; fonts Helvetica, Helvetica-Bold, Courier-Bold with
  `/Encoding /WinAnsiEncoding`; text wrapping by character widths — Helvetica widths table for the letter text,
  Courier fixed 600; logo top-left, footer bottom full width, stamp right-aligned after the text; content streams
  uncompressed). Layout follows `LOG.docx` (see spec). `service_log`: `json_api`-style auth by hand like
  `export_csv` (401 / 403 / 404 JSON), `ratelimit.check(request, "export")`, `require_edit`, service via
  `scoped_vessels`, member found by uid in `onSigners`, `TO` = first segment's airline, date
  `timezone.localdate()` as `DD/MM/YYYY`, `api.audit(request, "service.log", id=…, vessel=…, crew=name)`; images
  read only from `settings.LETTERHEAD_DIR` with fixed file names; file name reduced with `re.sub(r"[^A-Za-z0-9 -]", "", …)`.
- [ ] **Step 4:** Tests pass. Open one generated PDF (with the real images from `LOG.docx`, kept outside the repo)
  in a viewer and compare with `LOG.docx` side by side.
- [ ] **Step 5:** Commit `feat(log): LOG letter PDF per on-signer`.

### Task 6: Front end

**Files:**
- Modify: `sheet/static/sheet/js/modals/service.js` (crew card: **Needs hotel** checkbox for all; on-signers:
  **Broken visa** cost / revenue + currencies and a **LOG** link `h('a', {class: 'btn ghost small', href: \`/api/services/${id}/log/${uid}/\`}, 'LOG')`
  shown only when the service is saved, the member has a uid and the user can edit; keep `uid` through edits)
- Modify: `sheet/static/sheet/js/pages/bookings.js` (**To complete** tag on `draft` rows)
- Modify: `sheet/static/sheet/js/modals/booking.js` (guests keep `crew_uid`; crew picker passes `uid` as `crew_uid`)
- Modify: `sheet/static/sheet/js/modals/vessel.js` (date input disabled and set to the sailing day while a sailing time is filled)
- Modify: `sheet/static/sheet/css/app.css` (tag style with tokens only)
- Test: `tools/ui_smoke_test.js`

- [ ] **Step 1:** Smoke test additions (fail first): alex opens MSC AURORA's crew change → each on-signer card has
  Needs hotel and Broken visa fields and a LOG link whose `GET` returns `application/pdf`; Transport page lists
  MSC AURORA drafts tagged **To complete**; bell shows **Early arrival** for the seeded on-signer; viewer sees no LOG
  link.
- [ ] **Step 2:** Implement; `cd tools && npm run lint` (or `npm run check`) clean.
- [ ] **Step 3:** Commit `feat(ui): crew card hotel, broken visa and LOG; draft tags; sailing date`.

### Task 7: Demo data, docs, full check

**Files:**
- Modify: `sheet/management/commands/seed_demo.py` (MSC AURORA: first on-signer `needsHotel`, second lands 3 days
  before the vessel date; call `crewbookings.sync` for seeded crew changes)
- Modify: `CLAUDE.md` (architecture: crewbookings, logpdf, letterhead, seed facts), `docs/STATUS.md`, `README.md`,
  `SECURITY.md` (test count; LOG gate and letterhead folder), `docs/DEMO_HOSTING.md` if the demo needs the setting
- [ ] **Step 1:** `cd tools && npm run check` → green.
- [ ] **Step 2:** Smoke test on a fresh scratch database for alex, admin, viewer, suez (CLAUDE.md recipe) → pass.
- [ ] **Step 3:** Fresh review of the whole branch (one reviewer), fix findings, re-run check.
- [ ] **Step 4:** Commit `docs: crew bookings, early arrival, LOG letter`.
