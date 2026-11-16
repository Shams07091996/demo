# Safe page building (no innerHTML) + code checks

Date: 2026-11-17 · Size: project · Status: draft for approval

## Why
The user is **selling the app to their company**, so security comes first. The front end builds every screen as an
HTML string and writes it with `innerHTML` (37 places in 17 files). Each place is safe only while every dynamic value
has been passed through `esc()` by hand; one missed `esc()` is a stored XSS (a vessel name, agent, guest name... runs
as script for every viewer). The user asked for **the most secure option**, plus checking tools (ruff, ESLint,
pip-audit). This is piece 1 of 3; piece 2 is an OWASP Top 10 (2025) review, piece 3 two-step login (MFA).

## Goals
- **No HTML strings are ever parsed** from front-end code: no `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`, `DOMParser`, `createContextualFragment`. Screens are built from elements; dynamic values only ever
  go in as **text** (`textContent` / text nodes) or as **attribute values** via `setAttribute` on an allow-list.
- **The browser enforces it**: CSP `require-trusted-types-for 'script'` with **no HTML policy at all**, so any
  string-to-HTML sink throws. One narrow policy, `pdfjs-worker`, creates a script URL only for the exact vendored
  PDF.js worker URL (anything else throws).
- **Tools stop regressions**: ESLint bans those sinks (and `eval`, `new Function`, string `setTimeout`); ruff gains its
  security rules (`S`, from Bandit); pip-audit checks Python packages, `npm audit` the dev tools. One command runs all
  checks and tests.
- Screens look and behave **exactly as today** (same markup, classes, `data-act` buttons, ids).

