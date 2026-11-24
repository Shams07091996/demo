# Access rework — design

Date: 2026-11-24. Status: written, waiting for the user's approval.

## Why

The company is changing how people get access. Instead of six fixed roles (Admin, Read-only, or exactly one of four
fixed ports) there will be:

- **Admins** — the people with full power. **Admin = superuser** (the user's decision): about 3 people, created
  by the user through `createsuperuser` / the Django admin pages, never from the app.
- **Users** — limited power, segregated by port. An Admin creates their username and gives them **one or more
  ports** and the **permissions** and **pages** their job needs.

Admins also **add ports** (ports stop being the fixed list in `constants.PORTS`) and give agents **extra ports**.
The user showed the "Create User & Manage Users" page of their prototype
(`ARKAS_EGYPT_AGENCY_V19_FINAL_INTEGRATED_TEST.html`, outside the repo) as the model: ports, a job template, and
individual permission boxes. We take its idea and look, not its code (it keeps passwords in the browser).

The app is **not live yet**: today's test accounts may be changed or lost (the user's words: deleting data is not a
problem). The four ports' existing records are kept anyway because it costs nothing.

## Goals

- Admins manage Users on the Accounts page: username, names, ports (home + extra), a template, page ticks,
  permission ticks, turn off / on.
- Admins manage the port list on a Ports page.
- Every rule is enforced on the server; screens only hide what the server would refuse.
- Every change to people, ports, permissions and pages is in the History.

## Non-goals

- Creating, changing or turning off **Admins** from the app (they stay in `createsuperuser` / the admin pages; the
  Accounts page shows them read-only, as today).
- Branch managers managing users (the prototype had it; here only Admins manage users).
- The prototype's extra fields (branch, department, job title, employee id) and its finance collection / approval
  workflow. (My call: not asked for; easy to add later.)
- Read-only role: **removed** (the accountants are going; the Open / Closed accounting switch becomes Admin-only).

## Anti-goals

- A User reaching data of a port that isn't theirs, a page that isn't ticked, or doing something not ticked — by
  any route, export, alert, search or count.
- Money reaching a person without the matching box (`money.edit` for form money, `money.view` for overviews) in
  any answer, file or document.
- Changing a template silently changing existing people.
- The app creating or editing a superuser / staff account.

## Approaches (the user picked A, built in three pieces)

- **A. The app's own tables and rules** (picked). A `Port` table (fixed key, renamable name, on / off); each
  User's ports, permissions and pages stored on their account and checked against fixed lists in the code;
  templates are constants that only fill in the boxes; every check in `access.py`; money removed where the server
  builds its answers; records keep their port key.
- **B. Django's built-in groups and permissions.** Templates as groups would stay linked (changing a group changes
  everyone in it, against "templates only fill in the boxes"), and ports / pages / money aren't Django permissions,
  so most checks would be custom anyway.
- **C. Turning every record's port into a foreign key to `Port`.** Touches every table and query for no gain over A.

**Order** (each piece designed here, planned, built, reviewed and merged on its own):
1. **Ports and the new kinds of people.**
2. **Permissions and pages.**
3. **"See money".**

---

## Piece 1 — Ports and the new kinds of people

### Ports

- New model `Port`: `key` (fixed, `[a-z0-9]{2,20}`, unique; made from the name when added: lower-case letters and
  digits only, a digit added if the key is taken), `name` (2–40 characters, unique ignoring case,
  renamable), `active` (default on), plus history tracking.
- A data migration creates `alexandria` Alexandria, `portsaid` Port Said, `damietta` Damietta, `suez` Suez.
- Every `port` field keeps holding the key. `choices=PORTS` is removed from `Vessel.port`, `PortClosure.port`,
  `DisposalPrice.port` (and the Profile role choices); `validators.py` checks a port against the `Port` table
  instead of `PORT_KEYS`. Port names for screens, receipts, exports and the Excel come from the table (one cached
  read per request, e.g. `ports.labels()`), replacing `constants.PORT_LABELS`.
