# Master Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Receipt button on each service opens a pre-filled, editable form; Download returns a PDF "WHOM IT MAY CONCERN" receipt (logo + footer, no stamp) for the master to sign.

**Architecture:** `logpdf.py` gets a second document body (`build_receipt`) on the same layout / PDF writer as the LOG letter. A new view `service_receipt` at `/api/services/<id>/receipt/`: GET returns the pre-filled fields (JSON), POST takes the edited fields and returns the PDF. The front end adds a button on each service card and a dialog `js/modals/receipt.js`; the download reuses the LOG's fetch → blob → link pattern.

**Tech Stack:** Django 5.2, Python standard library only for the PDF, vanilla ES modules built with `dom.js`.

**Spec:** `docs/superpowers/specs/2026-11-20-master-receipt-design.md`

## Global Constraints

- No PDF library; reuse `logpdf.py` (WinAnsi, raw JPEGs). **No stamp** on the receipt; logo and footer as on the LOG.
- Edit roles only (`require_edit`), vessel through `access.scoped_vessels`, rate limited with `ratelimit.check(request, "export")`.
- Input cleaned only in `validators.py`; too long is refused with a message, never cut.
- Nothing typed is stored. The download is recorded in the History with action `receipt`.
- Front end: `dom.js` only (no `innerHTML`, no inline styles), every button `data-act`, no help text / placeholders (user's taste).
- Files LF; `npm run check` green before merge; README / SECURITY test counts updated.

## Review Focus

- Services text long enough to cross a page → a second page with the logo and footer, the signature lines after the text (Task 1 test).
- Text containing `(`, `)`, `\`, `{{ }}`, Arabic → escaped / `?`, never a PDF operator (Task 1 test).
- A port user asking for another port's service → 404; a read-only user → 403 and no button (Task 2 tests, Task 3 smoke).
- A service with no revenue, revenue 0, or several entries in two currencies → sensible pre-fill (Task 2 tests).
- An empty or whitespace-only Services box → refused "Write the services." (Task 2 test).

---

### Task 1: The receipt PDF

**Files:**
- Modify: `sheet/logpdf.py`
- Test: `sheet/tests_logpdf.py` (new class `ReceiptPdfTests`)

**Interfaces:**
- Produces: `logpdf.build_receipt(fields: dict, images: dict) -> bytes`; `fields` keys `port`, `date`, `vessel`, `services` (plain text, may hold line breaks). `images` as for `build`; a `stamp` passed in is **ignored**.

- [ ] **Step 1: Write the failing tests** (reuse `tiny_jpeg`, `page_count`, `page_contents`)

```python
RECEIPT = {"port": "Alexandria", "date": "20/11/2026", "vessel": "MSC AURORA",
           "services": "Arrange 5 shore pass with cost $50\nLanding with cost $120"}

def test_receipt_text(self):
    pdf = logpdf.build_receipt(RECEIPT, {})
    for text in (b"(Alexandria: 20/11/2026)", b"(MV/ MSC AURORA)", b"(WHOM IT MAY CONCERN)",
                 b"(Arrange 5 shore pass with cost $50)", b"(Landing with cost $120)", b"(Master)", b"(Ship's stamp)"):
        self.assertIn(text, pdf)
    self.assertIn(b"master of m/v MSC AURORA", pdf)
    self.assertIn(b"ARKAS EGYPT SAE", pdf)
    self.assertNotIn(b"{{", pdf)

def test_receipt_has_logo_and_footer_but_no_stamp(self):
    jpeg = tiny_jpeg()
    pdf = logpdf.build_receipt(RECEIPT, {"logo": jpeg, "stamp": jpeg, "footer": jpeg})
    self.assertIn(b"/Im1 Do", pdf); self.assertIn(b"/Im3 Do", pdf)
    self.assertNotIn(b"/Im2", pdf)  # neither drawn nor embedded
    self.assertEqual(pdf.count(b"/Filter /DCTDecode"), 2)

def test_receipt_long_services_add_page_signature_after_text(self):
    services = "\n".join(f"Service line {i} with cost $10" for i in range(120))
    pdf = logpdf.build_receipt({**RECEIPT, "services": services}, {"logo": tiny_jpeg()})
    self.assertGreaterEqual(page_count(pdf), 2)
    last = page_contents(pdf)[-1]
    self.assertIn(b"(Master)", last)
    self.assertLess(last.index(b"(Service line 119 with cost $10)"), last.index(b"(Master)"))

def test_receipt_text_escaped(self):
    pdf = logpdf.build_receipt({**RECEIPT, "services": "a(b)c\\d {{x}} عربي"}, {})
    self.assertIn(b"(a\\(b\\)c\\\\d {{x}} ????)", pdf)
```

- [ ] **Step 2: Run to see them fail** — `venv/Scripts/python.exe manage.py test sheet.tests_logpdf` → AttributeError `build_receipt`.

- [ ] **Step 3: Implement.** Move the object-writing half of `build` into `_pdf(layout, pictures) -> bytes`; `build` keeps its signature. Add `_receipt(layout, fields)` and `build_receipt`, which drops `stamp` from the images before making the layout. Layout (Helvetica 11 unless said): `"{port}: {date}"` bold; `"MV/ {vessel}"` bold; gap 24; `WHOM IT MAY CONCERN` bold 12, centred; gap 18; the sentence `I, the undersigned master of m/v {vessel} declare the following services have been rendered from Messrs ARKAS EGYPT SAE` wrapped; gap 10; the services with `layout.block(services, "F1", 11)`-style line breaks kept (add a `font` / `size` use, not Courier); gap 40; `Master` bold; gap 70; `Ship's stamp` bold. Use `layout.room` so a signature label never sits alone at a page bottom (keep `Master` + 70pt together).

- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet.tests_logpdf` → all pass (the LOG tests unchanged).

- [ ] **Step 5: Commit** `feat(receipt): the master receipt PDF`

### Task 2: The receipt endpoint

**Files:**
- Create: `sheet/receipt.py` (pre-fill text), `sheet/migrations/0017_history_receipt.py`, `sheet/tests_receipt.py`
- Modify: `sheet/validators.py` (`clean_receipt`), `sheet/views.py` (`service_receipt`), `sheet/urls.py`, `sheet/models.py` (`ChangeRecord.ACTIONS` + `("receipt", "Receipt made")`, `action` `max_length=7`), `sheet/static/sheet/js/pages/history.js` (`ACTION_LABEL.receipt = 'Receipt made for'`, shown like `letter`)

**Interfaces:**
- Consumes: `logpdf.build_receipt`, `views._letterhead_images`, `views._file_name_part`.
- Produces: `receipt.prefill(service) -> dict` with `port` (port label), `date` (`timezone.localdate()` DD/MM/YYYY), `vessel`, `services` (one line). `validators.clean_receipt(raw) -> dict` (same four keys). Route `api/services/<int:pk>/receipt/` name `api_service_receipt`: GET → `{"receipt": prefill}`; POST → PDF, `Content-Disposition: attachment; filename="Receipt <vessel> <YYYY-MM-DD>.pdf"`, `X-Content-Type-Options: nosniff`.

Pre-fill line: `{label} with cost {amounts}`; `label` is the service type, or for Others / Remarks its note (first line, else the type). `amounts` = the service's **revenue** in its own currency: single-priced and Crew Change `revenue` / `revenueCurrency`; Delivery Parcels / Courier / Landing the sum of the entries' revenue per currency; Cash to Master the share as `finance._cash_to_master` works it out (reuse, don't copy). USD → `$120`, EGP → `EGP 2,500`; whole numbers without decimals, else 2 decimals; thousands with commas; two currencies joined with ` and ` (USD first). No revenue / 0 → just the label.

`clean_receipt`: whitelisted keys; `port` / `vessel` ≤ 80, `date` ≤ 20, `services` ≤ 2000 characters and ≤ 40 lines, all via `_short` (refused, not cut); `services` blank → `BadRequest("Write the services.")`.

- [ ] **Step 1: Write the failing tests** in `sheet/tests_receipt.py` (`ApiTestCase`, `tests.pass_two_step`, `@override_settings(RATE_LIMIT_EXPORTS_PER_USER=20)`):
  - `test_prefill_single_usd` — Medical Treatment, revenue 120 USD → `services == "Medical Treatment with cost $120"`, `port == "Alexandria"`, `vessel` name, `date` today DD/MM/YYYY.
  - `test_prefill_entries_two_currencies` — Landing entries revenue 100 USD, 20.5 USD, 3000 EGP → `"Landing with cost $120.50 and EGP 3,000"`.
  - `test_prefill_no_revenue` — revenue empty / 0 → `"Fresh Water"`.
  - `test_prefill_others_uses_note` — note `"Arrange 5 shore pass"`, revenue 50 USD → `"Arrange 5 shore pass with cost $50"`.
  - `test_prefill_cash_to_master` — amount 1000 USD, 5 % → `"Cash to Master with cost $50"`.
  - `test_post_returns_pdf_and_history` — alex POSTs edited fields → 200, `application/pdf`, body contains `(Arrange 5 shore pass with cost $50)`, one `ChangeRecord` with `action="receipt"`, attachment file name starts `Receipt MSC`.
  - `test_blank_services_refused` — `"   "` → 400 `"Write the services."`; `test_too_long_refused` — 2001 characters → 400, 41 lines → 400.
  - `test_viewer_refused` (403 GET and POST), `test_other_port_not_found` (suez user on an Alexandria service → 404), `test_anonymous_refused`, `test_rate_limited` (limit 2 → third POST 429).

- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_receipt` → fail (404 route).

- [ ] **Step 3: Implement** `receipt.prefill`, `validators.clean_receipt`, the model change + hand-checked migration `0017_history_receipt` (AlterField only; check `DJANGO_DEBUG=1 venv/Scripts/python.exe manage.py makemigrations --check --dry-run` is clean afterwards), the view (`@json_api`, `@require_http_methods(["GET", "POST"])`, `require_edit`, scoped service, POST: `ratelimit.check(request, "export")`, `history.record("receipt", service, {"Master receipt": [None, service.service_type]})`, `audit(request, "service.receipt", id=…, vessel=…)`), the route, the History label.

- [ ] **Step 4: Run** `venv/Scripts/python.exe manage.py test sheet` → all pass (history / migration tests included).

- [ ] **Step 5: Commit** `feat(receipt): the receipt endpoint, pre-filled text and History record`

### Task 3: The Receipt button and dialog

**Files:**
- Create: `sheet/static/sheet/js/modals/receipt.js`
- Modify: `sheet/static/sheet/js/modals/vessel.js` (`serviceCard`: a `btn('ghost small', 'receipt', [icon('file'), ' Receipt'], { id })` before Edit, edit roles only), `sheet/static/sheet/js/actions.js` (`receipt`, `receipt-download`, `receipt-back`), `tools/ui_smoke_test.js`

**Interfaces:**
- Consumes: `GET/POST /api/services/<id>/receipt/` (Task 2).
- Produces: `openReceipt(serviceId: number)` in `receipt.js`.

Dialog: head `Receipt` + vessel name; fields Port, Date, Vessel (inputs) and Services (textarea, rows 6), values from the GET; footer **Download** (primary). `state.ctx = { view: 'receipt', vesselId, serviceId }`. Back / close returns to the vessel form the way the service form does. Download: `fetch` POST with JSON + CSRF header (as `api.js` does), on error show the JSON `error` with `showError` in the dialog, on success save the blob exactly as `'crew-log'` does (move that blob-saving into a shared `saveBlob(response, fallbackName)` helper in `actions.js` and use it in both).

- [ ] **Step 1: Write the failing smoke checks** in `tools/ui_smoke_test.js`, in the alex / admin run where MSC AURORA's services are open: `[data-act="receipt"]` exists on each service card; clicking it shows `#receipt-form` with Services pre-filled starting with the service type; Download with the box emptied shows `Write the services.`; a direct POST returns `application/pdf`. In the viewer run: no `[data-act="receipt"]`, POST → 403.

- [ ] **Step 2: Run the smoke test** (throwaway database, see `CLAUDE.md`) for alex → the new checks fail.

- [ ] **Step 3: Implement** the button, dialog, actions and `saveBlob`.

- [ ] **Step 4: Run** `cd tools && npm run check`, then the smoke test for alex (`DJANGO_RATE_LIMIT_WRITES_PER_USER=300`), admin, viewer, suez → all pass. Restart `runserver --noreload` after edits.

- [ ] **Step 5: Commit** `feat(receipt): Receipt button and dialog`

### Task 4: Docs and review

**Files:** `docs/STATUS.md`, `CLAUDE.md` (a **Master receipt** paragraph next to the LOG letter), `README.md` / `SECURITY.md` (test count)

- [ ] **Step 1:** Update the docs; `cd tools && npm run check` green.
- [ ] **Step 2:** Fresh reviewer (most capable model) reads the whole branch; fix important findings test-first; list the rest in STATUS "Left open".
- [ ] **Step 3: Commit** `docs: master receipt` — merge into `main` only when the user agrees.
