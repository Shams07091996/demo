# Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jobs per agent, services per month and money per month on the Dashboard — charts and figures — with one
filter bar (dates, port, OPR, agent, service type) that the existing OPR charts follow too.

**Architecture:** A new `sheet/dashboard.py` builds every Dashboard figure on the server from the vessels in range
(`scoped_vessels`), each service's `finance.compute` figures and the agent fields; `listing.dashboard_response` moves
there. `GET /api/dashboard/` grows; `GET /api/dashboard/jobs/` lists one agent's jobs. The page draws its own bars with
`dom.js` (no chart library).

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-18-dashboards-design.md`

## Global Constraints

- Branch `feature/dashboards` from `main`, built in a git worktree under `.superpowers/worktrees/`; merged only when
  the user agrees.
- Job = arrival (arrival agent) / sailing (sailing agent) / each service (service agent); a Crew Change is 1 job.
- "(no agent)" = empty agent; in the query string it is `agent=__none__` (`NO_AGENT = "__none__"` in `constants.py`,
  mirrored in `config.js` via the page context).
- Month = vessel date's month; months between the first and last month with data are zero-filled.
- Money = services only (`calc.cost_egp` / `revenue_egp` / `profit_egp`), summed then rounded to the cent once;
  hotels / transport never counted.
- Service-type filter hides arrivals and sailings (columns hidden too); agent / service filters narrow the OPR charts
  and cards to the counted services; with neither, the OPR figures are exactly today's.
- Port users pinned to their port (`scoped_vessels`); every role may read.
- Charts with `dom.js` only; no library; `npm run check` green; LF endings.

## Review Focus

- Vessel with an OPR but no services, no filters → still counted in "Vessels per OPR" (today's behaviour) — Task 1.
- Agent filter = an agent that only *sailed* a vessel → that vessel counts in the OPR vessel chart, with 0 services and
  0 money — Task 1.
- `service=` an unknown type → 400; `agent=__none__` → jobs with empty agents only — Task 1.
- A date range with no vessels → every list empty, totals 0, no crash in the page ("No data.") — Tasks 1 and 3.
- Agent names with markup (`<b>A</b>`) in the agents table, the chart labels and the jobs dialog show literally —
  Task 3 smoke step.

---

### Task 1: Dashboard figures on the server

**Files:** Create `sheet/dashboard.py`, `sheet/tests_dashboard.py`; Modify `sheet/views.py` (`dashboard` →
`dashboard.response`, new `dashboard_jobs`), `sheet/urls.py` (`api/dashboard/jobs/`), `sheet/constants.py` (`NO_AGENT`),
`sheet/listing.py` (remove `dashboard_response`; keep `_service_counts` importable or move it), `sheet/views.py`
`index` context (`no_agent` value for the page).

**Interfaces — Produces:**
- `dashboard.parse(params) -> Filters` (`date_from`, `date_to`, `port`, `opr`, `agent: str | None` — `""` means no
  agent, `None` all —, `service: str | None`); 400 on bad dates, from > to, unknown service.
- `dashboard.response(profile, params) -> dict` with keys `count`, `oprs` (as today: `opr, vessels, services, cost_egp,
  profit_egp, service_counts`), `filters: {oprs, agents}`, `service_types`, `agents: [{agent, arrivals, sailings,
  by_type, total}]`, `months: [{month: "YYYY-MM", by_type, total, cost_egp, revenue_egp, profit_egp}]`,
  `totals: {jobs, services, cost_egp, revenue_egp, profit_egp}`.
- `dashboard.jobs_response(profile, params) -> {"jobs": [{vessel_id, vessel, date, job}], "truncated": bool}`; `agent`
  param required (400 without); newest vessel date first, at most 500.

- [ ] **Step 1: Failing tests** (`tests_dashboard.DashboardFigureTests`, fixtures in November 2026, Alexandria + Suez):
  - `test_jobs_per_agent`: V1 arrival DELTA, sailing NILE, Crew Change (agent DELTA, 3 crew), Fresh Water (no agent);
    V2 arrival DELTA → agents == DELTA {arrivals 2, sailings 0, by_type {"Crew Change": 1}, total 3},
    NILE {sailings 1, total 1}, "" {sailings 1 (V2), by_type {"Fresh Water": 1}, total 2}; order DELTA, "" last.
  - `test_months_zero_filled_and_money`: services in Sep and Nov 2026 → months `["2026-09","2026-10","2026-11"]`,
    Oct all zero; each month's cost / revenue / profit equals the sum of `vessel_to_dict` service `calc`s; totals match.
  - `test_bookings_are_not_counted` (a HotelStay with money changes nothing).
  - `test_service_filter_hides_arrivals_and_narrows_opr` (`service=Fresh Water`: agents rows have arrivals 0 / sailings
    0, `service_types == ["Fresh Water"]`, OPR `services`, `cost_egp` only Fresh Water).
  - `test_agent_filter` (`agent=NILE`: only NILE's jobs; OPR vessel count 1 with services 0, cost 0) and
    `agent=__none__`.
  - `test_opr_filter` and `test_no_filter_opr_figures_unchanged` (vessel without services still counted).
  - `test_filters_lists_present_values` (`filters.oprs`, `filters.agents` from range + port, not narrowed by
    opr / agent / service).
  - `test_port_user_pinned`, `test_read_only_allowed`, `test_bad_service_400`, `test_empty_range`.
  - `test_jobs_endpoint` (DELTA → 3 jobs newest first with job labels "Arrival" / "Crew Change"; no `agent` → 400;
    port user only own port; 501 jobs → 500 + `truncated`).
- [ ] **Step 2:** `python manage.py test sheet.tests_dashboard` → FAIL (module missing).
- [ ] **Step 3:** Implement. One pass over `scoped_vessels(...).prefetch_related("services")` in range / port / OPR;
  per vessel build its job list `[(kind, agent, service_or_None)]`, apply the agent / service filter, then aggregate.
  Reuse `serializers.month_rates` + `finance.compute` per service; `_service_counts` logic for OPR cards over the kept
  services. Existing `tests_listing.DashboardTests` keep passing unchanged.
- [ ] **Step 4:** `python manage.py test sheet` → PASS.
- [ ] **Step 5:** Commit `feat: dashboard figures per agent and per month on the server`.

### Task 2: Filter bar and data loading

**Files:** Modify `sheet/templates/sheet/index.html` (Dashboard toolbar: `#d-port` (hidden unless `me.seesAll`),
`#d-opr`, `#d-agent`, `#d-service` selects; new panels `#chart-agents`, `#chart-months`, figure tables `#tbl-agents`,
`#tbl-months`, `#tbl-money`, above the OPR panels), `js/config.js` (`NO_AGENT` from page context),
`js/state.js` (`dashboardFilter: {opr: '', agent: '', service: ''}`, `dashboard` default gains the new keys),
`js/data.js` (`loadDashboard` sends from / to / port + non-empty dashboard filters; `setDashboardFilter(patch)`),
`js/main.js` (change listeners: `#d-port` → `setFilter({port})`, others → `setDashboardFilter`).

