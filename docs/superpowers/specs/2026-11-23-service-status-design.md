# Service status and accounting status — design

Date: 2026-11-23. Branch: `feature/service-status` (from `main`). Next after it: Excel import (its own design).

## Why

Compared with the company's ARKAS V19 mock-up, the app could not say whether a service is still being worked on or was
cancelled, nor whether its money has been settled. The user wants **two separate statuses**, one per team:

- **Operations** (port users) mark each service **In progress / Completed / Cancelled**, with a reason when cancelled.
- **Accounting** marks each money row on the Calculations page **Open / Closed** (settled or not). The accountants are
  the people who today have **read-only** accounts; they stay read-only for everything else.

Success: operations see at a glance what is still open on a vessel; accounting filters Calculations to what is still
open (e.g. everything except Closed) and sees how much money that is.

## Decisions the user made

- Two independent statuses: operations on the service, accounting on Calculations.
- Accounting is done by **read-only** accounts (and admins); port users only see it.
- **Cancelled keeps the money in every total** (choice B): cancelling sets cost and revenue to 0 in the dialog, and
  anyone can type an amount back (a fee). Nothing is hidden from totals.
- A row whose cost and revenue are both 0 **stays off Calculations** (today's rule) — a cancelled service at 0 / 0 is
  not shown there; accounting only cares where there is money.
- Labels as previewed in the real app: amber **In progress**, green **Completed**, grey struck-through **Cancelled**
  beside the service name; the reason in italics under the details; Status and Accounting columns on Calculations.
- Filters as **tick-box dropdowns** (all ticked by default; untick Completed = "all except Completed").
- Counts of each status: Dashboard and the management Excel.
- **Cancelled outside the money:** cancelling a Crew Change deletes its **draft** bookings (saved bookings stay); a
  cancelled service raises **no alerts** (no Early arrival, no missing agent, no Hotel / Transport missing details).
  Setting it back to In progress or Completed brings the drafts (next `crewbookings.sync`) and the alerts back.
- **A Closed row is locked:** operations need accounting's permission — accounting reopens it first. While Closed,
  any edit or delete of that service / hotel stay / transfer, any change to that vessel's garbage / sludge
  (quantities or Hide), and deleting the vessel are **refused (400)** with "Accounting has closed this. Ask accounting
  to reopen it first."

## Goals

1. `Service.status` (`in_progress` / `completed` / `cancelled`) and `Service.cancel_reason` (text). Migration
   `0019_service_status`: existing services become `completed`; new ones start `in_progress`.
2. Service dialog: a **Status** dropdown beside Agent; choosing Cancelled shows **Cancellation reason** (required, max
   500 characters) and sets every cost / revenue input of the form to 0 on screen (the person can type amounts back
   before saving). Validation: status must be one of the three; a reason is required when Cancelled and **refused**
   otherwise (the dialog clears it when the status changes away from Cancelled).
3. Service card: the label beside the type; Cancelled shows "Reason: …". Vessel list Services column and the vessel
   summary: an amber "N in progress" chip when N > 0.
4. Accounting status: a boolean `acct_closed` (default False = Open) on **Service**, **HotelStay**, **Transfer** and
   **VesselDisposal** (the garbage / sludge rows of a vessel close together). A multi-entry service (Delivery Parcels /
   Courier, Landing, Crew Change lines) closes as one: all its rows share the flag. Existing rows start Open.
5. `POST /api/accounting/` `{"kind": "service" | "hotel" | "transfer" | "disposal", "id": n, "closed": bool}`:
   admins and read-only only (`access.require_accounting`), scoped like everything else (`scoped_vessels`; read-only
   sees all ports), rate limited as a write, one transaction, audited (`accounting.close` / `accounting.open`), recorded
   in the History by the model signals. It changes nothing else on the row and **does not raise `version`** (an
   accounting click must not make an operations dialog conflict, and operations saves never send or change
   `acct_closed`; saves write named fields so a stale save cannot overwrite it).
5a. **Lock** (`accounting.require_open(obj)` raising `BadRequest` with the message above): called by service PUT /
   PATCH / DELETE, booking PUT / DELETE, disposal PUT and vessel DELETE (any Closed service, booking or disposal of
   it) for **every role** — an admin reopens first, like anyone. Automatic writes (`crewbookings.sync`) never change
   or delete a Closed booking. Vessel edits that do not touch money (times, agents, notes) stay allowed; a
   sailing-day date change is allowed. The dialogs show the refusal like any other error; the service card and
   booking row show a small "Closed by accounting" note so nobody is surprised.
5b. **Cancelled:** `crewbookings.sync` treats a cancelled Crew Change as having no members (its drafts are deleted,
   Closed ones kept); `listing.missing_details` and the early-arrival check skip cancelled services.
6. Calculations: each row carries `status` (service rows; `null` for hotel / transfer / garbage), `cancel_reason`,
   `closed` and `ref` `{kind, id}`. Two new columns **Status** and **Accounting** (Open / Closed switch: clickable for
   admin / read-only, plain label for port users). Two tick-box filters: `status=` (comma list of
   `in_progress,completed,cancelled`; omitted = all; when it is not all, rows with no status — hotel, transfer,
   garbage — are left out) and `accounting=` (`open,closed`; omitted = all). Unknown values → 400. Totals follow the
   filters and add "Open N · Closed N".
7. Dashboard (`/api/dashboard/`): a small **Service status** table — per vessel-date month and in total: In progress /
   Completed / Cancelled (services) and Open / Closed (rows with money, the Calculations rows) — following the
   dashboard's date range, port and OPR filters (agent / service-type filters narrow the service counts like they
   narrow jobs). Management Excel: the same table on a new sheet "Service status".

