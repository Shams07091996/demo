# Safe Page Building and Code Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The front end never parses HTML strings: every screen is built from elements, the browser enforces it
with Trusted Types, and ruff / ESLint / pip-audit / npm audit stop regressions.

**Architecture:** A small pure element builder (`js/dom.js`: `h`, `frag`, `setChildren`, `optionEls`) replaces
template strings. Screens are converted one area at a time; while a shared helper still has string callers, its old
`…Html` version stays beside the new `…El` version and is deleted when its last caller moves. The CSP lock and the
sink ban land last, when no sink is left.

**Tech Stack:** Django 5.2, vanilla ES modules (no build step), Node + jsdom + esbuild for tests, ruff, ESLint 9
(flat config), pip-audit.

**Spec:** `docs/superpowers/specs/2026-11-17-safe-dom-and-checks-design.md` (approved: "build it without the
innerHTML, no security vulnerability should be there").

## Global Constraints
- Banned in `sheet/static/sheet/js/**`: `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`,
  `DOMParser`, `createContextualFragment`, `eval`, `new Function`, string `setTimeout`/`setInterval`.
- `h()` attribute allow-list: `id, class, title, type, name, for, colspan, rowspan, min, max, step, maxlength,
  placeholder, rows, role, tabindex, href, target, rel, autocomplete, inputmode, readonly, multiple, accept, list`,
  plus `aria-*`; `data-*` only via `dataset`. Properties: `value, checked, selected, disabled, hidden`. `style` only
  as an object applied through `el.style`. Anything else throws. `href` must be `#…`, relative or `http(s):`.
- Final CSP adds `require-trusted-types-for 'script'` and `trusted-types pdfjs-worker`, and **removes**
  `style-src-attr 'unsafe-inline'` (the `style-src` fallback line keeps `'unsafe-inline'` only if a test shows an
  old-browser need; otherwise it goes too).
- Markup, CSS classes, ids, `data-act` names and visible text stay exactly as today.
- No new runtime dependency; dev tools only (`requirements-dev.txt`, `tools/package.json` devDependencies).
- LF line endings; smoke test on a throwaway DB only (see `CLAUDE.md`).

## Review Focus
1. Text that looks like HTML (`<b>`, `&amp;`, `"quotes"`) in a vessel name / agent / guest / remark / master-data
   value shows literally everywhere, and `&amp;` is not double-shown as `&amp;amp;` — smoke check with
   `SMOKE <i>X</i> & "Q"` (Task 3, extended in every screen task).
2. A `<select>` refilled while it has a value keeps that value selected (vessel form port change, quick add) —
   smoke check in Task 3 and Task 4.
3. Event handling still works after a redraw: `data-act` buttons inside rebuilt rows, the `#master-grid` change
   listener, inputs that keep focus while a list redraws — existing smoke checks must stay green each task.
4. Empty / missing values (`null`, `undefined`, `0`) render as today (`—`, `0.00`, empty input) and not as the text
   `null` — `dom_test` case in Task 2.
5. Reading a PDF still works under the final CSP in a real browser (Task 9 checklist).

---

### Task 1: Checking tools

**Files:** Create `requirements-dev.txt`, `tools/eslint.config.js`, `tools/check.js`; modify `pyproject.toml`,
`tools/package.json`, any Python file ruff flags.

**Interfaces:** Produces `npm run check` (in `tools/`), `npm run lint`.

- [ ] **Step 1:** `requirements-dev.txt` = `-r requirements.txt`, `ruff`, `pip-audit`; install into the venv.
  `npm install --save-dev eslint@9 globals` in `tools/`.
- [ ] **Step 2:** ruff `select` adds `"S"`; `per-file-ignores` for `sheet/tests*.py`: `S101, S105, S106`. Run
  `venv/Scripts/ruff check .` — fix every finding, or add `# noqa: <code>  <reason>` only where the code is right.
- [ ] **Step 3:** `eslint.config.js`: files `../sheet/static/sheet/js/**/*.js` (ignores `vendor/`), browser globals,
  `recommended`, `no-eval`, `no-implied-eval`, `no-new-func`. (The sink ban comes in Task 9.) Fix findings.
- [ ] **Step 4:** `tools/check.js` runs in order, stopping on the first failure and printing which: ruff, ESLint,
  `pip-audit -r ../requirements.txt`, `npm audit --omit=optional`, `manage.py check --deploy --fail-level WARNING`
  (env: random `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS=example.com`, no `DJANGO_DEBUG`), `manage.py test sheet`,
  `npm run test:parsing`, `node dom_test.js` (once it exists). `package.json` scripts `check`, `lint`.
- [ ] **Step 5:** Run `npm run check` → everything passes (note any `check --deploy` warning that is deliberate,
  e.g. HSTS preload, and silence only that id). Commit `chore: add ruff security rules, ESLint, pip-audit and one check command`.

### Task 1b: No eval anywhere (user: "if there is any eval delete it too")

Found: the app's own code has none. It remains in four places:
- `tools/parsing_test.js:11` (`new Function`, to load the bundled parsers);
- `tools/ui_smoke_test.js:83, 91, 593` (`w.eval`);
- the vendored PDF.js: a `new Function("")` probe in both files, plus the PostScript-function compiler in
  `pdf.worker.min.mjs`. That compiler is the path behind CVE-2024-4367. Today it is switched off only by
  `isEvalSupported: false`, and the worker file may be served without our CSP (for example by nginx in production).

**Files:** `tools/parsing_test.js`, `tools/ui_smoke_test.js`, `sheet/static/sheet/vendor/pdfjs/pdf.min.mjs`,
`pdf.worker.min.mjs`, new `sheet/vendor/pdfjs/PATCHES.md`, `sheet/tests_dev.py`.

- [ ] **Step 1: Failing test** (`tests_dev.py`) `test_no_eval_in_shipped_javascript`: for every `.js`/`.mjs` under
  `sheet/static/sheet/` (vendor included) the text contains none of `eval(`, `new Function`, `Function(`
  (word-boundary regex, `\beval\s*\(` and `\bFunction\s*\(`).
- [ ] **Step 2:** FAIL (PDF.js). **Step 3:** patch both PDF.js files with exact string replacements:
  - `try{new Function("");return!0}catch{return!1}` → `return!1`;
  - in the worker, `if(e)return new Function("src","srcOffset","dest","destOffset",e)` → `` (PDF.js then falls back
    to its built-in PostScript interpreter).

  Record both in `PATCHES.md` with the original strings, so a future PDF.js update repeats them.
- [ ] **Step 4:** tools without eval:
  - `parsing_test.js`: write the esbuild `cjs` output to a temp file and `require()` it.
  - smoke test: `localNow` / `plusDays` use `new w.Date()` directly, and the bundle loads through a `<script>`
    element appended to the jsdom document (jsdom's `runScripts` setting).
  - Then `grep -rnE "\beval\s*\(|\bFunction\s*\(" sheet tools --include=*.js --include=*.mjs --include=*.py`
    (excluding `node_modules`) → nothing.
- [ ] **Step 5:** test PASS, parser tests PASS, smoke alex PASS, reading a PDF still works (checked again in
  Task 9's browser list). Commit `security: remove every eval and new Function, PDF.js included`.

### Task 2: Element builder

**Files:** Create `sheet/static/sheet/js/dom.js`, `tools/dom_test.js`.

**Interfaces — Produces:**
- `h(tag: string, props?: object|null, ...children) → Element`
- `frag(...children) → DocumentFragment`
- `setChildren(el: Element, ...children) → void` (`el.replaceChildren`)
- `optionEls(pairs: Array<[value, label]>, selected: string) → Array<HTMLOptionElement>`
- Children: Node, string/number → text node, arrays flattened, `null`/`undefined`/`false` skipped.

- [ ] **Step 1: Failing tests** (`dom_test.js`, jsdom global document, same `ok()` style as `parsing_test.js`):
  - `h('td', null, '<img src=x onerror=alert(1)>')` → `td.querySelector('img') === null`, `textContent` equals input.
  - `h('a', { href: 'javascript:alert(1)' })` throws; `{ attrs: { onclick: 'x' } }` throws; `{ attrs: { srcdoc: 'x' } }` throws; `{ attrs: { style: 'x' } }` throws.
  - `h('button', { class: 'btn small', dataset: { act: 'summary', id: 5 } })` → `dataset.act === 'summary'`, `dataset.id === '5'`.
  - `h('input', { value: 'a"b', disabled: true })` → `.value === 'a"b'`, `.disabled === true`.
  - `h('div', { style: { display: 'none', borderTopColor: '#fff' } })` → `style.display === 'none'`.
  - `h('td', null, null, undefined, false, 0, ['a', ['b']])` → `textContent === '0ab'`.
  - `optionEls([['', 'All'], ['x', '<b>']], 'x')` → second option selected, label literal.
- [ ] **Step 2:** `node tools/dom_test.js` → FAIL (no module). **Step 3:** implement `dom.js`. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: element builder that only ever inserts text`.

### Task 3: Vessels area (list, pager, alerts, range notice, dashboard, port selects)

**Files:** `render/list.js`, `render/pager.js`, `render/notifications.js`, `render/rangeNotice.js`,
`render/dashboard.js`, `main.js` (port select), `quickAdd.js`, `components.js` (add `statusChipEl`, `optionChoicesEl`,
`tagLabel` unchanged), `tools/ui_smoke_test.js`.

**Interfaces — Produces:** `pagerEl({count, pages, page, size, noun, sizeId, prev, next}) → Element`;
`optionChoicesEl(kind, current = '', port = null) → Option[]`; `statusChipEl(status) → Element`;
`portOptionEls({ all: boolean }) → Option[]` (in `components.js`, used by every port select).

- [ ] **Step 1: Failing smoke checks** (all roles): create via API a vessel named `SMOKE <i>X</i> & "Q"` (agent
  `<b>A</b>`) at the start, delete it at the end; on Vessels, its row's name cell `textContent` is exactly that and
  the row has no `i`/`b` element; the alerts panel likewise when it's today; after an admin changes `#qa-port`,
  `#qa-agent` keeps its chosen value.
- [ ] **Step 2:** Run the smoke test → the literal-text checks FAIL? (They may already pass because of `esc()`; then
  they act as guards.) Record which.
- [ ] **Step 3:** Convert the files to `h()` / `setChildren`; old `pagerHtml`, `optionChoices`, `statusChip` stay
  until Task 8 removes their last string callers.
- [ ] **Step 4:** Smoke alex / admin / viewer / suez + `npm run check` → PASS; `grep -n "innerHTML\|insertAdjacentHTML"`
  in the converted files → none. Commit `refactor: build the vessels area from elements`.

### Task 4: Dialog frame, vessel form, summary

**Files:** `modal.js`, `modals/vessel.js`, `modals/summary.js`, `components.js` (`headEl`, `metaBadgesEl`, `pillEl`,
`moneyPillsEl`, `portCallBlockEl`), callers in `actions.js`.

**Interfaces — Produces:** `openModal(content: Node)`; until Task 8, `openModalHtml(html: string)` keeps the old
behaviour for unconverted dialogs (renamed so each remaining caller is visible).

- [ ] **Step 1: Failing smoke checks:** the summary of the hostile vessel shows its name and agent literally with no
  `i`/`b` inside `#modal`; in the vessel form, the admin changing the port keeps the chosen OPR/POC/Agent.
- [ ] **Steps 2–4:** run (record), convert, smoke ×4 + check PASS. Commit `refactor: build the vessel and summary dialogs from elements`.

### Task 5: Service dialog and crew editor

**Files:** `modals/service.js` (incl. `crewGroupHtml`, `entryRowHtml`, money preview box), `actions.js`
(`add-entry` uses `append(entryRowEl(type))`).

- [ ] **Step 1: Failing smoke check:** add a service whose remark / crew name is `<b>R</b>` → reopening shows it
  literally in the input value and the summary, no `b` element.
- [ ] **Steps 2–4:** run, convert, smoke ×4 + check PASS. Commit `refactor: build the service dialog from elements`.

### Task 6: Bulk add

**Files:** `pages/bulk.js` (preview table, summary, success box, `#bk-port`).

- [ ] **Step 1: Failing smoke check:** pasting a row with vessel `SMOKE <i>B</i>` shows the text literally in the
  editable preview cell (`input.value`) and no `i` in `#bk-preview`; the success box link still works.
- [ ] **Steps 2–4:** run, convert, smoke ×4 + check PASS. Commit `refactor: build bulk add from elements`.

### Task 7: Hotels, Transport and the booking dialog

**Files:** `pages/bookings.js`, `modals/booking.js` (vessel picker, crew picker, guests).

- [ ] **Step 1: Failing smoke checks:** the hostile vessel in the booking dialog's vessel picker and a guest named
  `<b>G</b>` in the Hotels table show literally; no `b`/`i` elements in `#modal` or the table.
- [ ] **Steps 2–4:** run, convert, smoke ×4 + check PASS. Commit `refactor: build hotels, transport and bookings from elements`.

### Task 8: Calculations, Master data, Rates; remove the old string helpers

**Files:** `pages/calculations.js`, `pages/master.js`, `pages/rates.js`, `components.js`, `render/pager.js`,
`modal.js`, `util.js` (delete `esc`, `val`), `tools/parsing_test.js` if it imports them.

- [ ] **Step 1: Failing smoke checks:** the hostile vessel's row on Calculations, and a master-data value
  `SMOKE <i>M</i>` on Master data, show literally; changing that value's port (admin) still saves.
- [ ] **Step 2–3:** run, convert, then delete every `…Html` helper, `openModalHtml`, `esc`, `val`.
- [ ] **Step 4:** `grep -rnE "innerHTML|outerHTML|insertAdjacentHTML|esc\(|Html\(" sheet/static/sheet/js` → nothing;
  smoke ×4 + check PASS. Commit `refactor: no screen builds HTML strings any more`.

### Task 9: The lock — CSP, sink ban, inline styles, PDF worker, docs

**Files:** `sheet/middleware.py`, `sheet/tests.py` (CSP tests at lines ~263 and ~658), `templates/sheet/*.html`
(20 `style=` attributes → classes in the stylesheet), `js/pdfReader.js`, `tools/eslint.config.js`,
`SECURITY.md`, `CLAUDE.md`, `README.md`, `docs/STATUS.md`.

- [ ] **Step 1: Failing backend tests:** the page CSP contains `require-trusted-types-for 'script'` and
  `trusted-types pdfjs-worker`, and does **not** contain `style-src-attr 'unsafe-inline'` (replace the old assertion
  at ~658); a test asserts no template under `sheet/templates/sheet/` contains `style="`.
- [ ] **Step 2:** FAIL. **Step 3:** implement the CSP; move inline styles to classes; in `pdfReader.js` create the
  `pdfjs-worker` policy once (`createScriptURL: (url) => { if (url !== PDF.worker) throw …; return url; }`), build
  `new Worker(policy ? policy.createScriptURL(PDF.worker) : PDF.worker, { type: 'module' })` and set
  `pdfjs.GlobalWorkerOptions.workerPort`; ESLint `no-restricted-properties` / `no-restricted-syntax` for every banned
  sink in Global Constraints, and `no-restricted-globals` for `DOMParser`.
- [ ] **Step 4:** backend tests + smoke ×4 + `npm run check` PASS; prove the ESLint ban bites by temporarily adding
  `x.innerHTML = ''` and seeing it fail, then remove it.
- [ ] **Step 5: Real-browser checklist** (built-in browser, `runserver` on the throwaway DB): as admin and as alex,
  open every page, every dialog, the summary, add a service row, read a PDF in bulk add; console shows **zero** CSP
  or Trusted Types violations (check with `read_console_messages` and a `securitypolicyviolation` listener); the
  hostile vessel shows literally.
- [ ] **Step 6:** Docs: SECURITY.md (A03 Injection row, gap 3 closed, check command, test count), CLAUDE.md
  (rendering rule: "build with `h()`, never HTML strings"; `npm run check`), README (dev tools), STATUS.md. Update the
  backend test count in README and SECURITY. Commit `feat: browser-enforced no-HTML lock and docs`.
- [ ] **Step 7:** Fresh reviewer (opus) on the whole branch; fix Critical/Important test-first; merge only on the
  user's OK.
