# Agents per job (and Bulk add removed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record and show an arrival agent and a sailing agent per vessel and an agent per service, warn about past
vessels with a missing agent, and remove the Bulk add page.

**Architecture:** Real columns (`Vessel.arrival_agent` renamed from `agent`, `Vessel.sailing_agent`, `Service.agent`)
validated in `validators.py`, serialised in `serializers.py`, searched / sorted in `listing.py`; the missing-agent
rule lives in `listing.alerts_response`. Front end: vessel form, service form, service cards, list columns,
port-call block, quick add, bell / banner — all built with `dom.js`.

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test.

**Spec:** `docs/superpowers/specs/2026-11-18-agents-per-job-design.md`

## Global Constraints

- Branch `feature/agents-per-job` from `main`; merged only when the user agrees.
- Agents: `CharField(max_length=100, blank=True)`, trimmed, ≤ 100 chars, may be empty; no defaults copied anywhere.
- Dropdowns use Master data kind `agent` via `optionChoicesEl('agent', current, port)`.
- Missing agent = vessel `date < timezone.localdate()` and (empty arrival agent or empty sailing agent or any service
  with empty agent — every service type, Others / Remarks included).
- Banner shows at most 20 missing-agent rows, then "+ N more" (opens the bell panel).
- No `innerHTML` etc.; screens only via `dom.js`; `npm run check` green; LF line endings.
- Change the backend test count in `README.md` and `SECURITY.md` at the end.

## Review Focus

- Whitespace-only agent (`"   "`) must count as empty (missing) — test in Task 3 (`_text` trims) and Task 4.
- A vessel dated yesterday with **no services** and both vessel agents set is **not** missing — Task 4.
- Port user calling `/api/vessels/alerts/?port=suez` sees only their own port's missing vessels — Task 4.
- Editing a vessel without sending `sailing_agent` must not wipe it? — No: the form always sends both; API treats a
  missing key as empty (same as `opr` today). Test the form sends both in the smoke test (Task 5).
- Many missing vessels (25) → banner shows 20 rows + "+ 5 more" — smoke-free unit: jsdom smoke on seeded data can't
  reach 25, so pin it in the JS by a pure helper `bannerMissingRows(list, max=20)` covered in Task 5's smoke check
  with a stubbed `state.alerts`.

---

### Task 1: Remove Bulk add

**Files:**
- Modify: `sheet/urls.py` (drop the two `api/vessels/bulk/` routes), `sheet/views.py` (drop `vessels_bulk`,
  `vessels_bulk_check`, unused imports), `sheet/validators.py` (drop `clean_bulk`, `BULK_MAX_ROWS` import),
  `sheet/listing.py` (drop `existing_rows`, `BULK_MAX_ROWS` import), `sheet/constants.py` (drop `BULK_MAX_ROWS`),
  `sheet/ratelimit.py` docstring (no "200-row bulk add"), `sheet/templates/sheet/index.html` (sidebar item
  `#nav-bulk`, `#qa-bulk` button, `#page-bulk` section), `sheet/static/sheet/js/{actions,main,router}.js` (bulk
  imports, actions, listeners, page name; `render/list.js` comment), `sheet/static/sheet/app.css` (`.bulk-*` rules),
  `tools/parsing_test.js` (bulk parser checks; keep crew parsing checks), `tools/ui_smoke_test.js` (bulk fetch hooks,
  bulk steps; sidebar counts become viewer 7, admin 8, others 7; page order without `bulk`).
- Delete: `sheet/static/sheet/js/pages/bulk.js`, `sheet/static/sheet/js/bulkParsing.js`.
- Tests: delete `tests.BulkAddTests`, `tests_listing.BulkCheckTests`, `tests_history...test_bulk_add_records_each_vessel`,
  `tests_ratelimit...test_a_bulk_add_of_200_rows_counts_once` (keep `history.record_created`: logistics uses it).

- [ ] **Step 1: Write the failing test** in `sheet/tests.py`:
```python
class BulkAddRemovedTests(ApiTestCase):
    def test_bulk_endpoints_are_gone(self):
        self.login("admin")
        for url in ("/api/vessels/bulk/", "/api/vessels/bulk/check/"):
            self.assertEqual(self.client.post(url, {}, content_type="application/json").status_code, 404)

    def test_page_has_no_bulk_add(self):
        self.login("admin")
        html = self.client.get("/").content.decode()
        self.assertNotIn("page-bulk", html)
        self.assertNotIn("nav-bulk", html)
```
(Use the helpers `ApiTestCase` already has for signing in; adapt names to them.)
- [ ] **Step 2:** `python manage.py test sheet.tests.BulkAddRemovedTests` → FAIL (405/201 and markup present).
- [ ] **Step 3:** Remove everything listed above; `grep -rni bulk sheet tools/*.js` shows only `bulk_create`
  (logistics / history) and nothing else.