## Non-goals / anti-goals

- No change to any money figure or rule (`finance.py`, `logistics.booking_line`, `disposal`).
- No new role, no new sign-in, no extra rights for read-only beyond the Open / Closed switch.
- No bell alert for services still in progress (offered, not chosen).
- No stat cards, help text or placeholders (the user's preference).
- Accounting status is not shown or editable outside Calculations (and the counts).

## Constraints

- Input refused, never silently fixed (`validators.py`); amounts never negative.
- Every API view through `api.json_api`, vessels through `access.scoped_vessels`.
- Front end only through `dom.js`; colours only as `app.css` tokens (status colours from `--warning`, `--success`,
  `--muted`); no inline styles.
- Edit conflicts: `status` / `cancel_reason` are part of the service PUT and its `version` like the other fields.
- `README.md` / `SECURITY.md` test counts, `STATUS.md`, `CLAUDE.md`, `DEPLOYMENT.md` (read-only now has one write)
  updated.

## Approaches

1. **Fields on the existing models + one small accounting endpoint** (chosen): status lives with the service, the
   accounting flag with each thing that makes a Calculations row; History and scoping come for free.
2. A separate `AccountingMark` table keyed by (kind, id): no model changes, but orphan rows on delete and joins on every
   Calculations request. Rejected.
3. Status inside `Service.data` JSON: no migration, but it would mix status into the per-type data shape and its
   validators, and could not be filtered cheaply. Rejected.

## Left to the builder

- **Calls made for the user (check these):** the lock applies to admins too (they can reopen themselves); the
  Open / Closed counts count Calculations rows (the lines accounting sees); Dashboard / Excel show counts only (open
  money is on Calculations, whose totals follow the filters).
- Exact markup of the tick-box dropdown (a `<details>` with checkboxes is enough; no new library).
- Which inputs count as "cost / revenue" per service type when zeroing on Cancelled (every money input of the form:
  entries' cost / revenue, single cost / revenue, Crew Change broken-visa cost / revenue, Cash to Master's own share);
  the amount paid to the master is not cost or revenue and is left as typed.
- The Dashboard table's layout (follow the existing jobs tables).