**Interfaces — Produces:** `setDashboardFilter(patch) -> Promise`; `state.dashboard` shaped as Task 1's response.

- [ ] Smoke steps first (Task 3 holds them); this task is checked by Task 3's run. Commit
  `feat: dashboard filter bar`.

### Task 3: Charts, tables, jobs dialog

**Files:** Modify `js/render/dashboard.js` (`renderFilters`, `renderAgentChart` horizontal bars busiest first,
`renderMonthChart` stacked columns + legend, `renderAgentTable`, `renderMonthTable`, `renderMoneyTable`; OPR parts
unchanged), `js/actions.js` (`'agent-jobs'` → `openAgentJobs(agent)`), new `js/modals/agentJobs.js` (fetch
`/api/dashboard/jobs/`, list vessel / date / job; a row opens the vessel; "Showing the newest 500" when truncated),
`sheet/static/sheet/app.css` (`.hbar`, `.stack-col`, `.legend`, `.fig-table`, `tr.total`, `.neg`),
`tools/ui_smoke_test.js`.

Values: month label `Sep 2026` from a fixed English month list (not the locale); one colour per service type =
`CHART_COLORS[TYPES.indexOf(type) % CHART_COLORS.length]`; "(no agent)" row last, class `no-agent` (danger colour);
negative profit class `neg`; money with `fmt`.

- [ ] **Step 1: Smoke expectations** (all roles; seed data: DELTA SHIPPING / NILE AGENCY, today's month):
  `#tbl-agents` has a "DELTA SHIPPING" row and a "(no agent)" row last; header has "Arrivals" and "Sailings";
  `#tbl-months` has a Total row; `#tbl-money` rows are Cost, Revenue, Profit; choosing `#d-service` = "Fresh Water"
  hides "Arrivals" (waitFor) and resets; choosing `#d-agent` = "DELTA SHIPPING" leaves one agent row; clicking the
  DELTA row opens a dialog listing "MSC AURORA"; a vessel created with arrival agent `<b>A</b>` shows literally in the
  table and dialog (`noMarkup`); an empty range (`2000-01-01`–`2000-01-31`) shows "No data." in each panel.
- [ ] **Step 2:** Run the smoke test (fresh DB, CLAUDE.md recipe) → those checks FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Smoke PASS for alex / admin / viewer / suez; `npm run check` green.
- [ ] **Step 5:** Commit `feat: jobs per agent, services and money per month on the Dashboard`.

### Task 4: Docs

- [ ] `CLAUDE.md` (Dashboard paragraph: `dashboard.py`), `README.md` (Dashboard row; test count), `SECURITY.md` (test
  count), `docs/STATUS.md` (built row, branch state, Next). Commit `docs: dashboards`.