- [ ] **Step 4:** `python manage.py test sheet` → PASS; `cd tools && npm run test:parsing` → ALL PASSED.
- [ ] **Step 5:** Commit `feat: remove Bulk add (not needed any more)`.

### Task 2: Model fields and migration

**Files:** Modify `sheet/models.py`; Create `sheet/migrations/0011_agents_per_job.py`; Test `sheet/tests_agents.py` (new).

**Interfaces — Produces:** `Vessel.arrival_agent`, `Vessel.sailing_agent`, `Service.agent` (all `str`, default `""`).

- [ ] **Step 1: Failing tests** (`tests_agents.AgentFieldTests`):
  `test_vessel_has_arrival_and_sailing_agent` (create with both, read back), `test_service_has_agent`,
  `test_agent_changes_are_in_history` (update `sailing_agent` "" → "DELTA" → a `ChangeRecord` whose changes show
  `sailing_agent` old "" new "DELTA"; follow `tests_history` for how records are read).
- [ ] **Step 2:** Run → FAIL (unexpected keyword `arrival_agent`).
- [ ] **Step 3:** Fields in `models.py`; hand-written migration: `RenameField("vessel", "agent", "arrival_agent")`,
  `AddField` `vessel.sailing_agent`, `AddField` `service.agent`, with `verbose_name`s "Arrival agent",
  "Sailing agent", "Agent". `DJANGO_DEBUG=1 python manage.py makemigrations sheet --check --dry-run` → "No changes".
- [ ] **Step 4:** Run → PASS (other tests referencing `agent=` still fail; fixed in Task 3).
- [ ] **Step 5:** Commit `feat: arrival / sailing agent on vessels, agent on services`.

### Task 3: API, search, sort, CSV, usage counts

**Files:** Modify `sheet/validators.py` (`clean_vessel`), `sheet/views.py` (`_read_service`, `service_create`,
`service_detail`, `export_csv`, `_usage_counts`), `sheet/serializers.py`, `sheet/listing.py` (`SORT_KEYS`,
`_matches_query`), `sheet/management/commands/seed_demo.py`, every existing test using `agent=` / `"agent"`.
Test: `sheet/tests_agents.py`.

**Interfaces — Produces (JSON):** vessel dict keys `arrival_agent`, `sailing_agent` (no `agent`); service dict key
`agent`; service payload `{type, agent, data}`; sort keys `arrival_agent`, `sailing_agent`.
`_read_service(request) -> tuple[str, str, dict]` (type, agent, data).

- [ ] **Step 1: Failing tests** (`tests_agents.AgentApiTests`):
  - `test_create_vessel_with_agents`: POST `/api/vessels/` with `arrival_agent: " DELTA "`, `sailing_agent: ""` →
    201, JSON `arrival_agent == "DELTA"`, `sailing_agent == ""`, no `"agent"` key.
  - `test_agent_too_long_is_cut_to_100` (mirror how `opr` is treated today — check `_text`; assert what it does).
  - `test_service_agent_round_trip`: POST service `{type: "Fresh Water", agent: "NILE", data: {...}}` → vessel JSON
    service `agent == "NILE"`; PUT with `agent: "  "` → `""`.
  - `test_port_user_cannot_set_agent_on_other_port_vessel` → 404 (existing scoping).
  - `test_search_matches_each_agent`: three vessels, one per agent kind (arrival / sailing / a service) → `q=` finds each.
  - `test_sort_by_sailing_agent` asc order; `test_old_sort_key_agent_is_rejected` → 400.
  - `test_csv_has_arrival_and_sailing_agent_columns` (header contains "Arrival agent", "Sailing agent", not "Agent").
  - `test_usage_counts_vessel_once_for_any_role`: agent "DELTA" as arrival on V1, sailing + service on V2, service only
    on V3 → Master data option `used == 3`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `_usage_counts`: for kind `agent`, count distinct visible vessel ids whose
  `arrival_agent`, `sailing_agent` or any `services__agent` equals the value (one query per field, union of ids per
  value in Python is fine). CSV header and row: "Arrival agent", "Sailing agent" in place of "Agent".
  `seed_demo`: arrival agents on all demo vessels; sailing agent and service agents on today's / future ones; one
  past vessel (yesterday) with an empty sailing agent and one service without agent. MSC AURORA keeps its Crew Change
  (two on-signers) and USD Fresh Water at rate 50. Update every existing test that used `agent`.
- [ ] **Step 4:** `python manage.py test sheet` → all PASS.
- [ ] **Step 5:** Commit `feat: agents in the API, search, sort, CSV and Master data usage`.

### Task 4: Missing-agent alerts (backend)

**Files:** Modify `sheet/listing.py` (`alerts_response`, new `missing_agents(profile, port) -> list[dict]`).
Test: `sheet/tests_agents.py`.

