# Ships, Customers, Rates, Billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ship list (name, IMO, OPR, customer) picked by type-ahead when adding vessels; customers with contacts
and agreed rates that pre-fill service revenue; an optional billing party and Cash / On account on each service,
shown and filtered on Calculations and its Excel.

**Architecture:** New models `Ship`, `Customer`, `CustomerContact`, `CustomerRate` (migration 0021) with two new
modules, `sheet/ships.py` and `sheet/customers.py` (cleaning lives in `validators.py`, as everywhere). `Vessel.ship`,
`Service.billing_party`, `Service.billing` join them to the existing flow. The revenue fill-in is front end only
(`js/rates.js`, pure and unit-tested); the server stores what is sent and `finance.py` is untouched.

**Tech Stack:** Django 5.2, vanilla ES modules (`dom.js`), Django test runner, Node parser tests, `tools/ui_smoke_test.js`.

**Spec:** `docs/superpowers/specs/2026-11-24-ships-customers-design.md`

## Global Constraints

- Branch `feature/ships-customers` (exists, design committed); one commit per task (Conventional Commits, ending
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`).
- IMO: exactly 7 digits, check digit valid, unique among ships that have one; required unless `no_imo` is true (then
  stored empty). Ship names upper case, 120 max. Customer name unique (case-insensitive), 120 max; notes 500;
  contacts 0–20 (name 100, role 60, email 254 valid, phone 40 of digits / spaces / `+ - ( )`); one rate per
  customer and service type, never for "Others / Remarks"; amounts never negative; Cash to Master rate 0–100.
- Rate meaning per type: per service (Crew Change, Medical Treatment, Certificates), per unit of quantity (Fresh
  Water), per line (Delivery Parcels, Delivery Courier, Landing), percentage (Cash to Master).
- `Service.billing`: `"account"` (default, label "On account") / `"cash"` (label "Cash"); a label only.
- Ships: admins and port users write (`require_edit`), admins delete; customers: admins write (`require_admin`);
  everyone reads both. Ships and customers shared by all ports. In use → delete refused
  ("In use: mark it inactive instead."), `on_delete=PROTECT`.
- New vessel through the API must have `ship_id` ("Choose a ship, or add a new one."); once linked it can't be
  emptied. The ship's OPR is always allowed as the vessel's OPR.
- Input refused, never fixed; whitelisted keys; one transaction per write (`json_api`); `api.audit` on every write;
  History signals on the four new models; no `version` on ships / customers.
- Front end only through `dom.js` (no `innerHTML`, inline style, `eval`); icons from the sprite (`icons.svg` +
  `ICONS` together); colours from tokens; lean screens (no help paragraphs, no placeholders); LF line endings.
- `npm run check` green before the merge; README / SECURITY test counts, STATUS, CLAUDE updated in the last task.

## Review Focus

1. A port user edits a saved service whose revenue was hand-typed, then changes the quantity or billing party: the
   typed revenue stays. Test: Task 8 `fill keeps saved non-zero revenue` (parsing_test).
2. Two ships, one with No IMO and one without IMO in the payload: the first saves with empty IMO, the second is
   refused; a second No IMO ship also saves (empty IMOs don't clash). Test: Task 1 `test_no_imo_ships_do_not_clash`.
3. A vessel POST with a `ship_id` that doesn't exist or is inactive: 400, not 500 / a silent link. Test: Task 3
   `test_unknown_or_inactive_ship_refused`.
4. Calculations `billing=cash` (filter out on-account) keeps booking and garbage rows; `billing=junk` → 400. Test:
   Task 5 `test_billing_filter_keeps_other_rows_and_refuses_junk`.
5. A customer PUT with a duplicate service type in rates, or a rate for "Others / Remarks": 400, nothing saved
   (contacts untouched). Test: Task 2 `test_bad_rates_refused_and_nothing_saved`.

---

### Task 1: Ship and customer models, ships API

**Files:**
- Modify: `sheet/models.py`, `sheet/constants.py`, `sheet/validators.py`, `sheet/history.py` (`TRACKED`),
  `sheet/admin.py`, `sheet/views.py`, `sheet/urls.py`
- Create: `sheet/migrations/0021_ships_customers.py`, `sheet/ships.py`, `sheet/tests_ships.py`

**Interfaces:**
- Produces models:
  - `Customer(name CharField 120, notes CharField 500 blank, active Bool True, created_at)`, ordering `name`.
  - `CustomerContact(customer FK CASCADE related_name="contacts", name 100, role 60 blank, email 254 blank, phone 40
    blank, position PositiveInt)`, ordering `position, id`.
  - `CustomerRate(customer FK CASCADE related_name="rates", service_type CharField 40 choices SERVICE_TYPES, amount
    Decimal(12,2), currency CharField 3 "USD"|"EGP")`, unique (customer, service_type).
  - `Ship(name 120, imo CharField 7 blank, opr CharField 100 blank, customer FK Customer null PROTECT
    related_name="ships", active Bool True, created_at)`, ordering `name, id`; constraint unique `imo` where
    `imo != ""` (`UniqueConstraint(fields=["imo"], condition=~Q(imo=""), name="unique_imo")`).
  - `Vessel.ship` FK Ship null PROTECT related_name="vessels"; `Service.billing_party` FK Customer null PROTECT
    related_name="services"; `Service.billing` CharField 8 choices `BILLING`, default `"account"`.
- `constants.BILLING = {"account": "On account", "cash": "Cash"}`; `constants.RATE_UNITS = {"Crew Change":
  "service", "Medical Treatment": "service", "Certificates": "service", "Fresh Water": "unit", "Delivery Parcels":
  "line", "Delivery Courier": "line", "Landing": "line", "Cash to Master": "percent"}` (Others / Remarks absent =
  no rate).
- `validators.imo_valid(text: str) -> bool`; `validators.clean_ship(data, profile, existing=None) -> dict` (keys
  name, imo, opr, customer, active).
- `ships.ship_to_dict(ship) -> {"id", "name", "imo", "opr", "customer": {"id","name"} | None, "active",
  "calls": int}`; `ships.list_response(params) -> {"ships": [...]}` (`q` literal case-insensitive on name or IMO,
  `active=1` only active, at most 200 rows, `limit` param 1–200 for the type-ahead); `ships.save_ship(profile,
  payload, existing=None) -> Ship`.
- Routes: `GET/POST /api/ships/` (`views.ships_list`), `PUT/DELETE /api/ships/<id>/` (`views.ship_detail`).
  Audits `ship.create` / `ship.update` / `ship.delete`.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_ships.py` (`ApiTestCase`):
  - `test_imo_check_digit`: `imo_valid("9074729")` True; `"9074728"`, `"907472"`, `"90747290"`, `"9O74729"` False.
  - `test_port_user_creates_ship`: alex POST `{"name": "msc aurora", "imo": "9074729", "opr": "TEST OPR"}` → 201,
    name `"MSC AURORA"`, `customer` None, `calls` 0; History has a ChangeRecord for the ship.
  - `test_imo_required_unique_and_checked`: missing IMO → 400; bad check digit → 400; same IMO twice → 400.
  - `test_no_imo_ships_do_not_clash`: two POSTs with `no_imo: true` (and an `imo` sent anyway) → both 201, `imo` "".
  - `test_opr_must_be_listed`: OPR not in Master data → 400; an admin may use an OPR listed only for suez.
  - `test_viewer_reads_but_cannot_write`: viewer GET 200, POST 403.
  - `test_search_and_active_filter`: `q=aur` and `q=907472` find it; `active=1` hides inactive; `q` with `%` / `.`
    is literal.
  - `test_delete_admin_only_and_refused_in_use`: alex DELETE 403; admin DELETE unused 200; admin DELETE a ship a
    vessel uses → 400 "In use: mark it inactive instead."
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_ships` — expected: FAIL (import / 404).
- [ ] **Step 3: Implement** the models, constants, `imo_valid` (weights 7..2 on the first six digits, sum mod 10 ==
  seventh), `clean_ship` (OPR via `listed("opr", value, profile.port)`, admins: any port's OPR; customer by id must
  exist and be active unless it is the saved one), migration 0021 (tables + fields; existing services get
  `billing="account"` by the default), `TRACKED` += the four models, read-only admin registrations like `Option`,
  `ships.py`, the views and routes.
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet.tests_ships sheet.tests_history` — PASS; and
  `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations --check --dry-run` — "No changes detected".
- [ ] **Step 5: Commit** `feat(ships): ship and customer models, ships API`.

### Task 2: Customers API

**Files:**
- Modify: `sheet/validators.py`, `sheet/views.py`, `sheet/urls.py`
- Create: `sheet/customers.py`, `sheet/tests_customers.py`

**Interfaces:**
- Consumes: Task 1 models, `constants.RATE_UNITS`.
- Produces: `validators.clean_customer(data, existing=None) -> {"name", "notes", "active", "contacts": [dict],
  "rates": [dict]}`; `customers.customer_to_dict(c) -> {"id", "name", "notes", "active", "contacts": [{"name",
  "role", "email", "phone"}], "rates": {service_type: {"amount": float, "currency": str}}, "ships": [{"id",
  "name", "imo"}]}`; `customers.save_customer(payload, existing=None) -> Customer` (replaces contacts and rates in
  the same transaction); routes `GET/POST /api/customers/` (`views.customers_list`, GET `{"customers": [...]}`
  ordered by name), `PUT/DELETE /api/customers/<id>/` (`views.customer_detail`). Audits `customer.create` /
  `.update` / `.delete` (ids only, no contact details in the audit).

- [ ] **Step 1: Write the failing tests** in `sheet/tests_customers.py`:
  - `test_admin_creates_customer_with_contacts_and_rates`: POST name "Blue Owners", 2 contacts, rates
    `{"Fresh Water": {"amount": 12.5, "currency": "USD"}, "Cash to Master": {"amount": 5}}` → 201, returned shape as above.
  - `test_only_admin_writes_everyone_reads`: alex / viewer POST 403; alex / viewer GET 200 and see contacts / rates.
  - `test_bad_rates_refused_and_nothing_saved`: PUT with a rate for "Others / Remarks", or Cash to Master 101, or a
    negative amount, or an unknown type → 400 and the stored contacts / rates unchanged.
  - `test_contact_limits`: bad email, phone "12ab", 21 contacts, name too long → 400.
  - `test_name_unique_case_insensitive`: "blue owners" after "Blue Owners" → 400.
  - `test_linked_ships_listed`: a ship with this customer appears in `ships`.
  - `test_delete_refused_in_use`: used by a ship → 400; used by a service's billing party → 400; unused → 200.
  - `test_inactive_customer_not_assignable`: a ship POST with an inactive customer → 400.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_customers` — FAIL.
- [ ] **Step 3: Implement** `clean_customer` (email with Django's `validate_email`, phone regex
  `^[0-9 +()\-]{1,40}$`), `customers.py`, views, routes.
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet.tests_customers sheet.tests_ships` — PASS.
- [ ] **Step 5: Commit** `feat(customers): customers with contacts and agreed rates`.

### Task 3: Vessels linked to ships

**Files:**
- Modify: `sheet/validators.py` (`clean_vessel`), `sheet/views.py` (vessel POST / PUT), `sheet/serializers.py`
  (`vessel_to_dict`), `sheet/tests.py` (`ApiTestCase.call`, `setUpTestData`), `sheet/management/commands/seed_demo.py`
- Test: `sheet/tests_ships.py` (class `VesselShipTests`)

**Interfaces:**
- Consumes: Task 1 `Ship`.
- Produces: vessel payload key `ship_id` (int); `clean_vessel` returns `ship` (Ship | None); vessel JSON gains
  `"ship": {"id", "name", "imo", "customer_id"} | None`. Test helper: `ApiTestCase` creates `cls.test_ship` (IMO
  "9074729", OPR NEEDED["opr"]) and `call` adds `ship_id: cls.test_ship.id` to a `post` on `/api/vessels/` that
  has none (like it adds `version`); the "required" check itself is tested with a raw request.
- `seed_demo`: customers "Blue Owners" (Fresh Water USD 50 per unit, Crew Change USD 300) and "Red Managers"; a ship
  per demo vessel (MSC AURORA → Blue Owners), and its vessels linked; Fresh Water's existing USD service unchanged.

- [ ] **Step 1: Write the failing tests** (`VesselShipTests`):
  - `test_new_vessel_needs_ship`: raw POST without `ship_id` → 400 "Choose a ship, or add a new one."
  - `test_ship_links_and_is_returned`: POST with `ship_id` → `ship.imo` "9074729"; GET returns it.
  - `test_ship_opr_allowed_even_if_unlisted_for_port`: a ship whose OPR is listed only for suez; alex POST with that
    OPR and ship → 201.
  - `test_unknown_or_inactive_ship_refused`: `ship_id` 999999 or an inactive ship → 400.
  - `test_old_vessel_without_ship_still_saves_but_link_cannot_be_removed`: PUT on `alex_vessel` without `ship_id`
    → 200; after linking, PUT with `ship_id: null` → 400.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_ships` — FAIL.
- [ ] **Step 3: Implement**; the ship's OPR is passed to `listed` as an extra allowed value (add a parameter
  `also=()` to `listed`); an inactive ship stays allowed only if it is the vessel's saved one.
- [ ] **Step 4: Run** the whole suite `venv/Scripts/python.exe manage.py test sheet` — PASS (the helper keeps the
  old vessel tests green); `seed_demo` on a scratch database runs.
- [ ] **Step 5: Commit** `feat(vessels): vessels linked to ships`.

### Task 4: Billing party and Cash / On account on services

**Files:**
- Modify: `sheet/validators.py`, `sheet/views.py` (`_read_service`, `service_create`, `service_detail`),
  `sheet/serializers.py` (`service_to_dict`)
- Create: `sheet/tests_billing.py`

**Interfaces:**
- Consumes: Task 1 fields, Task 3 `Vessel.ship`.
- Produces: `validators.clean_service_billing(payload, vessel, existing=None) -> (billing: str, party: Customer |
  None)`: key `billing` absent keeps the saved value (new: `"account"`), unknown → 400 "Choose Cash or On account.";
  key `billing_party` (customer id or null) absent → saved value, or on a **new** service the vessel's ship's
  customer; an inactive customer only if it is the saved one; unknown id → 400. Service JSON gains `billing`,
  `billing_party: {"id", "name"} | None`. Both fields are tracked by `conflicts` (not `UNTRACKED`) and locked by
  `accounting.require_open` with the rest.

- [ ] **Step 1: Write the failing tests** (`tests_billing.py`):
  - `test_new_service_defaults_to_account_and_ship_customer`.
  - `test_billing_party_can_be_changed_or_emptied` (`null` → None).
  - `test_cash_saved_and_bad_value_refused` (`"credit"` → 400).
  - `test_save_without_keys_keeps_values`.
  - `test_change_raises_version_and_is_in_history`.
  - `test_closed_service_billing_locked` (accounting closed → PUT changing billing → 400 `accounting.LOCKED`).
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_billing` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet.tests_billing sheet.tests_conflicts_api sheet.tests_accounting` — PASS.
- [ ] **Step 5: Commit** `feat(services): billing party and cash or on account`.

### Task 5: Calculations columns, filters, data export

**Files:**
- Modify: `sheet/calculations.py`, `sheet/dataexport.py`
- Test: `sheet/tests_billing.py` (class `CalculationsBillingTests`), `sheet/tests_dataexport.py`

**Interfaces:**
- Consumes: Task 4 fields.
- Produces: every Calculations row gains `billing` ("account" | "cash" | None for bookings / garbage) and
  `billing_party` ({"id","name"} | None); params `billing=` comma list of `account,cash` (unknown → 400 "Unknown
  billing.", empty items ignored) — **filters service rows only, other rows kept**; `party=<customer id>` or
  `party=__none__` keeps only service rows with that party / none (unknown id → 400). The response gains
  `parties: [{"id","name"}]` (customers present in the range, by name, not narrowed by `party`). Data export
  Calculations sheet: columns "Billing party" and "Billing" (labels) after the status columns.

- [ ] **Step 1: Write the failing tests**: `test_rows_carry_billing`, `test_billing_filter_keeps_other_rows_and_refuses_junk`,
  `test_party_filter_and_parties_list`, `test_totals_follow_billing_filter`; in `tests_dataexport`
  `test_calculations_export_has_billing_columns`.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_billing sheet.tests_dataexport` — FAIL.
- [ ] **Step 3: Implement** (prefetch `services__billing_party`).
- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet` — PASS.
- [ ] **Step 5: Commit** `feat(calculations): billing columns and filters`.

### Task 6: Ships page, ship dialog, type-ahead in quick-add and the vessel form

**Files:**
- Create: `sheet/static/sheet/js/pages/ships.js`, `sheet/static/sheet/js/modals/ship.js`,
  `sheet/static/sheet/js/shipPicker.js`
- Modify: `sheet/templates/sheet/index.html` (nav item `data-page="ships"`, `#page-ships`), `router.js` (TITLES,
  load), `actions.js`, `quickAdd.js`, `modals/vessel.js`, `templates/sheet/icons.svg` + `dom.js` `ICONS` if a new
  icon, `static/sheet/css/app.css`
