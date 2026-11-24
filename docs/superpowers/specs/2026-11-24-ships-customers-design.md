# Ships, customers, agreed rates, billing party, Cash / On account — design

Date: 2026-11-24. Branch: `feature/ships-customers` (from `main`). Piece 1 of three agreed on 2026-11-24
(1 this, 2 an In-progress services page, 3 an accounts and permissions page for admins), each designed on its own.

## Why

Master data today is lists of names. The user wants it enriched: **customers** with their agreed rates, contact
details (people, emails, phone numbers) and linked vessels, and a **list of ships** (name, IMO number, OPR) so that
creating a vessel means typing a name and picking the ship from a dropdown. On a service the user wants an optional
**billing party** ("a vessel might be ARKAS but the billing party is someone else") and a choice of **cash** instead of
everything being on account. The agreed rate must **fill in the revenue automatically, and people can change it**.

## Decided by the user

- The customer is **separate from the OPR** (option B): the customer is who we bill (e.g. the owner / manager); each
  ship has both an OPR and a customer.
- Agreed rates fill in the revenue automatically; the person can change it.
- A ship that is not in the list yet is **added right there from the vessel form** (and the quick-add bar), by
  **admins and port users**.
- Billing party on a service is optional; services can be Cash instead of On account.
- Order: this piece first, then the In-progress page, then the accounts page.

## Goals, non-goals, anti-goals

- Goals: one ship record per real ship (IMO), reused by every port call; customers with contacts and rates; revenue
  pre-filled from the rate of whoever pays; who pays and Cash / On account visible where accounting works
  (Calculations and its Excel).
- Non-goals: no automatic linking of old vessels to ships (they get linked when someone picks the ship in their
  form); no customer invoices or statements; no rates for hotels / transport / garbage & sludge (those have their own
  prices); no change to how the server works out money (`finance.py`) — the stored amounts are still the truth; no
  Dashboard changes.
- Anti-goals: a changed rate silently rewriting services already saved; a typed revenue being overwritten behind the
  person's back once they changed it; customer / ship data that can be deleted while services depend on it; any new
  way of building screens outside `dom.js` (no `innerHTML`, no datalist tricks that need HTML strings).

## Approaches

- **New tables, the form fills in the revenue (chosen).** `Ship`, `Customer`, `CustomerContact`, `CustomerRate`;
  `Vessel.ship`, `Service.billing_party`, `Service.billing`. The service dialog looks up the payer's rate and fills
  the revenue boxes as the person works; the server stores what was sent. Keeps the money logic where it is.
- Server fills the revenue when the box is empty: can't tell "left empty" from "0 on purpose", and the person sees the
  amount only after saving. Dropped.
- Customers / ships as more Master data lists (`Option`): a list value can't hold contacts, rates or an IMO. Dropped.

## Design

### Ships (new page "Ships", admins and port users edit; everyone reads)

