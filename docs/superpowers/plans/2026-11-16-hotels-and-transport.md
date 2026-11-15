# Hotels and Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new pages, 🏨 Hotels and 🚗 Transport, where editors add bookings (one room / one car trip with 1–6
guests picked from a vessel's crew change) and everyone with access sees them by date range and port; read-only users
never see prices.

**Architecture:** New models `HotelStay`, `Transfer` and `Guest` (one table, two nullable FKs + check constraint) in
`sheet/models.py`; input cleaning in `sheet/validators.py`; list / filter / serialise logic in a new
`sheet/logistics.py` that reuses the vessel list's parameter parsing; thin views. Front end: one shared list module
(`pages/bookings.js`) configured twice, plus one dialog module (`modals/booking.js`).

**Tech Stack:** Django 5.2, SQLite (dev) / PostgreSQL (prod), vanilla ES modules (no build), jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-16-hotels-and-transport-design.md` (approved). Read `CLAUDE.md` first.

**Not a git repo:** each task ends with a checkpoint (full backend suite) instead of a commit. `DJANGO_DEBUG=1` is
needed for `makemigrations`. Write files with LF endings.

## Global Constraints

- Guests per booking: 1–6, all belonging to the booking's vessel; guest `name` required ≤120 upper-cased; `rank`,
  `nationality` ≤60; `group` in `on` / `off` / `""`; `flight` ≤20.
- `HotelStay.nights` 1–60; check-out = check-in + nights; `price_per_night` is **per room**.
- Transfer places: `airport`, `hotel`, `port`; from ≠ to; `hotel` required when either end is `hotel`, else stored `""`.
- Prices optional, ≥ 0; currency `EGP` / `USD` (anything else → `EGP`, as services); `exchange_rate` optional > 0.
- Read-only users: price, currency and exchange rate keys are **absent** from every booking JSON.
- Every query is scoped through the vessel with `access.scoped_vessels`; out-of-scope ids → 404; writes need
  `require_edit`; every change is `audit`ed.
- List params as the vessel list: `from`, `to`, `q`, `port`, `sort`, `dir`, `page`, `page_size` (1–200); default
  sort ascending (`check_in` / `at`); rows-per-page choices 10 / 25 / 50 / 100, remembered per page.
- Hotel money never enters `finance.compute`, vessel totals, Dashboard or CSV.

## Review Focus

1. **Stay edges:** a stay checking out on `from` is excluded; one checking in on `to` is included (Task 3 test).
2. **Guest lists:** empty, 7 guests, a blank name among valid ones → 400 with a clear message (Task 2 test).
3. **Transfer places:** hotel → hotel, or a hotel end with no hotel → 400 (Task 2 test).
4. **Cross-port:** a port user creating on, editing, deleting or listing another port's booking → 404 / not listed (Task 3 test).
5. **Unreadable flight text** ("TBA", "", "31 FEB 10:00") → empty pre-fill, never an error (Task 4 test).

---

### Task 1: Models, migration, Hotel master data, vessel delete wording

**Files:**
- Modify: `sheet/models.py`, `sheet/constants.py`, `sheet/views.py` (`_usage_counts`), `sheet/admin.py` (register the three models), `sheet/static/sheet/js/actions.js` (delete confirm), `tools/ui_smoke_test.js` (master data now has 4 lists)
- Create: migration `sheet/migrations/0006_hotels_and_transport.py`
- Test: `sheet/tests_logistics.py`

**Interfaces:**
- Produces: `PLACES = [("airport", "Airport"), ("hotel", "Hotel"), ("port", "Port")]`, `PLACE_KEYS`, `GUEST_GROUPS = ("on", "off", "")`, `MAX_GUESTS = 6`, `MAX_NIGHTS = 60` in `constants.py`; `OPTION_KINDS` gains `("hotel", "Hotel")`.
- Models: `HotelStay(vessel FK CASCADE related_name="hotel_stays", hotel, check_in DateField(db_index), nights PositiveSmallInteger, price_per_night Decimal(12,2) null, currency Char(3) default "EGP", exchange_rate Decimal(10,4) null, created_at)` with property `check_out -> date`; `Transfer(vessel FK CASCADE related_name="transfers", from_place, to_place, hotel, at DateTimeField(db_index), price Decimal(12,2) null, currency, exchange_rate, created_at)`; `Guest(stay FK null related_name="guests", transfer FK null related_name="guests", position PositiveSmallInteger, name, rank, nationality, group, flight)` with `Meta.ordering = ["position", "id"]` and a `CheckConstraint` "exactly one of stay / transfer".

- [ ] **Step 1: Write the failing tests** (`class ModelTests(ApiTestCase)` from `.tests`)

```python
def test_check_out_and_cascade(self):
    stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=3)
    Guest.objects.create(stay=stay, position=0, name="AHMED TEST")
    self.assertEqual(stay.check_out, date(2026, 11, 17))
    self.alex_vessel.delete()
    self.assertFalse(HotelStay.objects.exists() or Guest.objects.exists())

