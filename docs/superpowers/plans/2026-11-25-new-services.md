# New services — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suez Canal Transit, Surveyors Attendance, Supply, SIM Cards, Tourism Tours as single-priced services with
their own detail fields; Reference / Beneficiary on Cash to Master.

**Architecture:** One field table `constants.SERVICE_FIELDS` drives cleaning (`validators`), money line labels
(`finance`), and the browser (sent as `json_script` `service-fields-data`, read in `config.js`, used by the service
form, card and Summary). Replaces `SINGLE_EXTRAS` / `SINGLE_EXTRA`.

**Tech Stack:** Django 5.2, vanilla ES modules (`dom.js`), no new libraries.

**Spec:** `docs/superpowers/specs/2026-11-25-new-services-design.md`

## Global Constraints

- Refused, never fixed; messages name the field's label. Detail fields are not money.
- Existing keys stay: `patientName`, `certName`, `quantity` (no data migration).
- `dom.js` only, no inline `style=` in new code, `hidden` to show / hide. LF endings. `npm run check` green.

## Review Focus

- A user without `money.edit` editing a Cash to Master: Reference / Beneficiary show and save, money kept (Task 1 test).
- Old Medical / Certificates / Fresh Water services keep their label and value (Task 1 test).
- A datetime typed with seconds or an offset is refused, not cut (Task 1 test).
- A choice value outside the list (Direction "East") is refused (Task 1 test).
- SIM Cards with an agreed per-card rate fills revenue = cards × rate (Task 2 smoke / parsing check).

---

### Task 1: Field table, cleaning, labels (backend)

**Files:** Modify `sheet/constants.py`, `sheet/validators.py`, `sheet/finance.py`, `sheet/views.py` (index context),
`sheet/templates/sheet/index.html` (json_script); Test new `sheet/tests_service_fields.py`.

**Produces:** `SERVICE_FIELDS: dict[str, dict]` = `{type: {"fields": [{"key", "label", "kind", "max"?, "choices"?}],
"label": key | None, "suffix": str, "cost_label"?: str, "cost_currency"?: str}}` for the eight types with fields
(the five new, Medical Treatment, Certificates, Fresh Water, Cash to Master). Kinds `text` / `number` / `date` /
`datetime` / `choice`. `validators._clean_details(service_type, raw) -> dict` (every field key present, "" or None
when empty). Index context `service_fields` → `{{ service_fields|json_script:"service-fields-data" }}`.

- [ ] Tests: each new type cleans its fields; unknown key dropped; refusals: text over max ("Names is too long"),
  number "abc" / -1, date "20.11.2026", datetime "2026-11-20T10:00:00" and "…+02:00", choice "East"; old
  `{"patientName": "A"}` / `{"certName": "B"}` / `{"quantity": 5}` still cleaned the same; `finance.service_lines`
  labels: "Suez Canal Transit · Northbound", "Surveyors Attendance · 3 people", "SIM Cards · 5 cards",
  "Fresh Water · 5 t", "Medical Treatment · A"; Cash to Master keeps reference / beneficiary and its money;
  a no-`money.edit` user PUTs a Cash to Master with reference only → 200, money unchanged; `RATE_UNITS["SIM Cards"]
  == "unit"`; index page carries `service-fields-data`.
- [ ] Run → fail. Implement. Run `python manage.py test sheet` → all pass (fix any old test messages that named
  "Name" / "Quantity"). Commit.

### Task 2: Screens from the table (front end)

**Files:** Modify `sheet/static/sheet/js/config.js` (`SERVICE_FIELDS`), `js/modals/service.js` (form: detail fields
for single types and Cash to Master, shown even without money.edit; Suez cost label / USD), `js/modals/vessel.js`
(card text), `js/modals/summary.js` (Summary lines), `tools/ui_smoke_test.js`.

- [ ] Form: fields two per row (`row two`), `choice` → select with "—", `date` / `datetime` → `date` /
  `datetime-local` inputs, `number` → `numberInput`, `text` → input with maxlength. Card / Summary: filled fields
  "Label: value", dates dd.mm.yyyy, datetimes dd.mm.yyyy HH:MM.
- [ ] Smoke (alex): add Suez Canal Transit (Direction Northbound, canal entry, SCA charges 1000 USD), save, card
  shows "Direction: Northbound", Summary lists it; Cash to Master shows Reference.
- [ ] `npm run check`, smoke alex / admin / marine on a fresh database. Commit.

### Task 3: Docs

- [ ] STATUS, CLAUDE.md (service data / table), README / SECURITY counts. Commit.
