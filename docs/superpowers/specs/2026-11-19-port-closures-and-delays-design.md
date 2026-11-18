# Port closures, delay reason and missing-details alert — design

Date: 2026-11-19. Branch: `feature/port-closures-delays`.

## Intent

The user's words: "i want to add a page for port closure and if arrival date and berthing date is delayed by more
than 2 hrs want to choose the reason (the reason i will choose from master data) and a notification if a vessel date
has passed and no one put the dates in the vessel and if it is missing arrival by and sailed by".

The company wants a complete record of each port call: when each port was shut (weather and so on), why a vessel
waited for its berth, and no past port call left with gaps. The app is being sold to the company, so the usual
security rules apply in full.

## Decisions the user made

1. **Port closures are a separate record.** They are not linked to vessels or delays. When a closure held a vessel
   up, the agent simply picks a delay reason such as "Port closed".
2. A closure's reason comes from **its own Master data list, "Closure reason"**. It is separate from "Delay reason".
3. **Delayed** means Berthed is more than 2 hours after Arrived.
4. A delayed vessel **cannot be saved without a delay reason**: the save is refused with a message (option A).
5. Once a vessel's date has passed, the alert requires **all five times**: Arrived, Berthed, Ops started,
   Ops finished, Sailed.
6. **Closures get a page of their own** in the sidebar (1A). The past-vessel alert becomes **one group,
   "Missing details"**, with one line per vessel that lists everything it lacks (2A).
7. Proposed in the conversation and not objected to:
   - A closure holds port, closed from (required), reopened at (empty = still closed), reason (Closure reason list)
     and notes (optional).
   - Port users add, edit and delete only their own port's closures; admins do this for all ports; read-only users
     see every port and change nothing.
   - The page is a table with From–To and port filters, newest first, **+ Add**, and a click on a row to edit.
   - The delay reason dropdown appears in the vessel form only when needed. The app never clears a reason by itself.

## Goals

- A **Port closures** page (sidebar, between Transport and Calculations), with change history.
- A **Delay reason** on each vessel: required when delayed, refused when not delayed.
- Two new Master data lists, **Delay reason** and **Closure reason**, per port like the others, with "used by N"
  counts.
- The **Missing details** alert: past vessels missing any of the 5 times, a needed delay reason (vessels saved
  before this change), the arrival / sailing agent, or a service agent.

## Non-goals

- No link between closures and vessels: no automatic delay reason, no "closed during the call" marker.
- No closure figures on the Dashboard or Calculations, and no CSV of closures.
- No overlap check between closures of the same port. Two closures may overlap, for example fog followed by a
  strike.
- No change to how the times themselves are entered. They stay optional while the vessel is current or upcoming,
  and the existing order rules stay.
- Nothing is backfilled. Old delayed vessels keep an empty reason until someone edits them.

## Anti-goals (a failure even if it works)

- The app filling in or wiping a reason by itself (silent fixing).
- A port user seeing or changing another port's closures, or using another port's list values.
- Help text, placeholders or stat cards on the new page.
- HTML strings, emoji, or anything that breaks the CSP / `dom.js` rules.

## Approaches considered

- **Closures: their own page (picked)** vs a section on the Master data page. The Master data page is for lists, and
  closures are dated events that people look up by date, like bookings.
- **Alert: one "Missing details" group (picked)** vs separate "Missing agent" and "Missing times" groups. One line
  per vessel repeats nothing and keeps the banner short (same 20-row cap with "+ N more").
- Under the hood there was one sensible way: a new `PortClosure` model, a `Vessel.delay_reason` field, two new
  `Option` kinds, and the 2-hour rule enforced in `validators.clean_vessel` (the front end only mirrors it).

## Design

### Data

- `constants.OPTION_KINDS` gains `("delay", "Delay reason")` and `("closure", "Closure reason")`. Both fit
  `Option.kind` (`max_length=10`).
- `constants.DELAY_LIMIT = timedelta(hours=2)`. Delayed means `berthing_at - arrival_at > DELAY_LIMIT`, both set.
  Exactly 2:00 is not delayed.