def test_guest_belongs_to_exactly_one_booking(self):
    with self.assertRaises(IntegrityError), transaction.atomic():
        Guest.objects.create(position=0, name="NOBODY")

def test_hotel_is_a_master_data_kind_counted_by_bookings(self):
    stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=1)
    Option.objects.create(kind="hotel", value="HILTON")
    _, data = self.call(self.login("admin"), "get", "/api/options/")
    hilton = next(o for o in data["options"] if o["kind"] == "hotel")
    self.assertEqual(hilton["used"], 1)
```

- [ ] **Step 2: Run to verify they fail** — `python manage.py test sheet.tests_logistics` → ImportError / FAIL.
- [ ] **Step 3: Implement** the constants, models, admin registrations; `_usage_counts` counts `hotel` as stays + transfers (scoped through the vessel) whose `hotel` equals the value; make the migration (`DJANGO_DEBUG=1 python manage.py makemigrations sheet -n hotels_and_transport`). Delete confirm text: `` `Delete ${vessel.name} and all of its services, hotel stays and transfers? This cannot be undone.` ``. In the smoke test change the master-data checks to `'OPR,POC,Agent,Hotel'` and `.panel` count 4.
- [ ] **Step 4: Run to verify they pass**; checkpoint `python manage.py test sheet` → all OK.

---

### Task 2: Validation

**Files:** Modify `sheet/validators.py`; Test `sheet/tests_logistics.py` (`class LogisticsValidationTests(SimpleTestCase)`)

**Interfaces:**
- Produces: `clean_guests(raw) -> list[dict]` (keys `name, rank, nationality, group, flight`), `clean_hotel_stay(data) -> dict` (keys `hotel, check_in, nights, price_per_night, currency, exchange_rate, guests`), `clean_transfer(data) -> dict` (keys `from_place, to_place, hotel, at, price, currency, exchange_rate, guests`). Input keys from the browser are snake_case as above plus `vessel` (int, handled by the view). `at` arrives as `"YYYY-MM-DDTHH:MM"` (Cairo) and reuses `_local_datetime`. Prices are returned as `Decimal` or `None`.

- [ ] **Step 1: Write the failing tests**

```python
G = [{"name": "ahmed test", "rank": "2/E", "nationality": "Egyptian", "group": "on", "flight": "TK689"}]
def stay(**o): return {"hotel": "HILTON", "check_in": "2026-11-14", "nights": 2, "guests": G, **o}
def trip(**o): return {"from_place": "airport", "to_place": "hotel", "hotel": "HILTON", "at": "2026-11-14T14:30", "guests": G, **o}

def test_guests_are_cleaned_and_limited(self):
    self.assertEqual(clean_guests(G)[0]["name"], "AHMED TEST")
    for bad in ([], G * 7, G + [{"name": "  "}], "x"):
        with self.assertRaises(BadRequest): clean_guests(bad)
    self.assertEqual(clean_guests([{"name": "X", "group": "boss"}])[0]["group"], "")

def test_stay_rules(self):
    self.assertEqual(clean_hotel_stay(stay())["nights"], 2)
    for bad in (stay(nights=0), stay(nights=61), stay(nights="two"), stay(check_in="14.11.2026"), stay(hotel=" "),
                stay(price_per_night=-1), stay(exchange_rate=0)):
        with self.assertRaises(BadRequest): clean_hotel_stay(bad)
    self.assertEqual(clean_hotel_stay(stay(price_per_night="80", currency="GBP"))["currency"], "EGP")

