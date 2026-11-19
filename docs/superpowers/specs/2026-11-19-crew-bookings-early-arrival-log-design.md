# Crew change: automatic bookings, sailing date, early arrival, LOG letter

Designed 2026-11-19 with the user. Branch: `feature/crew-bookings-log`.

## Why

The crew change is where the operator first learns who is coming and going. Today hotel rooms and car trips are
entered separately on the Hotels / Transport pages, so it is easy to forget one, and nothing warns when a booking is
still incomplete after the vessel has left. An on-signer who lands two or more days before the vessel breaks the
visa terms, which costs money that is currently untracked. And the "Letter of Guarantee" (LOG) the airline needs for
each on-signer is typed by hand in Word from data the app already holds.

## What the user decided

1. **Needs hotel** switch on every crew member (on- and off-signers). Switched on → a **hotel booking appears by
   itself** on the Hotels page with the guest's name, the vessel and the check-in date (on-signer: the day their flight
   lands; off-signer: the vessel date). The user completes hotel, nights, cost and revenue later.
2. **Every crew member gets a transport booking by itself** (on-signer: airport → port at their landing time;
   off-signer: port → airport at their departure time). The user completes the places and price.
3. **Missing data warning:** once the vessel has **sailed**, every booking of it that is still incomplete is listed in
   the bell / banner.
4. **Vessel date = sailing date:** when a sailing time is entered, the vessel's date becomes that day (Cairo). The
   vessel may move to the next month in the list, Dashboard and Calculations — accepted ("Yes, replace it").
5. **Early arrival:** an on-signer whose flight lands **2 or more days before the vessel date** (lands 17/11, vessel
   19/11) is shown in the bell / banner. The user can then enter a **Broken visa** cost (and revenue, if the owner is
   charged) on that on-signer.
6. **LOG letter:** a **LOG** button on each on-signer downloads a **real PDF file** that looks like the user's Word
   letter (`LOG.docx`), with the `{{ }}` parts filled from that on-signer's data and everything else unchanged. **Anyone
   who can edit** the vessel may make it.
7. **No outside library** for the PDF: written by our own Python code. Letters outside the Western European set print
   as their plain form (Ş → S, Ğ → G, İ → I); letters with no plain form (Cyrillic, Arabic) print as `?` — accepted.
8. **No `{{ }}`** and no placeholder labels in the PDF: each placeholder is replaced by the value alone
   (`{{PERSONAL DETAILS:}}` → the personal details text, no "PERSONAL DETAILS:" label).

## Approaches considered (LOG PDF)

- **A. Server makes a real PDF** — picked. One click, a real file, the stamp never served on its own.
- **B. Browser print page** ("Save as PDF") — no new code beyond a page, but an extra step every time, margins differ
  by browser, and the stamp image would have to be downloadable by any signed-in user. Rejected.
- **C. Fill the .docx and convert** — needs Word / LibreOffice on the server. Rejected.
- Within A, **fpdf2** was considered and rejected by the user (no outside library). The PDF is hand-written:
  a PDF is structured text; the three JPEGs embed as they are (`/DCTDecode`, no decoding — only width / height are read
  from the JPEG header); text uses the built-in Helvetica / Helvetica-Bold / Courier-Bold fonts with WinAnsi encoding.

## Goals / non-goals / anti-goals

- Goals: no crew member without a transport booking; no hotel forgotten; incomplete bookings surface after sailing;
  broken-visa money tracked; LOG in one click.
- Non-goals: a LOG for off-signers; editing the letter text in the app; e-mailing the LOG; embedding fonts.
- Anti-goals: the signed company stamp ending up public (in the public GitHub repo, as a static file, or downloadable
  by read-only users); crew text able to change the letter's layout; a booking the user completed being deleted or
  changed by a crew-change edit.

## Design

### Crew member data (`Service.data` of a Crew Change, `validators._crew_member`)