## Non-goals
Visual changes; a framework or build step (still vanilla ES modules, no bundler); server-side changes beyond the CSP
header; the Django admin pages (they keep Django's own defaults); MFA and the wider OWASP review (pieces 2 and 3).

## Anti-goals
- A sanitizer library or an HTML Trusted-Types policy "just for this one place" — that reopens the hole.
- Any screen that silently breaks; any `data-act` button that stops working.

## Approaches (user picked B)
| | What | Trade-off |
|---|---|---|
| A | One auto-escaping `html` template helper + Trusted Types policy that only it may use | Mechanical change; HTML is still parsed, safety rests on the helper |
| **B. Build elements, no HTML parsing at all (chosen: "the most secure one")** | Small element builder; every screen rewritten to return nodes; Trusted Types with no HTML policy | Rewrites ~3,000 lines of rendering; safest by construction and enforced by the browser |
| C | Keep strings, audit every `esc()`, add a lint rule | Least work; still depends on nobody forgetting |

## Design
- **`js/dom.js`** (new, pure, unit-tested in Node with jsdom):
  - `h(tag, props, ...children)` → Element. `props` keys: `class`, `id`, `dataset` (object → `data-*`), `style`
    (object of CSS properties set via `el.style`), `attrs` (other attributes). Children: Node, string/number (→ text
    node), arrays (flattened), `null`/`false` (skipped).
  - Attribute allow-list; **refuses** names starting with `on`, `srcdoc`, and `href`/`src`/`action` values that are not
    `#…`, relative, or `http(s):` (blocks `javascript:` / `data:`). Throws on refusal so tests catch it.
  - `frag(...children)` → DocumentFragment; `setChildren(el, ...children)` → `el.replaceChildren(...)`.
  - `optionEls(pairs, selected)` for `<select>` fills.
- **Every `…Html()` function becomes a node builder** (`rowHtml` → `rowEl`, `pagerHtml` → `pagerEl`,
  `optionChoices` → returns `<option>` nodes, `statusChip`, `entryRowHtml`, modals, etc.). Callers use
  `setChildren`. Modal open takes a node instead of a string.
- **`esc()` / `val()`** become unnecessary and are removed (nothing left to escape); `index.html` (server-rendered
  by Django with auto-escaping) is unchanged.
- **CSP** (`middleware.py`): add `require-trusted-types-for 'script'` and `trusted-types pdfjs-worker`.
  `pdfReader.js` creates the policy and passes the worker URL through it (when `window.trustedTypes` exists).
- **Checks:** `pip install ruff pip-audit` into the venv (dev only, listed in a new `requirements-dev.txt`);
  `npm install --save-dev eslint` in `tools/` with `eslint.config.js` covering `sheet/static/sheet/js/` (not the
  vendored PDF.js). ruff `select` adds `S`; fix or justify (`# noqa: S…` with a reason) every hit.
  `tools/check.sh` (also a `npm run check`) runs: ruff, ESLint, pip-audit, `npm audit --omit=optional`,
  `manage.py check --deploy` (with prod-like env), backend tests, parser tests.

## Settled after the builder check (my calls unless noted)
- **PDF.js under Trusted Types (answered from the code):** the vendored build supports `workerPort`. `pdfReader.js`
  creates the worker itself — `new Worker(policy.createScriptURL(PDF.worker), { type: 'module' })`, where the
  `pdfjs-worker` policy returns the URL only if it equals `PDF.worker` and throws otherwise — and sets
  `GlobalWorkerOptions.workerPort`. PDF.js then never builds a worker or blob URL itself. Its one `new Function` is
  already blocked by `script-src 'self'` (no `'unsafe-eval'`) and is turned off with `isEvalSupported: false`. If the
  real-browser check still finds a violation, I stop and bring it back rather than widening the policy.
- **What `h()` accepts:** a fixed allow-list, not patterns, except `data-*` (via `dataset`) and `aria-*`.
  Attributes: `id, class, title, type, name, for, colspan, rowspan, min, max, step, maxlength, placeholder, rows,
  role, tabindex, href, target, rel, autocomplete, inputmode, readonly, multiple, accept, list`. **Properties** (set
  as `el.value` and so on, not as attributes): `value, checked, selected, disabled, hidden`. Anything else throws, so
  the smoke test finds it. No SVG is used (checked), so `createElementNS` isn't needed.
- **Order of work:** shared builders (`components.js`, `pager`, the option lists) are converted **together with all
  their callers** in dependency order. There is no temporary string adapter. The branch is merged only once every
  screen is converted, and the smoke test runs after each step.
- **CSP lands last:** the Trusted Types rules are added once every sink is gone. In the same step,
  **`style-src-attr 'unsafe-inline'` is dropped**: the 20 `style="…"` attributes in the templates become classes.
  Styles set from JS through `el.style` are not affected by that rule. This closes gap 3 in SECURITY.md, which
  matches "the most secure option".
- **Real-browser check:** a written checklist done in the built-in browser:
  - log in as admin and as a port user;
  - open every page, every dialog and the summary;
  - add a service row; read a PDF.
  Pass means zero CSP or Trusted Types violations in the console, and the hostile-name vessel shows as plain text.
- **Running the checks:** `tools/check.js` (Node), called by `npm run check`, so it works on Windows without Git
  Bash. `check --deploy` runs with throwaway production-like environment values: a random secret key, an
  `ALLOWED_HOSTS` value and `DJANGO_DEBUG` unset. This only checks the settings and needs no database.

## Testing
- `tools/dom_test.js`: `h()` puts `<img src=x onerror=…>` in as text; refuses `onclick`, `javascript:` href;
  dataset / style / attrs work.
- Backend: CSP header contains `require-trusted-types-for 'script'` and `trusted-types pdfjs-worker`.
- Smoke test (alex / admin / viewer / suez) passes unchanged, plus new checks: a vessel named
  `<img src=x onerror=alert(1)>` shows that text literally in the list, summary, bookings and calculations, and no
  `img` element appears.
- **Real browser** (jsdom has no Trusted Types): open every page in the built-in browser with the new CSP and confirm
  no Trusted Types violations in the console, including reading a PDF.
- `grep` shows zero banned sinks; ESLint enforces it.

## Left to the builder
Exact module split for the new builders; names of helpers; order of converting files (one screen at a time, smoke
test after each).