def test_transfer_rules(self):
    self.assertEqual(clean_transfer(trip())["hotel"], "HILTON")
    self.assertEqual(clean_transfer(trip(to_place="port", from_place="airport", hotel="HILTON"))["hotel"], "")
    for bad in (trip(to_place="airport"), trip(from_place="hotel", to_place="hotel"), trip(hotel=""),
                trip(from_place="sea"), trip(at=""), trip(at="2026-11-14"), trip(price="-5")):
        with self.assertRaises(BadRequest): clean_transfer(bad)
```

Error messages (exact): `"Add at least one guest."`, `"At most 6 guests per booking."`, `"Every guest needs a name."`, `"Nights must be a whole number from 1 to 60."`, `"Enter a valid check-in date."`, `"Choose a hotel."`, `"From and To must be different."`, `"Choose where from and where to."`, `"Enter the date and time."`, `"Prices cannot be negative."`, `"Exchange rate must be a positive number."`.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass**; checkpoint full suite.

---

### Task 3: Bookings API (list, create, edit, delete)

**Files:** Create `sheet/logistics.py`; Modify `sheet/listing.py` (rename `_date` → `date_param`, `_whole` → `int_param`, keep behaviour), `sheet/views.py`, `sheet/urls.py`; Test `sheet/tests_logistics.py` (`class BookingApiTests(ApiTestCase)`)

**Interfaces:**
- Consumes: Task 1 models, Task 2 cleaners, `listing.date_param`, `listing.int_param`.
- Produces: `logistics.KINDS = {"hotels": HotelStay, "transfers": Transfer}`; `logistics.list_response(kind, profile, params) -> dict` (`bookings, page, page_size, count, pages`); `logistics.booking_to_dict(obj, profile) -> dict`; `logistics.save_booking(kind, profile, data, existing=None) -> obj`. Routes `api/hotels/`, `api/hotels/<int:pk>/`, `api/transfers/`, `api/transfers/<int:pk>/` (names `api_hotels`, `api_hotel`, `api_transfers`, `api_transfer`) → views `bookings(request, kind)` (GET, POST) and `booking_detail(request, kind, pk)` (GET, PUT, DELETE).
- Row JSON: `id, vessel {id, name, port, port_label}, guests [..]`, plus hotels `hotel, check_in, nights, check_out` / transfers `from_place, to_place, hotel, at` (`"YYYY-MM-DDTHH:MM"` Cairo), plus — editors only — `price_per_night`/`price` (float or null), `currency`, `exchange_rate`.
- Sort keys: hotels `check_in, nights, hotel, guest, vessel`; transfers `at, from_place, to_place, guest, vessel` (`guest` = first guest's name).

- [ ] **Step 1: Write the failing tests** — fixtures: a 2-guest stay on `alex_vessel` (HILTON, 14.11, 3 nights, 80 USD), a stay on `suez_vessel`, a transfer on `alex_vessel` at 15.11 14:30.

```python
def test_stay_overlap_edges(self):
    rows = lambda **p: [b["id"] for b in self.list("admin", "hotels", **p)["bookings"]]
    self.assertIn(self.stay.id, rows(**{"from": "2026-11-16", "to": "2026-11-16"}))   # inside
    self.assertNotIn(self.stay.id, rows(**{"from": "2026-11-17", "to": "2026-11-20"}))  # checks out on `from`
    self.assertIn(self.stay.id, rows(**{"from": "2026-11-10", "to": "2026-11-14"}))  # checks in on `to`

def test_transfer_range_inclusive_and_search(self):
    self.assertEqual(self.list("admin", "transfers", **{"from": "2026-11-15", "to": "2026-11-15"})["count"], 1)
    self.assertEqual(self.list("admin", "hotels", q="ahmed")["count"], 1)       # any guest
    self.assertEqual(self.list("admin", "hotels", q="alex ship")["count"], 1)   # vessel name

def test_read_only_sees_no_prices_and_cannot_write(self):
    row = self.list("viewer", "hotels")["bookings"][0]
    self.assertFalse({"price_per_night", "currency", "exchange_rate"} & row.keys())
    self.assertEqual(self.call(self.login("viewer"), "post", "/api/hotels/", self.payload())[0], 403)

