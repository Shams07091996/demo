# Dashboards: jobs per agent, services per month, money per month — design

Date: 2026-11-18. Branch: `feature/dashboards` (from `main` after `feature/agents-per-job` is merged; it needs the
agent fields). Second of three pieces.

## Why

Management wants to see **how many jobs each agent did**, and a **breakdown of services per month** — as charts
**and** as figures — filtered however they want. Money per month too, but **separate** from the counts.

## Goals

The Dashboard page (`#dashboard`) gets, in this order:

1. **One filter bar** for the whole page: From–To (the existing date range), **Port** (admins and read-only only; port
   users are pinned as everywhere), **OPR**, **Agent**, **Service type**. Each has "All". The OPR / Agent dropdowns
   offer the values that occur in the current date range and port (like the Calculations page's OPR list), always
   keeping the chosen one.
2. **Jobs per agent** — horizontal bar chart (busiest first) + figures table.
3. **Services per month** — stacked column chart (one column per month, stacked by service type, with a legend) +
   figures table.
4. **Money per month (EGP)** — figures table only: Cost, Revenue, Profit rows × month columns + Total.
5. The **existing OPR charts and OPR cards**, below, following the same filters.

The mockup approved by the user is `.superpowers/brainstorm/…/look-b-dark.html` (not committed); the tables there are
the target layout.

## Definitions

- **Job**: entering a vessel = 1 job for its arrival agent; sailing it = 1 job for its sailing agent; each service =
  1 job for that service's agent. A Crew Change is one job however many crew are on it. A vessel whose arrival
  agent is filled counts as an arrival whether or not the arrival time is filled (the vessel date is what counts).
- **(no agent)**: jobs with an empty agent are collected in a "(no agent)" row, always shown last, highlighted.
- **Month**: the **vessel date**'s month (same rule as the Calculations page). Months with no services in range are
  shown as 0 columns between the first and last month that has data (no gaps in the table).
- **Money**: each service's `calc.cost_egp` / `calc.revenue_egp` / `calc.profit_egp` (from `finance.compute`, as
  `serializers.service_to_dict` attaches them; vessels carry no revenue total, so revenue is summed from the
  services), summed per month and rounded once at the end like the other totals. **Services only**
  — hotel / transport money stays on the Calculations page (user's earlier decision). Every role that can see the
  Dashboard sees the money (read-only included, per the existing decision).

## How filters apply

- Date range and port narrow the vessels (as today, `listing.range_rows` + `scoped_vessels`).
- **OPR**: vessels with exactly that OPR.
- **Service type**: only services of that type count (in jobs, services per month, money); arrivals and sailings
  are **not** shown when a service type is chosen (they are not services) — the Arrivals / Sailings columns are hidden.
  OPR charts count vessels that have at least one such service.
- **Agent**: only jobs done by that agent count — their arrivals, sailings and services; money per month = money of
  the services that agent did. OPR charts count vessels where that agent did any job. Choosing "(no agent)" is
  allowed and means empty agent.
- **OPR charts and cards under a service-type or agent filter** (builder's call): their services count, cost and
  profit add up only the services that pass the filter (so they agree with "Money per month" on the same page);
  their vessel count is the vessels with at least one counted job. With no such filter they are exactly today's
  figures. The OPR cards keep counting Crew Change per person as "Crew Change (On)" / "(Off)" (their labels say so);
  the new panels count jobs, so a Crew Change is 1 there.

## Tables

Jobs per agent (columns): Agent · Arrivals · Sailings · one column per service type that occurs · Total. A Total row
at the bottom. Sorted by Total, highest first, "(no agent)" last. Clicking an agent row opens a dialog listing that
agent's jobs in the filters: vessel, date, job (Arrival / Sailing / service type); clicking a job opens the vessel.

Services per month: rows = service types that occur, columns = months + Total, a Total row.

Money per month: rows Cost / Revenue / Profit, columns = months + Total; negative profit shown in the danger colour;
amounts with two decimals and thousands separators (existing `fmt`).

Empty results: "No data." in each panel (as today).

## API

`GET /api/dashboard/?from&to&port&opr&agent&service` (extends `listing.dashboard_response`; same `json_api` wrapper,
read-only, every role). Unknown service type → 400. Response adds to today's `{count, oprs}`:

```
"filters": {"oprs": [...], "agents": [...]},          // dropdown values present in range + port
"service_types": [...],                                // types present after filters, in SERVICE_TYPES order
"agents": [{"agent": "Delta", "arrivals": 12, "sailings": 10, "by_type": {"Crew Change": 8}, "total": 37}, ...],
"months": [{"month": "2026-09", "by_type": {...}, "total": 24, "cost_egp": .., "revenue_egp": .., "profit_egp": ..}],
"totals": {"jobs": .., "services": .., "cost_egp": .., "revenue_egp": .., "profit_egp": ..}
```
`agent` in `agents` is `""` for "(no agent)". The jobs list behind an agent row comes from
`GET /api/dashboard/jobs/?…same filters…&agent=X` → `{"jobs": [{vessel_id, vessel, date, job}]}` (capped at 500,
newest first, with `truncated: true` beyond that).

## Front end

- `render/dashboard.js` grows the new panels, built only with `dom.js`. Charts are the app's own divs (no library,
  user: no third-party): horizontal bars for agents, stacked columns for months (segments sized with the existing
  `style: {height}` property approach). Series colours come from `CHART_COLORS`, one fixed colour per service type.
- The filter bar is in `index.html` (Dashboard section). The OPR / agent / service filters are the Dashboard's own
  (in `state.dashboardFilter`), **not** shared with the vessel list; From–To stays shared as today. The Dashboard
  gets its **own Port dropdown** (new; today it follows the Vessels page's `#portSelect`): it reads and sets the same
  `state.filter.port`, so both pages stay in step; hidden for port users.
- `data.loadDashboard` sends all filters; out-of-order responses dropped as today.

## Approaches considered

1. **Server counts and sums** (chosen): one place for the port rules and the money maths (`finance`), same as the
   vessel list and the Calculations page.
2. Counting in the browser from the vessel list: would need every vessel in range sent to the browser and would
   duplicate the money rules. Rejected.
Charts: own simple bars (chosen) vs a chart library (rejected: no third-party code, strict CSP).

## Tests (test-first)

Backend: job counting (arrival / sailing / per service, crew change = 1, "(no agent)"); each filter alone and
combined; service-type filter hides arrivals / sailings; month bucketing on vessel date and zero-filled gaps; money
per month equals the sum of `compute` for those services and excludes bookings; port user sees only their port even
with `port=` of another; read-only allowed; bad service type → 400; jobs endpoint and its cap. Smoke test: Dashboard
shows the three new sections for admin / alex / viewer, filters change the numbers.

## Left to the builder

Chart sizes and spacing; legend placement; the dialog's exact look; whether months show as "Sep 2026" or "09.2026"
(use "Sep 2026" like the mockup unless it clashes with existing formatting).