- `Vessel.delay_reason = CharField("Delay reason", max_length=100, blank=True)`.
- New model `PortClosure`:
  - `port`: CharField, PORTS choices, db_index.
  - `start_at`: DateTimeField, required.
  - `end_at`: DateTimeField, null (still closed).
  - `reason`: CharField(100). Required, from the "closure" list for the port.
  - `notes`: CharField(500), blank.
  - `created_at`: auto.
  - Ordering: `-start_at`, `-id`.
- One migration `0013_port_closures_and_delays`. It adds the field and the model, and alters the Option kind choices.
- `PortClosure` is added to `history.TRACKED`, and a read-only Django admin registration follows the existing pattern.

### Rules (validators.py)

`clean_vessel`, after the times are cleaned and order-checked:

- Delayed: `delay_reason = listed("delay", data.get("delay_reason"), port, existing.delay_reason)`. If the result is
  empty, refuse with **"Choose a delay reason (berthed more than 2 hours after arrival)."**
- Not delayed and a non-empty reason is sent: refuse with **"Not delayed (berthed within 2 hours): clear the delay
  reason."**
- Not delayed and empty: `""`.

Because the PUT sends the whole vessel, an old delayed vessel with no reason is refused on any edit until a reason
is picked. That is intended.

The quick-add bar sends no times, so it is never affected. Check every other caller of `clean_vessel` (for example
the summary save) for the same behaviour. A save that doesn't send `delay_reason` must not lose the stored one: if
the key is absent, treat the stored value as sent.

`clean_closure(data, profile, existing=None)`:

- Port: port users are pinned to their own port. Admins must send a known port; on edit, the existing one is the
  default.
- `start_at` is required and parsed with `_local_datetime` ("Closed from" label). `end_at` is optional
  ("Reopened" label).
- `end_at < start_at` is refused with "Reopened cannot be before closed from."
- `reason = listed("closure", …, port, existing.reason)` is required; empty → "Choose a closure reason."
- `notes = _short(…, 500, "Notes")`.
- Unknown keys are ignored, as elsewhere.

### Access

- `access.scoped_closures(profile, port=None)` mirrors `scoped_vessels`: port users get only their own port whatever
  they send, and others get the port filter if one is given.
- Writes call `require_edit`. Edits and deletes look the closure up through `scoped_closures`, so another port's id
  gives 404.
- Read-only users can GET only.

### API (all through `api.json_api`, audited with `api.audit`)

- `GET /api/closures/?from=&to=&port=` lists closures **overlapping** the range: `start_at` on or before the end of
  `to` (Cairo), and `end_at` empty or on or after the start of `from`. Empty from / to means no limit on that side.
  Newest first. Response: `{"closures": [...]}`.
- `POST /api/closures/` creates a closure.
- `PUT /api/closures/<id>/` edits it. `DELETE /api/closures/<id>/` deletes it.
- Serializer: id, port, port_label, start_at / end_at (local ISO `YYYY-MM-DDTHH:MM`, like the vessel times),
  reason, notes, hours (decimal hours to 0.1, null when still closed), can_edit.

### Master data

- The page shows the two new lists like the others, with labels "Delay reason" and "Closure reason".
- `_usage_counts`: "delay" counts visible vessels by `delay_reason`. "closure" counts visible closures
  (`scoped_closures`) by `reason`. Note that the generic loop uses the kind as the field name, and that doesn't hold
  for either new kind. The "used by" text says vessels / closures accordingly.

### Vessel form and display

- The form sits under "Port call times". A **Delay reason** select (`optionChoices("delay", current, port)`) is
  visible when the arrival / berthing inputs show a gap of more than 2 hours, **or** when the vessel already has a
  reason. It is re-checked live on input. It has no help text: the server message explains a refusal.
- `serializers.vessel_to_dict` adds `delay_reason`. The vessel summary dialog shows "Delay reason: …" next to the
  times when one is set.
- The CSV export gets a "Delay reason" column after the times.
- The vessel-list search also matches the delay reason (cheap and consistent with agents).