**Interfaces — Produces:** `/api/vessels/alerts/` JSON gains
`"missing_agent": [{"id": int, "name": str, "date": "YYYY-MM-DD", "missing": [str, ...]}]`, oldest date first (ties by
id); `missing` is `"Arrival"`, `"Sailing"`, then each service type lacking an agent in `SERVICE_TYPES` order, each once.

- [ ] **Step 1: Failing tests** (`tests_agents.MissingAgentTests`, freeze "today" with `mock.patch` of
  `django.utils.timezone.localdate` as other alert tests do, or use dates relative to `timezone.localdate()`):
  - yesterday, both agents set, no services → not listed;
  - yesterday, sailing empty → `missing == ["Sailing"]`;
  - yesterday, arrival `"   "` sent via API → stored `""` → listed with "Arrival";
  - yesterday, two Crew Changes and an Others / Remarks without agent → `["Crew Change", "Others / Remarks"]`;
  - today and tomorrow with everything empty → not listed;
  - a year ago → listed (no look-back limit);
  - port user `alexandria` with `?port=suez` → only Alexandria vessels; read-only sees all ports.
- [ ] **Step 2:** Run → FAIL (`KeyError: 'missing_agent'`).
- [ ] **Step 3:** Implement with one query: `scoped_vessels(profile, port).filter(date__lt=localdate())` +
  `prefetch_related("services")`, keep those with any gap; return only the four keys (no `vessel_to_dict`).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: alert for past vessels missing an agent`.

### Task 5: Front end

**Files:** Modify `sheet/templates/sheet/index.html` (list headers "Arrival agent" `data-sort="arrival_agent"`,
"Sailing agent" `data-sort="sailing_agent"`; quick-add `#qa-agent` title "Arrival agent"), `js/quickAdd.js`
(`arrival_agent: $('#qa-agent').value`), `js/modals/vessel.js` (two dropdowns named `arrival_agent` /
`sailing_agent` from kind `agent`; `onVesselFormChange` refills them; service card line "Agent: X" / "Agent: —";
button "Edit times & agents"), `js/components.js` (`portCallBlockEl`: cards "Arrival agent", "Sailing agent"),
`js/modals/service.js` (`formFields` starts with an "Agent" select `name="agent"` for the vessel's port, current =
service's agent; `readServiceForm` leaves `agent` out of `data`), `js/actions.js` (`saveService` payload
`{type, agent: $('#svc-form [name=agent]').value, data}`), `js/render/list.js` (two agent cells),
`js/render/notifications.js` (third group), `tools/ui_smoke_test.js`.

**Interfaces — Consumes:** Task 3 JSON keys; Task 4 `state.alerts.missing_agent`.
**Produces:** `bannerMissingRows(list, max = 20) -> {shown: [], more: number}` exported from `render/notifications.js`;
action `show-alerts-panel` (opens the bell panel) for the "+ N more" button.

- [ ] **Step 1: Smoke-test expectations first** (`tools/ui_smoke_test.js`), replacing the old agent checks:
  - vessel form has `[name=arrival_agent]` and `[name=sailing_agent]`, both `""` for a new vessel; hostile-text checks
    move to `arrival_agent`;
  - service form has `[name=agent]` with value `""` for a new service; saving with an agent shows "Agent: <name>" on
    the card;
  - table header contains "Arrival agent" and "Sailing agent"; row has 10 cells;
  - quick add sends `arrival_agent` (the created vessel's `sailing_agent` is `""`);
  - bell panel and banner show a "Missing agent" group for the seeded past vessel (waitFor);
  - `bannerMissingRows(Array(25).fill(x)).more === 5` and `.shown.length === 20` (import the module in jsdom as the
    script already imports page modules, or check via a stubbed `state.alerts` render).
- [ ] **Step 2:** Run the smoke test against a fresh throwaway DB (CLAUDE.md recipe) → those checks FAIL.
- [ ] **Step 3:** Implement the files above. Banner head adds `"N missing an agent"`; rows show vessel name, date
  (`dmy`), and `missing.join(', ')`, `dataset: {act: 'summary', id}` like the other rows; bell badge count adds
  `missing_agent.length`; panel lists all.
- [ ] **Step 4:** Smoke test PASS for `alex`, `admin`, `viewer`, and the short `suez` run; `cd tools && npm run check`
  green.
- [ ] **Step 5:** Commit `feat: agent dropdowns, columns and the missing-agent alert in the page`.

### Task 6: Docs

- [ ] Update `CLAUDE.md` (no bulk add; `BULK_MAX_ROWS` line gone; seed_demo note about the past vessel missing an
  agent), `README.md` / `SECURITY.md` (test count; bulk mentions), `docs/STATUS.md` (built table row, decisions:
  agents empty until chosen, every service needs an agent, bulk add removed, field encryption deferred to production;
  the "Bulk add" open issues removed; branch listed as unmerged). Commit `docs: agents per job`.