- Test: `sheet/tests_look.py` / `tests_frontend_safety.py` (existing, must stay green), `tools/ui_smoke_test.js` (Task 9)

**Interfaces:**
- Consumes: `/api/ships/` (Task 1), vessel `ship` / `ship_id` (Task 3), `/api/customers/` for the ship dialog's
  customer dropdown (active only, keeping the saved one).
- Produces: `shipPicker.attach(input: HTMLInputElement, { onPick(ship), onClear() })` — lists up to 10 matches from
  `GET /api/ships/?active=1&limit=10&q=` after 2+ characters (debounce 250 ms, stale responses dropped by a counter),
  each "NAME · IMO · OPR" (IMO "No IMO" when empty), last item `+ New ship "TEXT"`; ArrowUp/Down, Enter, Escape,
  click. `openShip(ship | null, { name, onSaved(ship) })` in `modals/ship.js` (fields: Name, IMO, No IMO tick box
  that disables and empties IMO, OPR from `optionChoices('opr', current, port)`, Customer, Active). Ships page:
  search, Active filter, table Name / IMO / OPR / Customer / Calls, + Ship (edit roles), row click edits (edit
  roles), Delete in the dialog for admins.
- Quick-add: picking fills `#qa-name` and `#qa-opr`, keeps `ship_id` for the POST; typing after a pick clears it;
  Enter with a highlighted item picks it and adds; with nothing highlighted opens New ship; Add without a pick opens
  New ship. Vessel form: same picker on its name box; read-only "IMO" shown beside the name.