New keys per member:
- `uid`: 12 lowercase hex characters, the member's stable identity. Kept when the browser sends a valid one that
  already exists on this service; otherwise the server makes a new one (`secrets.token_hex(6)`). The browser keeps it
  when editing.
- `needsHotel`: boolean.
- On-signers only: `brokenVisa`: `{cost, costCurrency, revenue, revenueCurrency}` with the usual `_amount` /
  `_currency` rules (never negative; empty = not entered). Off-signers never keep it.

The crew card (`modals/service.js`) gets a **Needs hotel** checkbox for every member, and for on-signers a
**Broken visa** cost / revenue pair (with currencies), plus the **LOG** button (only on a saved service).

### Money

`finance._all_lines` for a Crew Change: the existing cost / revenue line, then one line per on-signer whose broken visa
has a cost or revenue: label `Broken visa · <name>`, same exchange rate rule as the service. So it counts in the
vessel's figures, the Dashboard and Calculations, like the rest of the crew change. `js/calc.js` mirrors it.

### Automatic bookings (`crewbookings.py`, new)

- `Guest.crew_uid` (CharField 12, blank, indexed) links a guest to a crew member. `HotelStay.draft` and
  `Transfer.draft` (boolean, default False) mark bookings made automatically and not yet completed by a person.
- `sync(service)` runs in the same transaction after a Crew Change is created or updated (`api` service views):
  - each member with `needsHotel` and no hotel guest with its uid on this vessel → a **draft hotel stay**: hotel `""`,
    check-in as in decision 1 (flight date via `logistics` flight parsing, else the vessel date), nights 1, no money,
    one guest copied as today (`_crew_entry`) with `crew_uid`.
  - each member with no transfer guest with its uid on this vessel → a **draft transfer** as in decision 2; time from
    the flight, else the vessel date at 00:00; the place names empty.
  - **drafts follow the crew change**: while a booking is still a draft and holds only that one guest, its guest copy
    and date / time are refreshed from the member (name, rank, flight, check-in / time).
  - a member removed, or with `needsHotel` switched off → its **draft** stay / transfer is deleted; a **completed**
    booking is never touched (the guest stays; the Missing details alert does not mention it).
  - a draft the user deletes by hand on the Transport page comes back on the next save of the crew change (every
    crew member must have transport). A draft hotel deleted by hand also comes back while Needs hotel is on.
- Deleting the Crew Change service (or the vessel) deletes its drafts; completed bookings follow today's rules.
- Saving a booking through the Hotels / Transport dialog (`PUT`) sets `draft = False`; the dialog's validation is
  unchanged (hotel / places required), so a completed booking always has its hotel / places.