def test_port_user_is_kept_to_own_port(self):
    alex = self.login("alex")
    self.assertEqual({b["vessel"]["port"] for b in self.list("alex", "hotels", port="suez")["bookings"]}, {"alexandria"})
    self.assertEqual(self.call(alex, "post", "/api/hotels/", self.payload(vessel=self.suez_vessel.id))[0], 404)
    self.assertEqual(self.call(alex, "put", f"/api/hotels/{self.suez_stay.id}/", self.payload())[0], 404)
    self.assertEqual(self.call(alex, "delete", f"/api/hotels/{self.suez_stay.id}/")[0], 404)

def test_create_edit_delete_keeps_guest_copy(self):
    alex = self.login("alex")
    status, row = self.call(alex, "post", "/api/hotels/", self.payload())
    self.assertEqual((status, [g["name"] for g in row["guests"]]), (201, ["AHMED TEST", "ALI SAYED"]))
    Service.objects.filter(vessel=self.alex_vessel).delete()              # crew change edited away
    self.assertEqual(len(self.call(alex, "get", f"/api/hotels/{row['id']}/")[1]["guests"]), 2)
    status, row = self.call(alex, "put", f"/api/hotels/{row['id']}/", self.payload(nights=4))
    self.assertEqual((status, row["check_out"]), (200, "2026-11-18"))
    self.assertEqual(self.call(alex, "delete", f"/api/hotels/{row['id']}/")[0], 200)

def test_changing_a_bookings_vessel_is_ignored_on_edit(self):
    status, row = self.call(self.login("admin"), "put", f"/api/hotels/{self.stay.id}/", self.payload(vessel=self.suez_vessel.id))
    self.assertEqual(row["vessel"]["id"], self.alex_vessel.id)

def test_bad_list_params(self):
    for p in ({"from": "x"}, {"page": "0"}, {"sort": "price"}, {"from": "2026-12-01", "to": "2026-11-01"}):
        self.assertEqual(self.client_status("admin", "hotels", **p), 400)
```

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement** — overlap in SQL: `check_in <= to` and `check_in > from - 60 days` then exact `check_out > from` in Python (or annotate `check_out` with `ExpressionWrapper`; builder's choice). Search in Python, as `listing.py` does. Guests are replaced wholesale on edit. Audit actions `hotel.create|update|delete`, `transfer.create|update|delete`.
- [ ] **Step 4: Run to verify they pass**; checkpoint full suite.

---

### Task 4: Crew helper and flight-time pre-fill

**Files:** Modify `sheet/logistics.py`, `sheet/views.py`, `sheet/urls.py`; Test `sheet/tests_logistics.py`

**Interfaces:**
- Produces: `logistics.parse_flight_time(text: str, segment_date: str, near: date) -> datetime | None` (Cairo-aware); `logistics.crew_of(vessel) -> list[dict]` (`group, name, rank, nationality, flight, arrival, departure`, times as `"YYYY-MM-DDTHH:MM"` or `""`); route `api/vessels/<int:pk>/crew/` (name `api_vessel_crew`, GET, scoped, readable by every role).
- Leg choice: on-signers → **last** segment (`arrival` from its `arrivalTime`); off-signers → **first** segment (`departure` from its `departureTime`). Year: the one that puts the date nearest the vessel date.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_flight_time(self):
    near = date(2026, 11, 13)
    self.assertEqual(parse_flight_time("13 NOV 10:00", "", near).strftime("%Y-%m-%d %H:%M"), "2026-11-13 10:00")
    self.assertEqual(parse_flight_time("02 JAN 06:15", "", date(2026, 12, 30)).year, 2027)   # nearest year
    for text in ("TBA", "", "31 FEB 10:00", "10:00"):
        self.assertIsNone(parse_flight_time(text, "", near))

def test_crew_helper_lists_on_and_off_signers_with_the_right_leg(self):
    # Crew Change on alex_vessel: on-signer with two segments (IST→CAI then CAI→HBE), off-signer with one
    data = self.call(self.login("viewer"), "get", f"/api/vessels/{self.alex_vessel.id}/crew/")[1]
    on, off = data["crew"]
    self.assertEqual((on["group"], on["flight"], on["arrival"][:10]), ("on", "MS 123", "2026-11-13"))
    self.assertEqual((off["group"], off["departure"][11:]), ("off", "05:00"))
    self.assertEqual(self.call(self.login("suezuser"), "get", f"/api/vessels/{self.alex_vessel.id}/crew/")[0], 404)
```

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass**; checkpoint full suite.