- [ ] **Step 1:** Build the three modules and wire them; run `cd tools && npm run lint` (or `npx eslint` as in
  `npm run check`) — no errors.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_look sheet.tests_frontend_safety sheet.tests_speed` — PASS.
- [ ] **Step 3:** Start the dev server on a scratch database (CLAUDE.md steps), add a vessel through the picker and
  through + New ship in the built-in browser, light and dark; screenshot for the user.
- [ ] **Step 4: Commit** `feat(ui): ships page and ship picker`.

### Task 7: Customers page and dialog

**Files:**
- Create: `sheet/static/sheet/js/pages/customers.js`, `sheet/static/sheet/js/modals/customer.js`
- Modify: `index.html` (nav `data-page="customers"`, `#page-customers`), `router.js`, `actions.js`, `app.css`

**Interfaces:**
- Consumes: `/api/customers/` (Task 2), `constants.RATE_UNITS` sent to the page through a `json_script` tag
  (`rate-units`) read in `config.js` as `RATE_UNITS`.
- Produces: page table Name / Contacts / Ships / Active; dialog (admins edit, others read-only): Name, Notes,
  Active, contacts rows (Name, Role, Email, Phone, remove; + Contact), rates rows one per `RATE_UNITS` type with
  Amount, Currency (hidden for percent) and a unit label ("per service" / "per unit" / "per line" / "%"), linked
  ships list (click → `openShip`).