- `Ship`: `name` (upper case, like vessel names, 120), `imo` (7 digits, **unique**, IMO check digit verified — my
  call, catches typos; **required unless the ship's "No IMO" tick box is ticked** — the user, 2026-11-24: "always
  have an IMO but give me a check box to disable it"; ticked → the IMO is empty, unique only among ships that have
  one; the tick box is in the ship dialog for everyone who adds ships, my call), `opr` (from the Master data OPR list of All ports or the saving user's port; an admin may
  pick any port's OPR — my call), `customer` (FK, optional, `PROTECT`), `active` (default true), `created_at`.
  Names may repeat (the IMO is the identity).
- Shared by all ports (one ship calls at several ports — my call).
- Page: search box (name or IMO), table Name / IMO / OPR / Customer / port calls count, + Ship, click a row to edit.
  Inactive ships shown greyed with a filter; inactive ships are left out of the vessel dropdown.
- Delete: admins only, and only when no vessel uses it (`PROTECT`); otherwise mark inactive.
- API: `GET /api/ships/?q=&active=` (list; `q` matches name or IMO, literal, case-insensitive), `POST /api/ships/`,
  `PUT /api/ships/<id>/`, `DELETE /api/ships/<id>/`. Writes: `access.require_edit`; delete `require_admin`.

### Picking a ship when adding / editing a vessel

- The **Vessel name** box in the quick-add bar and in the vessel form becomes a type-ahead: as the person types
  (2+ characters, short debounce), a list under the box shows up to 10 active ships matching the name or IMO, each as
  "NAME · IMO · OPR". Arrow keys / Enter / click pick one; Escape closes. Built with `dom.js` only.
- Picking a ship sets the vessel's name and OPR from the ship and remembers `ship` (sent as `ship_id`). The OPR stays
  changeable on the vessel (my call: a call can be under another operator); the ship's OPR is always accepted for the
  vessel even when that port's OPR list doesn't have it (my call; `listed` gets the ship's OPR as an allowed value).
- The last item of the list is always **+ New ship "TYPED NAME"**: it opens a small ship dialog (name pre-filled,
  IMO, OPR, customer optional) on top of the form; saving it creates the ship and picks it.
- **A new vessel must be linked to a ship** (my call, so every new call has a customer; adding one is one step). Old
  vessels without a ship still save; once linked, the ship can be changed but not removed (like OPR / POC).
  Enforced by the API's vessel POST (my call); the Django admin pages stay a superuser fallback without the check.
  `seed_demo` creates ships (and customers with rates) for its vessels; the tests' vessel helper makes a ship itself.
- Quick-add: Enter picks the highlighted ship and adds the vessel; with nothing highlighted it opens New ship (my
  call; the bar still adds in one go once a ship is picked).
- Typing over the name after picking a ship clears the pick (the person must pick again or add a new ship).
- The vessel keeps its own `name` and `opr` text (copied at pick time), so old calls keep the name / operator they
  had if the ship record changes later. The vessel dialog's header shows the IMO.
- `Vessel.ship`: FK, nullable, `PROTECT`, scoped like everything else (the ship itself is shared; the vessel stays
  scoped by its port).

### Customers (new page "Customers"; admins edit; everyone reads)

- `Customer`: `name` (unique, 120), `notes` (500), `active`, `created_at`.
- `CustomerContact` (0–20 per customer): `name`, `role` (e.g. "Accounts"), `email` (validated), `phone` (digits,
  spaces, + - ( ) only, 40). My call on the fields and the limit.
- `CustomerRate` (at most one per customer and service type): `service_type`, `amount`, `currency` (USD / EGP).
  What the amount means depends on the type (shown next to the box):
  - Crew Change, Medical Treatment, Certificates: per service.
  - Fresh Water: per unit of quantity (revenue = rate × quantity).
  - Delivery Parcels, Delivery Courier, Landing: per line (each new line's revenue = rate).
  - Cash to Master: a percentage (0–100); its currency box is hidden.
  - Others / Remarks: no rate (free text service).
  Amounts never negative (as everywhere).
- Page: list of customers (name, contacts count, ships count, active); + Customer; a dialog with name, notes,
  active, a contacts table (+ Contact / remove), a rates table (one row per service type, empty = no agreed rate),
  and a read-only list of the **linked ships** (ships whose customer is this one; clicking opens the ship).
- Shared by all ports (my call). Delete: only when no ship and no service uses it; otherwise mark inactive (hidden
  from dropdowns, kept on old records).
- API: `GET /api/customers/` (with contacts, rates and linked ship ids / names; every role),
  `POST /api/customers/`, `PUT /api/customers/<id>/` (whole customer incl. contacts and rates, one transaction),
  `DELETE /api/customers/<id>/`. Writes `access.require_admin`.

### On each service

- `Service.billing_party`: FK to Customer, nullable, `PROTECT`. **The dialog fills it in with the ship's customer**
  when the service is created (my call: stored, so a ship moving to another customer later never changes who paid
  for old services); the person may choose another customer or leave it empty. Old services: empty.
- `Service.billing`: `account` (default, "On account") / `cash` ("Cash"). Existing services become On account.
  **A label only** (the user, 2026-11-24): set by edit roles in the service dialog, no other accounting effect; its
  use is the Calculations filter, so cash lines can be filtered out.
  `clean_service_billing` like `clean_service_status`: a save without the key keeps the stored value.
- Both are under the service's status in the dialog; both are tracked by edit conflicts (`version`) and the History,
  and locked by accounting Closed like the rest of the service.
- **Revenue fill-in** (front end only, `js/rates.js` pure helper unit-tested in `tools/parsing_test.js`):
  - The rate used is the billing party's rate for that service type (none → nothing filled).
  - It fills the revenue (and its currency) when the dialog opens for a **new** service, when the billing party is
    changed, when the Fresh Water quantity changes, and for each new Parcels / Courier / Landing line.
  - It never overwrites a revenue box the person has typed in during this dialog, and never touches a saved service's
    revenue on open (a rate changed later doesn't change saved services).
  - On a **saved** service (my call, after the builder check) it fills only a box that is empty or 0, so a revenue
    typed last week stays when someone later changes the quantity or the billing party. On a **new** service it
    refills every box not typed in yet (single revenue, and lines added in this dialog). "Typed in" is tracked per
    dialog; nothing extra is stored.
  - A small "Agreed rate" note beside the revenue shows the rate in use (the minimal-UI exception: one short line),
    with nothing shown when there is no rate.
- The server doesn't check the revenue against the rate (the person may change it).

### Calculations and exports

- Calculations rows (services) get **Billing party** and **Billing** (Cash / On account) columns; booking and garbage
  rows show empty. A Billing filter (tick boxes, "all except", like Status) and a Billing party dropdown (customers
  present in the range). Totals follow the filters.
- The Calculations data export (single page and All data) gets the same two columns. The management Excel is left
  alone.

### Rules as everywhere

- Input refused, never fixed (`validators.py`, whitelisted keys, length limits). History signals on Ship, Customer,
  CustomerContact, CustomerRate. Audit with `api.audit`. Rate limited writes. No `version` on ships / customers (like
  Master data, which the conflict decision left out — my call).
- Migrations hand-written where needed; one migration for the new tables, fields and the On account default.
- Docs updated: STATUS, CLAUDE (architecture), README / SECURITY test count, DEPLOYMENT if roles change (they don't).

## Left to the builder

Exact page layouts and column order (lean, as the other pages), the nav position of Ships and Customers (next to
Master data), icons (from the sprite; add new ones to `icons.svg` and `ICONS`), debounce timing, the type-ahead's
keyboard details, file / module names, and the test split.