### Missing details alert (listing.py)

`missing_agents` becomes `missing_details(profile, port, today)`. It covers vessels dated before today (Cairo), with
no look-back limit, oldest first. The filter gets cheaper by asking the database only for vessels with a gap: any
time null, or an empty agent, or an empty service agent, or (arrival and berthing set and delay_reason empty, with
the 2-hour check done in Python).

`missing` is built in this order:

1. Each missing time by its label: Arrived, Berthed, Ops started, Ops finished, Sailed.
2. "Delay reason", when delayed with none.
3. "Arrival agent", "Sailing agent".
4. "<Service type> agent" for each service type without an agent, once each, in SERVICE_TYPES order.

A vessel with nothing missing is left out.

The alerts JSON key `missing_agent` is renamed to `missing`. The banner and bell show the group as **"Missing
details"**, and the head says "· N missing details". Rows look the same as today:
`name · dd.mm.yyyy · Berthed, Sailed, Sailing agent`.

### Port closures page

- A sidebar item "Port closures", a new sprite icon, and the hash `#closures`. Every role sees it.
- The filter bar has From / To (default this month, like the vessel list) and Port (admins / read-only only; port
  users see their own port only).
- The table columns are Port (for admins / read-only), Closed from, Reopened (or "Still closed"), Hours, Reason and
  Notes. A click on a row opens the dialog for anyone who may edit it. A delete button per row (icon `trash`) asks
  for confirmation.
- **+ Add** appears only for users who may edit.
- The dialog has Port (admins), Closed from and Reopened (datetime-local with "Now" buttons like the vessel times),
  Reason (`optionChoices("closure", current, port)`, changing with the port for admins) and Notes. Server errors
  show the usual way.
- The page is built only with `dom.js`. New files are `js/pages/closures.js` and `js/modals/closure.js`.

### Icon

- A new line icon is drawn in the same style as the sprite and added to `templates/sheet/icons.svg` and `dom.js`
  `ICONS`, so `tests_look` stays green. The name is the builder's choice, for example `ban` or `storm`.

### Demo data (seed_demo)

- Delay reasons for All ports: Waiting for berth, Port closed, Weather, Pilot delay, Other.
- Closure reasons for All ports: Weather, Fog, Strike, Other.
- One Alexandria closure ("Weather", yesterday 06:00 → 14:00), and one still-open Port Said closure.
- SEA BREEZE already has no times, so it shows the times in "Missing details" too. The smoke test relies on it.

## Tests (written first)

- **Validators:**
  - Delayed vessel without a reason → refused.
  - Exactly 2 hours → not delayed.
  - 2h01 with a listed reason → saved.
  - Reason from another port → refused.
  - Not delayed with a reason → refused.
  - Old saved reason kept when its list value is gone.
  - Absent key keeps the stored reason.
- **Closures:**
  - CRUD for a port user, own port only (another port's id → 404; a port sent by a port user is ignored).
  - Admin with any port.
  - Read-only user: GET only (403 on writes).
  - Reopened before closed refused, reason required and listed, notes too long refused.
  - The overlap filter on the range.
  - A history record on create / edit / delete.
- **Alert:**
  - Every missing item and its order.
  - Today's vessel not listed.
  - A complete vessel not listed.
  - An old delayed vessel without a reason listed.
  - Port scoping.
- **Master data:** both kinds accepted, and the usage counts.
- **Front end:** safety tests stay green.
- **Smoke test:**
  - The Port closures page for alex / admin / viewer (add, edit, delete for editors; no + Add for the viewer).
  - The delay reason appears and is required in the vessel form.
  - "Missing details" shown for SEA BREEZE.
  - The short suez run checks it can't see the Alexandria closure.

## Left to the builder

- (Claude's call) The times rule has no start date: it applies to every past vessel. The user's real database
  has no vessels yet, so nothing floods the alert on day one.

- The icon drawing and name; CSS for the page (reuse the bookings page classes).
- Exact wording of the empty-table text ("No closures.").
- How the smoke test drives the datetime inputs (as in the existing time tests).