- **Ports page** (sidebar, Admins only): the list (name, key, On / Off, counts of vessels and users), **+ Add port**
  (name), rename, turn off / on. No delete (my call: once a port has any record, deleting it would orphan data; an
  unused port can simply stay off).
- A **turned-off port** can't be chosen for new vessels, closures, Master data values or garbage prices, and isn't
  offered when giving people ports; existing records keep it and stay visible to whoever has that port.
- A new port starts with empty Master data and no garbage prices; its people (or an Admin) fill them in.

### The new kinds of people

- **Admin** = `user.is_superuser`. Sees every port, does everything, has every page. `Profile.is_admin` becomes
  that test. (A staff user who isn't a superuser is treated as a User; the Accounts page keeps staff read-only.)
- **User** = everyone else: a **home port** (required) and any **extra ports** (the set always includes the home
  port). They work **fully** in every one of their ports (the user's decision); the home port is only where the
  screens open and the default for a new vessel / closure / Master data value.
- Storage: `Profile.home_port` (port key) and `Profile.ports` (JSON list of keys, validated against `Port`; my call:
  a list, not a many-to-many, matching how records hold port keys). `Profile.role` is removed, and with it
  `"readonly"` and `constants.ROLES`.
- **Staff accounts that aren't superusers**: the migration clears `is_staff` on them (the app isn't live; my call),
  so the Django admin pages — which have no port, page or money checks — stay Admin-only.
- A User with **no** port can't sign in past the two-step step (blocked page "Your account has no port yet"); only
  accounts the migration turns off end up like that.
- `access.py` becomes the single source:
  - `ports_of(profile)` → every active+inactive port key for Admins, else the profile's list;
  - `scoped_vessels(profile, port)` / `scoped_closures` → Admin: all, or the asked port; User: their ports, narrowed
    to the asked port only if it is one of theirs (otherwise all of theirs — never wider);
  - `require_port(profile, key)` on every create / update that sets a port: it must be one of theirs (and active
    for new records);
  - `require_admin(profile)` (now superuser) for exchange rates, garbage prices, moving Master data values, All-ports
    Master data, the History, the accounting Open / Closed switch, accounts and ports.
- Everything that today reads `profile.port` (a single port) or `seesAll` moves to these helpers: listings,
  Services, Hotels / Transport, closures, garbage, Calculations, Dashboard, alerts, CSV / Excel / data exports,
  Master data lists (a User sees All-ports values plus their ports' values and adds values for one of their ports),
  disposal prices (Users read their ports'), the History's port column (unchanged).
- Screens: the port filter shows for anyone with more than one port, listing only their ports; port dropdowns in
  forms list only their (active) ports; `ME` gains `ports`, `homePort`, `isAdmin` (= superuser).

### Accounts page in piece 1

- The Role box becomes **Home port** (select) + **Extra ports** (ticks). Admin rows stay read-only.
- The list's Role column becomes **Ports** ("Alexandria (home), Damietta"; Admins: "Admin · all ports").
- New accounts need a home port; the rest of the page is unchanged (names, temporary password, turn off / on).

### On the day of the change (migration)

- Port-role users → Users with that home port and only that port.
- `admin`-role users who aren't superusers → Users with every current port as theirs, home Alexandria (my call).
- `readonly` users → **turned off**, no ports.
- Superusers → Admins (nothing to store).
- Existing records keep their port keys.

## Piece 2 — Permissions and pages

### The 16 permissions (fixed list in `constants.PERMISSIONS`, key → label)

| Key | Label | What it allows (in the person's ports) |
|---|---|---|
| `vessels.edit` | Add / edit vessels | create / update vessels (quick add, form) |
| `vessels.delete` | Delete vessels | delete a vessel |
| `services.edit` | Add / edit services | create / update / delete services |
| `services.cancel` | Cancel a service | save a service as Cancelled (and cancel its bookings with `bookings.edit`) |
| `services.complete` | Mark a service Completed | save a service as Completed |
| `money.view` | See money (overviews) | piece 3: vessel profit / totals, Dashboard money, money in the Excel files; needed for Calculations and Exchange rates |
| `money.edit` | Enter / edit prices and costs | piece 3: see and type the money boxes in services, bookings and garbage |
| `bookings.edit` | Hotels & transport bookings | create / update / delete hotel stays and transfers |
| `customers.edit` | Customers and ships: add / edit | ships, and customers' names / contacts (rates also need `money.edit`) |
| `master.edit` | Master data | add values for their ports |
| `closures.edit` | Port closures | create / update / delete closures |
| `disposal.edit` | Garbage & sludge quantities | the disposal PUT (prices stay Admin-only) |
| `exports` | Excel / data exports | CSV, data exports, management Excel |
| `documents` | LOG letter and master receipt | both PDFs |
| `history.view` | History | the History page, limited to records of their ports |
| `accounting.close` | Close / reopen lines | the Open / Closed switch on Calculations (needs the Calculations page) |

Admins have all of them always. (The user: Calculations is a page Admins give out on purpose; whoever an
Admin chooses may also close lines, with `accounting.close`.) Without a permission the server answers 403 ("You don't have permission to …").
Changing a service's status **to or from** Cancelled needs `services.cancel`, **to or from** Completed needs
`services.complete` (my call: undoing a cancellation or reopening a Completed service is the same power as doing it;
Cancelled → Completed needs both), even inside a service edit; leaving a status unchanged needs only `services.edit`.

### The pages (fixed list `constants.PAGES`)

Vessels, Services, Hotels, Transport, Port closures, Garbage & Sludge, Calculations, Dashboard, Ships, Customers,
Master data, Exchange rates, History. (Ports and Accounts are Admin-only and never ticked.)

- **Vessels is always on** (my call: it is the home screen and where every service lives).
- An unticked page is not in the sidebar, its address lands on Vessels, and the server refuses (403) the routes
  that only serve it (e.g. `/api/calculations/`, `/api/closures/`, `/api/disposal/`, `/api/dashboard/…`,
  `/api/history/`, the page's export). Data other pages also need (e.g. Master data lists for dropdowns, ships for
  the vessel form, customers for billing) stays readable.
- **Calculations and Exchange rates require `money.view`**: without it they're forced off.
- History requires `history.view`; ticking one ticks the other (one tick in the dialog: the History page is shown
  under Pages and disabled unless `history.view`). (My call: no separate meaning for one without the other.)
- **What a User's History shows** (my call, the narrow reading): only records whose port is one of theirs; records
  with no port (ships, customers and rates, exchange rates, All-ports Master data, people, devices, remembered
  computers) stay Admin-only. History entries carry old → new values, money included, so **`history.view` requires
  `money.view`** (disabled in the dialog until it is ticked).
- **Exports and alerts follow the pages** (my call): each page's own export needs that page **and** `exports`; the
  "All data" file and the management Excel leave out the sheets / figures of pages the person doesn't have (and
  money, piece 3); alert lines about hotels / transport show only with that page.
- A ticked page without its edit permission is **read-only** there (e.g. Hotels ticked, `bookings.edit` off).

### Templates (constants; they only fill in the boxes)

| Template | Permissions | Pages (besides Vessels) |
|---|---|---|
| Marine employee | vessels.edit, services.edit, services.complete, money.edit | Services |
| Operations employee | Marine + services.cancel, customers.edit, bookings.edit | Services, Hotels, Transport, Ships, Customers |
| Branch manager | all 16 | all |
| Accounts employee | money.view, exports, history.view, accounting.close | Services, Calculations, Dashboard, Exchange rates, History |

(The prototype's Marine / Operations templates had "view financial details"; here that is `money.edit` — they type
and see a service's money — not `money.view`, the overviews, per the user.)

(Marine / Operations / Branch manager / Accounts from the user's prototype; Operations also has bookings, the user's
addition. Pages per template are my call from each job's permissions.) "Custom" = no template. The person stores
only their ticks; which template was last applied is not stored (my call).

### Storage and checks

- `Profile.permissions` and `Profile.pages`: JSON lists, cleaned against the fixed lists (unknown keys refused).
- `access.can(profile, key)` / `require(profile, key)` and `access.sees(profile, page)` / `require_page`; every
  write route calls the matching `require`, every page-only read route `require_page`; `views.index` renders only
  the allowed nav items and pages; `ME.permissions`, `ME.pages`.
- On the day piece 2 lands, every existing User gets **all permissions and all pages** (nobody loses anything).

### Accounts page in piece 2

The dialog of the user's sketch:

```
Username [ahassan ]  First [Ahmed] Last [Hassan]   Template [Operations ▾]
Ports  [x] Alexandria (home)  [ ] Port Said  [x] Damietta  [ ] Suez
Pages  [x] Vessels [x] Services [x] Hotels ... [ ] History
Can    [x] Add/edit vessels  [ ] Delete vessels  [x] See money ...
                                        [Turn off]   [Cancel] [Save]
```

Choosing a template ticks its boxes (replacing the current ticks); any box can then be changed. Boxes that need
another (Calculations / Exchange rates → `money.view`; History → `history.view` → `money.view`; `accounting.close` →
the Calculations page) are disabled until it is ticked. The list gains a short "Can" summary (e.g. "8 of 16").

## Piece 3 — money in forms and in overviews

The user's rule: **people type money as part of their work, but the overview is given out on purpose.** Two
boxes:

- **`money.edit` — Enter / edit prices and costs.** The money boxes of the forms: a service's cost / revenue (all
  types, Cash to Master's amount and share, typed exchange rates, broken-visa amounts, agreed-rate fill), a
  booking's cost / revenue, the garbage & sludge money on its page, customers' agreed rates. With it the person sees
  and types them for the records they work on. Without it those boxes are hidden, the server **never sends** them,
  and saves **keep the stored values** (absent ≠ cleared); sending them anyway is refused (403). The "money to 0 on
  Cancelled" step and the agreed-rate fill run only for people with `money.edit`. Quantities (Fresh Water tons,
  garbage m³, sludge t) are not money: always shown.
- **`money.view` — See money (overviews).** Vessel **profit and totals** (the vessel list's money columns, its
  totals row, sorting by money, the vessel page's figures), the Dashboard's money charts / cards (jobs and counts
  stay), money columns / sheets in the CSV, data exports and the management Excel, the Services page's
  Cost / Revenue / Rate "missing" tags, and the Calculations and Exchange rates pages (forced off without it).
  Without it the server never sends those figures. The master receipt (permission `documents`) prints its amounts
  only with `money.edit` (they are that service's revenue).
- One place decides what to strip (a money filter used by `serializers`, `listing`, `logistics`, `disposal`,
  `dashboard`, `report`, `dataexport`, `receipt`), so a new money field has one place to be added.

## Docs to update (each piece)

`DEPLOYMENT.md` (accounts: ports, templates, permissions, pages; the Ports page; who is an Admin), `CLAUDE.md`,
`STATUS.md`, `README.md` / `SECURITY.md` (roles section, test counts), `docs/` mentions of Read-only.

## Left to the builder

Module split (`ports.py`, `permissions.py`, changes in `access.py`), exact messages, the key-from-name rule's
details, how the label cache is invalidated, the Ports page's look, how each existing route maps to a permission /
page (from the tables above), test layout, and the smoke test changes (the smoke users' ports / permissions;
`seed_demo` gains users that exercise extra ports and a Marine employee).
