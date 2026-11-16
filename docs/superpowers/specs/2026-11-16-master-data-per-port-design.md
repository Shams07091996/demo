# Master data per port

Date: 2026-11-16 · Size: small change · Status: draft for approval

## Why
Agents (and other Master data) showed up in every port: values an **admin** adds are always shared, because the
Master data page has no port choice, and admins' dropdowns mix every port's values. The user: **every list should
have the option to choose the port**.

## Goals
- On Master data, **every list** (OPR, POC, Agent, Hotel, Airport, Port) lets an admin choose, for each value they
  add, **one port or "All ports"**. Port users' values stay in their own port, as today.
- An admin can **change the port of an existing value** (including today's shared ones) from the Master data page.
- **Dropdowns show only what fits the item's port**: values of that port plus "All ports" values — in the vessel form,
  quick add, bulk add, and the hotel / transfer dialog (by the booking's vessel). A value already saved on a vessel or
  booking is always kept and shown, even if it doesn't match.

## Non-goals
Renaming or merging values; changing what is already saved on vessels or bookings; filters on the Vessels list.

## Approaches
| | What | Trade-off |
|---|---|---|
| **A. Use the existing `Option.port` field (chosen)** | Port picker when adding, "change port" on each value, dropdowns filtered by port in the browser | No migration; the server already stores and scopes `port` |
| B. New many-to-many "ports" per value | A value can belong to several chosen ports | Migration and a multi-select; more than was asked |

## Design
- **Adding (admin):** each list's add row gets a port select: `All ports`, Alexandria, Port Said, Damietta, Suez —
  default **All ports** *(my call: keeps today's behaviour unless chosen)*. Port users see no select (their port).
- **Changing (admin):** each value shows its port as a small select; changing it saves at once
  (`PATCH /api/options/<id>/ {port}`), admin only (port users: 403). Same value + kind + port twice → "That value
  already exists for that port."
- **Dropdowns:** `optionChoices(kind, current, port)` keeps values whose port is empty or equals `port`; callers pass
  the vessel's port (vessel form: the chosen / user's port, re-filled when an admin changes the vessel's port; quick
  add / bulk add: their port select or the user's port; booking dialog: the picked vessel's port).
- **Usage counts** stay as today ("used by N vessels / bookings").

## Testing
Backend: admin creates with a port; PATCH changes port (admin only, port user 403, duplicate 400, bad port 400).
Smoke: admin adds an agent for Suez → it is not offered on an Alexandria vessel but is on a Suez one; changing a shared
value's port moves it; port user sees no port select.