- [ ] **Step 1:** Build and wire; lint clean.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_look sheet.tests_frontend_safety` — PASS.
- [ ] **Step 3:** Check in the browser as admin and viewer (read-only); screenshot.
- [ ] **Step 4: Commit** `feat(ui): customers page`.

### Task 8: Service dialog billing and revenue fill-in; Calculations UI

**Files:**
- Create: `sheet/static/sheet/js/rates.js`
- Modify: `modals/service.js`, `pages/calculations.js`, `index.html` (Calculations filters), `tools/parsing_test.js`

**Interfaces:**
- Consumes: service `billing` / `billing_party` (Task 4), vessel `ship.customer_id` (Task 3), customers' `rates`
  (Task 2), Calculations `billing` / `party` / `parties` (Task 5).
- Produces (pure, in `rates.js`):
  - `rateFor(customer, serviceType) -> {amount, currency, unit} | null`.
  - `fillRevenue({ serviceType, rate, data, isNew, touched }) -> data` returning a new data object: `service` →
    `revenue = amount`, `revenueCurrency = currency`; `unit` → `revenue = amount × quantity` rounded to the cent
    (quantity empty → leave); `line` → each entry index not in `touched`; `percent` → `percentage` when
    `shareMode` is `"percent"`. `touched` is a Set of field keys (`"revenue"`, `"entry:3"`, `"percentage"`) the
    person typed in during this dialog — never filled. When `isNew` is false, only empty / 0 values are filled.
- Dialog: "Billing party" select (customers active + saved one, empty choice "—"), default for a new service the
  ship's customer; "Billing" select (On account / Cash) under Status; one short "Agreed rate: USD 50 per unit" line
  beside the revenue when a rate applies. Fill runs on open (new only), on billing party change, on quantity change,
  on + line.
- Calculations page: columns Billing party, Billing; Billing tick boxes (like Status, "all except"); Billing party
  dropdown from `parties` with "All" and "None"; `exportQuery()` carries both.

- [ ] **Step 1: Write the failing tests** in `tools/parsing_test.js`: `fill service rate on new`, `fill unit rate
  times quantity rounds to cent`, `fill line rate skips touched entries`, `fill percent only in percent mode`,
  `fill keeps saved non-zero revenue`, `fill skips touched revenue`, `no rate leaves data unchanged`, `others has no
  rate`.
- [ ] **Step 2: Run** `cd tools && npm run test:parsing` — FAIL.
- [ ] **Step 3: Implement** `rates.js`, then the dialog and the Calculations page.
- [ ] **Step 4: Run** `cd tools && npm run test:parsing` — PASS; lint clean; `manage.py test sheet.tests_look
  sheet.tests_frontend_safety` PASS; check in the browser (new Fresh Water for MSC AURORA fills USD 50 × quantity).
- [ ] **Step 5: Commit** `feat(ui): billing on services, agreed rate fill-in, calculations filters`.

### Task 9: Smoke test, docs, full check

**Files:**
- Modify: `tools/ui_smoke_test.js`, `docs/STATUS.md`, `CLAUDE.md`, `README.md`, `SECURITY.md`

- [ ] **Step 1:** Extend the smoke test: quick-add picks MSC AURORA from the picker (`waitFor`), + New ship from the
  quick-add bar (No IMO ticked), Ships page loads, Customers page loads (admin edits a rate, viewer sees it
  read-only), a new Fresh Water service shows the filled revenue, Calculations Billing filter hides a Cash line.
- [ ] **Step 2: Run** the smoke test for alex, admin, viewer, suez on a fresh scratch database
  (`DJANGO_RATE_LIMIT_WRITES_PER_USER=300`) — all pass.
- [ ] **Step 3:** Update the docs: STATUS (where things stand, decisions: customer separate from OPR, fill-in and
  change, add ship from the vessel form for admins and port users, No IMO tick box, Cash a label with a
  Calculations filter; next: In-progress page, then accounts page), CLAUDE (architecture paragraphs for Ships /
  Customers / billing, seed_demo additions), README / SECURITY test count.
- [ ] **Step 4: Run** `cd tools && npm run check` — green.
- [ ] **Step 5: Commit** `docs: ships and customers`; then a fresh whole-branch review before asking the user to merge.
