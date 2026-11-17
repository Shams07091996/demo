# Agents per job — design

Date: 2026-11-18. Branch: `feature/agents-per-job`. First of three pieces (then dashboards, then the new look).
These three pieces come **before** two-step login (user's decision, 2026-11-18); the two-step login design
(`2026-11-17-two-step-login-design.md`) will be built afterwards in the new look.

## Why

At one port call different agents do different jobs: one agent enters the vessel, another sails it, a third does
the crew change. The company wants to record who did each job, see it, be warned when it was forgotten, and (piece 2)
count jobs per agent. Today a vessel has one `agent` field and services have none.

## Goals

- A vessel records an **Arrival agent** (who entered it) and a **Sailing agent** (who sailed it).
- Every service (all nine types) records its own **Agent**.
- All three are picked from the Master data **Agent** list, offered per port exactly like today's agent dropdown
  (`optionChoices('agent', current, port)`: that port's + All-ports values, always keeping the current one).
- A **"Missing agent" notification** for vessels whose date has passed and that miss any of them.

## Non-goals / anti-goals

- No defaults: the sailing agent is **not** copied from the arrival agent and a service's agent is **not** copied
  from the vessel — every agent stays empty until someone chooses it (user's decision; a pre-filled agent would hide
  a forgotten choice from the notification).
- No money per agent here (piece 2 counts jobs; money per agent was not asked for).
- No server check that the agent belongs to the vessel's port (same as OPR / POC / Agent today; listed as an open
  issue in STATUS).

## Data

- `Vessel.agent` is **renamed** to `Vessel.arrival_agent` (hand-written migration with `RenameField`; the user's
  PostgreSQL database has no vessels yet, but the rename keeps any data). Label "Arrival agent".
- New `Vessel.sailing_agent = CharField(max_length=100, blank=True)`. Label "Sailing agent".
- New `Service.agent = CharField(max_length=100, blank=True)` — a real column, not inside `Service.data`, so every
  service type gets it the same way. Label "Agent".
- Change history records all three automatically (concrete fields of tracked models).

## API

- Vessel JSON (`serializers.vessel_to_dict`): `arrival_agent`, `sailing_agent` replace `agent`; each service dict gains
  `agent`. Vessel create / update accept `arrival_agent` and `sailing_agent` (`validators.clean_vessel`,
  trimmed, ≤ 100 chars, may be empty). The old `agent` key is no longer accepted.
- Service create / update (`views._read_service`) read a top-level `agent` next to `type` and `data` (trimmed,
  ≤ 100, may be empty).
- Vessel list: sort keys `arrival_agent` and `sailing_agent` replace `agent`; search (`listing._matches_query`)
  matches the arrival agent, the sailing agent and every service's agent.
- CSV export: columns "Arrival agent", "Sailing agent" replace "Agent" (still through `_csv_safe`).
- Master data "used by N": an Agent value counts the vessels (in scope) that use it as arrival agent, sailing agent
  or on any of their services (each vessel once).
- `seed_demo`: give the demo vessels arrival agents, some sailing agents and some service agents, and leave at least
  one past vessel with a missing agent so the notification shows in the smoke test. MSC AURORA keeps its Crew Change
  and USD Fresh Water (the smoke test relies on them).

## Screens

- **Vessel form** (`modals/vessel.js`): "Agent" becomes two dropdowns, "Arrival agent" and "Sailing agent", both
  empty by default, both refilled for the chosen port when an admin changes the port (as today). The vessel dialog's
  port-call block shows both. Button text "Edit times & agent" → "Edit times & agents".
- **Service form** (`modals/service.js`): an "Agent" dropdown at the top of every service type's form, for the
  vessel's port, empty by default.
- **Vessel dialog service cards**: each card shows "Agent: X" (or "Agent: —").
- **Vessel list**: the Agent column becomes two columns, "Arrival agent" and "Sailing agent" (sortable).
- **Quick-add bar**: its Agent dropdown becomes "Arrival agent" and sets only that (the sailing agent stays empty).
- Empty agents show "—".

## Bulk add removed

The user no longer needs Bulk add (2026-11-18: "delete bulk add, not needed"). Removed on this branch: the sidebar
item and `#page-bulk` section, `js/pages/bulk.js`, `js/bulkParsing.js` and its tests in `tools/parsing_test.js`, the
`vessels/bulk/` and `vessels/bulk/check/` routes and views, `listing.existing_rows`, the bulk validator,
`BULK_MAX_ROWS`, bulk-only CSS, rate-limit / history code that exists only for bulk create (keep anything shared),
bulk tests, and the smoke-test steps; `CLAUDE.md`, `README.md`, `SECURITY.md` and `STATUS.md` updated (including
the open "Bulk add" issues, which go away). Vessels are added with the quick-add bar and the vessel form. `crewParsing.js`
(pasted crew) stays.

## "Missing agent" notification

- A vessel is **missing an agent** when its date is **before today** (Cairo date, `timezone.localdate()`) and its
  arrival agent is empty, or its sailing agent is empty, or any of its services has an empty agent — **every** service type, Others / Remarks included (user's decision). A vessel dated
  today or later never counts. There is no look-back limit: it stays until fixed.
- Scope: `scoped_vessels(profile, port)` like the other alerts (port users see only their port; the port filter
  applies for admins / read-only).
- `GET /api/vessels/alerts/` gains `missing_agent`: a list of `{id, name, date, missing}` (oldest first), where
  `missing` lists what is missing in order: "Arrival", "Sailing", then each service type with no agent (a type named
  once even if several such services). Only the fields needed — no money figures — so it stays light.
- Bell: the badge count adds the missing-agent vessels. Panel: a third group "Missing agent" listing all of them
  (vessel, date, what is missing); clicking one opens the vessel.
- Banner: the head line gains "N missing an agent"; the banner lists at most **20** missing-agent rows and then a
  "+ N more" button that opens the bell panel (which lists all).
- Read-only users see the notification too (they read everything); they cannot fix it.

## Approaches considered

1. **Real `agent` column on `Service`** (chosen): one place for every service type; validation, search, history,
   counting and the notification read it the same way.
2. Agent inside `Service.data` via `clean_service_data`: no column, but every type's cleaner has to carry it and is
   easy to miss.
Vessel side: rename `agent` → `arrival_agent` + new `sailing_agent` (chosen) rather than keeping `agent` and adding
two fields (three agents on a vessel would be confusing).

## Tests (test-first)

Backend: model / migration rename keeps the value; vessel and service API round-trip the agents (create, update,
empty, too long, port user); quick add sets the arrival agent only; bulk endpoints are gone (404); search matches all three; sort by both; CSV columns; usage counts;
the missing-agent rule (yesterday vs today vs tomorrow, each kind of gap, port scoping, read-only sees it); history
records the new fields. Front end: smoke test sets agents in the vessel and service forms, sees the columns and the
"Missing agent" alert. `tests_frontend_safety` unchanged.

## Left to the builder

Exact placement and wording of small labels; ordering inside the bell panel groups; how `seed_demo` names agents.
