# Master Data Per Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admins choose a port (or All ports) for every Master data value and can move existing values; every
dropdown offers only values of the item's port plus All-ports values.

**Architecture:** No model change — `Option.port` already exists ("" = all ports). Server: admins may set `port` on
create (already supported by `views.options`) and change it via a new `PATCH /api/options/<id>/`. Front end: a port
select per list on Master data, a port select per value for admins, and `optionChoices(kind, current, port)` filters.

**Tech Stack:** Django 5.2, vanilla ES modules, jsdom smoke test. Branch `feature/master-data-per-port`.

**Spec:** `docs/superpowers/specs/2026-11-16-master-data-per-port-design.md` (approved).

## Global Constraints
- Port choices: `""` (shown "All ports"), `alexandria`, `portsaid`, `damietta`, `suez`; add default **All ports**.
- Only admins choose / change ports; port users' values are always their port; port users get 403 on PATCH.
- Duplicate kind + value + port → 400 "That value already exists for that port."
- A value already saved on a vessel / booking always stays selectable in its dropdown.

## Review Focus
1. Admin changes a vessel's port in the vessel form → the OPR / POC / Agent lists refill for the new port, keeping the current values (Task 2 smoke check).
2. Booking dialog for a Suez vessel offers Suez + All-ports hotels only (Task 2 smoke check).
3. PATCH with an unknown port or by a port user (Task 1 test).

---

### Task 1: Server — change a value's port

**Files:** `sheet/views.py` (`option_delete` becomes `option_detail` handling `PATCH` and `DELETE`), `sheet/urls.py`; test `sheet/tests_options.py` (new)

- [ ] **Step 1: Failing tests**

```python
def test_admin_adds_for_a_port_and_moves_a_value(self):
    admin = self.login("admin")
    _, data = self.call(admin, "post", "/api/options/", {"kind": "agent", "value": "NILE", "port": "suez"})
    nile = next(o for o in data["options"] if o["value"] == "NILE")
    self.assertEqual(nile["port"], "suez")
    status, data = self.call(admin, "patch", f"/api/options/{nile['id']}/", {"port": ""})
    self.assertEqual((status, next(o for o in data["options"] if o["id"] == nile["id"])["port"]), (200, ""))

def test_only_admins_move_values_and_ports_are_checked(self):
    option = Option.objects.create(kind="agent", value="X", port="alexandria")
    self.assertEqual(self.call(self.login("alex"), "patch", f"/api/options/{option.id}/", {"port": ""})[0], 403)
    self.assertEqual(self.call(self.login("admin"), "patch", f"/api/options/{option.id}/", {"port": "mars"})[0], 400)
    Option.objects.create(kind="agent", value="X", port="")
    status, data = self.call(self.login("admin"), "patch", f"/api/options/{option.id}/", {"port": ""})
    self.assertEqual((status, data["error"]), (400, "That value already exists for that port."))
```

- [ ] **Step 2:** FAIL. **Step 3:** implement (`require_admin`, `IntegrityError`-safe duplicate check, audit `option.port`). **Step 4:** PASS + full suite. **Step 5:** commit.

### Task 2: Front end — port pickers and filtered dropdowns

**Files:** `js/pages/master.js`, `js/actions.js` (`add-option` sends `port` for admins; new `option-port` change handler wired in `main.js`), `js/components.js` (`optionChoices(kind, current = '', port = null)`: `null` = no filtering, otherwise keep values whose option port is `''` or `port`), callers: `modals/vessel.js` (vessel's / chosen port; refill on admin port change), `render/list.js` (`#qa-*` by `#qa-port` or `ME.port`; `#bk-*` by `#bk-port` or `ME.port`), `pages/bulk.js` (target port), `modals/booking.js` (picked vessel's port), `state.js` (`optionsFor(kind, port)`); test `tools/ui_smoke_test.js`

- [ ] **Step 1: Failing smoke checks** (admin): Master data list has `select[data-new-port="agent"]` with `,alexandria,portsaid,damietta,suez` values; add agent `SMOKE SUEZ AGENT` for Suez → the vessel form for an Alexandria vessel doesn't offer it, for a Suez vessel it does, and switching the form's port to Suez offers it; each value row has a `select[data-option-port]`, changing `SMOKE SUEZ AGENT` to All ports makes it appear on the Alexandria vessel; booking dialog for MSC AURORA (Alexandria) doesn't offer a Suez-only hotel. (alex): no port selects on Master data.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** smoke ×3 + parser + backend PASS. **Step 5:** commit; update `README.md` roles / Master data row, `docs/STATUS.md`, test counts; fresh review; merge only when the user agrees.