- `history.record_created` / signals record the automatic bookings like any other ("system" is never the actor: the
  request's user is).
- Bookings pages: drafts show a **To complete** tag; rows open the normal dialog.

### Vessel date = sailing date

`validators.clean_vessel`: when `sailing_at` is set, `date` = its Cairo date (the posted date is ignored). The vessel
form shows the date field disabled while a sailing time is filled. A migration data step applies the same rule to
existing vessels with a sailing time (builder's call, see below). The "outside the current range" notice already
covers a vessel moving out of the shown range.

### "Sailed" and the missing-booking warning

A vessel has **sailed** when `sailing_at` ≤ now, or it has no sailing time and its date is before today (Cairo).
`listing.missing_details` adds, per sailed vessel, one entry per incomplete booking: `Hotel: <guest>` /
`Transport: <guest>`. Incomplete = `draft`, or cost or revenue empty. These join the existing "Missing details" line
of that vessel (one line per vessel stays). A vessel with only booking gaps but not yet "dated before today" (sailed
earlier today) is included.

### Early arrival alert

`alerts_response` gets `early`: on-signers of vessels whose arrival date (last flight leg's landing, parsed as in
`crew_of`) is ≤ vessel date − 2 days and whose broken visa has neither cost nor revenue (an entered 0 counts as
handled). Row: vessel id / name / date, crew name, landing date. Shown as its own group in the bell and banner
(**Early arrival**), clicking opens the vessel. No look-back limit (same as Missing details); only vessels dated from
today − 60 days onward are read, to keep the query light (builder may tune).

### LOG PDF

- Route: `GET /api/services/<id>/log/<uid>/` → `application/pdf`, `Content-Disposition: attachment;
  filename="LOG <vessel> <crew>.pdf"` (name reduced to letters, digits, spaces, `-`), `X-Content-Type-Options:
  nosniff`. Auth and two-step as every API call; the service through `access.scoped_vessels`; `access.require_edit`
  (read-only users 403, other ports 404); rate-limited like the CSV export (`ratelimit.check(request, "export")`);
  `api.audit` records who made which LOG (vessel, crew name). The crew member must be an on-signer of that service.
- `logpdf.py` (new, standard library only): `build(fields, images) -> bytes`. A4 page(s); on every page the logo top
  left and the footer image at the bottom; then, as in `LOG.docx`:
  - `TO:` airline of the on-signer's first flight leg (empty if none) · `DATE:` today, Cairo, `DD/MM/YYYY`
  - `CC:` `XXXXXXXXXXXXXXXXX.` (unchanged) · `OUR REF.:` vessel name
  - `SUBJECT: Invitation letter for boarding  M/v <vessel>` bold, with a rule under it
  - `PLEASE NOTE THAT THE FOLLOWING CREW MEMBER (S) WILL JOIN M/V <vessel>`
  - the member's pasted **flight details** (`flightData`), Courier-Bold, line breaks kept, long lines wrapped
  - the member's pasted **personal details** (`personalData`), same style
  - `A visa has been arranged before departure and will take care of him.` and `VISA UPON ARRIVAL IN EGYPT` (bold)
  - the stamp on the right after the text.
  Text that runs past the page continues on a new page (with logo and footer); the stamp moves with it.
- Text safety: every value is plain text; converted to WinAnsi (NFKD, then drop combining marks, then `?`), and the
  PDF string escapes `\`, `(`, `)` and control characters. No PDF names, operators or links come from data. Lengths are
  already capped (flight 4000, personal 2000, names 120 / 160).
- **Images are not in git** (the GitHub repo is public): logo, stamp and footer are read from a folder named by
  `DJANGO_LETTERHEAD_DIR` (files `logo.jpg`, `stamp.jpg`, `footer.jpg`), outside `static/`, never served on their own.
  Missing folder / file → the letter is made without that image (the online demo and tests). Only baseline JPEGs are
  accepted (SOF0 / SOF2 header read; anything else → left out, logged).
- Front end: the LOG button fetches the PDF and saves it with a `blob:` link and `download` attribute (same pattern
  as the CSV export if it fits); errors through the usual feedback.

## Constraints

Security rules of `CLAUDE.md` (dom.js only, no innerHTML, CSP), `scoped_vessels`, one transaction per write, change
history, validators refuse rather than fix, hash-locked requirements unchanged (no new package), `npm run check` green,
smoke test for alex / admin / viewer / suez. Migration `0014`. `seed_demo`: MSC AURORA's crew change gets uids, one
on-signer with Needs hotel and one landing 3 days early (the smoke test checks the Early arrival alert, the draft
bookings and that the LOG downloads for alex, not for viewer).

## Builder's calls (marked for the user to check)

- Existing vessels with a sailing time get their date moved to the sailing day by the migration.
- Existing crew changes get uids and automatic bookings only when next saved (no bulk creation by the migration).
- Draft placeholders: nights 1, time 00:00 of the vessel date when the flight time can't be read.
- A transport draft deleted by hand comes back on the next crew-change save.
- Date on the LOG `DD/MM/YYYY`; `TO:` empty when no airline is known.
- Early-arrival look-back 60 days.