---

### Task 5: The two list pages

**Files:** Create `sheet/static/sheet/js/pages/bookings.js`; Modify `index.html` (two nav items between Bulk add and Dashboard, two `<main class="page">` sections with ids `page-hotels` / `page-transport`), `router.js` (`TITLES.hotels = 'Hotels'`, `TITLES.transport = 'Transport'`), `main.js`, `actions.js`, `app.css`; Test `tools/ui_smoke_test.js`

**Interfaces:**
- Produces: `createBookingsPage(config) -> { load(), render(), setFilter(patch) }` where `config = { kind: 'hotels'|'transfers', root: '#page-hotels', columns: [...], storageKey: 'sheet.hotels.pageSize' }`; exported instances `hotelsPage`, `transportPage`; `router.showPage` calls `.load()`. Element ids inside each section are prefixed `h-` / `t-` (`h-from`, `h-to`, `h-search`, `h-port`, `h-pager`, `h-tbody`, `h-add`). Rows `tr[data-booking]`; editors' row click → `openBookingDialog(kind, id)` (Task 6).
- Reuse `render/pager.js` by giving `renderPager` a `(container, list, pageSize)` signature (update its single existing caller).

- [ ] **Step 1: Write the failing smoke checks** (all roles) — sidebar has 7 pages (6 for viewer); `#page-hotels` / `#page-transport` render a table with headers `Check-in, Nights, Check-out, Hotel, Guests, Vessel` (+ `Price/night` for editors) and `Date & time, From → To, Guests, Flight, Vessel` (+ `Price`); viewer: no `#h-add`, no price header; date range defaults to this month; rows-per-page choices `10,25,50,100`.
- [ ] **Step 2: Run** (`node ui_smoke_test.js alex|admin|viewer` against the throwaway DB, see `CLAUDE.md`) → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS for all roles; checkpoint backend suite.

---

### Task 6: Add / edit dialog

**Files:** Create `sheet/static/sheet/js/modals/booking.js`; Modify `actions.js`; Test `tools/ui_smoke_test.js`

**Interfaces:**
- Consumes: Task 3 API, Task 4 crew helper, `optionChoices('hotel', current)`.
- Produces: `openBookingDialog(kind, id = null)`; actions `booking-save`, `booking-delete`, `booking-add-guest`, `booking-del-guest`.
- Vessel search: input `#bk-vessel-q` → `GET /api/vessels/?q=…&page_size=10` (no date range), results as buttons `data-act="booking-pick-vessel"`; picking loads `/api/vessels/<id>/crew/` into a checklist (`input[type=checkbox][data-crew-i]`); checking adds an editable guest line; "+ Other guest" adds an empty line. Pre-fill: hotels `check_in` from the first ticked on-signer's `arrival` date; transfers `at` from the first ticked guest's `arrival` (on) / `departure` (off) and `hotel` from a stay on the same vessel containing that guest's name (from `GET /api/hotels/?q=<name>`). Exchange-rate field visible only when USD.

- [ ] **Step 1: Write the failing smoke checks** (alex and admin) — open "+ Add hotel stay", search `MSC`, pick the vessel, tick two crew, pick a hotel, 2 nights, price 80 USD → save → the Hotels list shows one row with both names and `USD 80.00`; open it, change nights to 3, save → check-out moves; "+ Add transfer" with one guest, Airport → Hotel, hotel pre-filled, save → listed as `Airport → Hotel (…)`; delete both; a save with no guest shows `Add at least one guest.` in the dialog. (Seed a Crew Change with two on-signers in `seed_demo` so the throwaway DB has crew.)
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run all roles** → PASS; parser tests and backend suite green.

---

### Task 7: Docs

**Files:** `README.md` (Pages table rows for Hotels and Transport, roles note: prices hidden from read-only, test count), `SECURITY.md` (test count; A01 line mentions bookings scoped through their vessel), `CLAUDE.md` (Architecture: `logistics.py`, the `Guest` table, `pages/bookings.js`).

- [ ] **Step 1:** Update; **Step 2:** final full run: backend suite, `npm run test:parsing`, smoke test ×3 roles.
