# ARKAS Look Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Navy sidebar, white cards with a light shadow, and the ARKAS logo + "ARKAS / EGYPT HUSBANDRY" brand, with no
change to how the app works.

**Architecture:** The logo is served by a small view from the letterhead folder (never in git); a context processor
tells templates whether it exists. The look changes only through `app.css` tokens and a few rules; templates change
only their brand block and titles.

**Tech Stack:** Django 5.2 templates and views, plain CSS tokens, Django test runner, `tools/ui_smoke_test.js`.

**Spec:** `docs/superpowers/specs/2026-11-23-arkas-look-design.md`

## Global Constraints

- Branch `feature/arkas-look` from `main`. **Nothing is committed until the user has seen the real app** (Task 4).
- Colours only as tokens at the top of `app.css`; every new token defined in light `:root`, both dark selectors and
  `@media print` (`tests_look`).
- No `gradient(`, no `text-transform:uppercase`, no `letter-spacing` >= 1, shadow blur <= 12 px (`TidyTests`).
- No inline `style=`, no `innerHTML`; templates hide with `hidden`.
- The logo file is `brand.png` in `settings.LETTERHEAD_DIR`; never in git, never under `static/`.
- Brand text exactly: "ARKAS" / "EGYPT HUSBANDRY"; tab titles end in "ARKAS Egypt Husbandry".
- LF line endings.

## Review Focus

1. No `brand.png` (or no letterhead folder): every page shows the anchor and the brand text; `/brand/logo.png` is 404. Test: Task 1 `test_missing_logo_is_404`, Task 2 `test_pages_fall_back_to_anchor`.
2. A file that is not a PNG saved as `brand.png` (a renamed JPEG, an HTML file): 404, never served, anchor shown. Test: Task 1 `test_not_png_is_404`, `test_context_false_for_not_png`.
3. Someone signed in but mid two-step (code page): the logo must still load, not redirect. Test: Task 1 `test_logo_open_during_two_step`.
4. Dark mode: sidebar text and the active item readable on navy (AA 4.5). Test: Task 3 `test_sidebar_contrast`.
5. Error pages (404 / 500) render without a request context: they must still pick the logo or the anchor and never crash. Test: Task 2 `test_error_pages_show_logo`.

---

### Task 1: Logo file served from the letterhead folder

**Files:**
- Create: `sheet/branding.py`
- Modify: `sheet/views.py` (add `brand_logo`), `sheet/urls.py`, `sheet/context_processors.py`, `config/settings.py` (add `sheet.context_processors.brand` after `theme`), `sheet/middleware.py` (`TwoStepMiddleware._always_open`)
- Test: `sheet/tests_brand.py`

**Interfaces:**
- Produces: `branding.logo_bytes() -> bytes | None` (reads `Path(settings.LETTERHEAD_DIR, "brand.png")`; None when no folder, missing, larger than `MAX_LOGO_BYTES = 500_000`, unreadable (log to `sheet.security` like `_letterhead_images`), or not starting with `PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"`); `branding.logo_available() -> bool`; URL name `brand_logo` at `brand/logo.png`; context key `brand_logo` (bool).

- [ ] **Step 1: Write the failing tests** in `sheet/tests_brand.py` (`TestCase`, each test with `override_settings(LETTERHEAD_DIR=tmp)` on a `tempfile.TemporaryDirectory`; a valid PNG is `PNG_SIGNATURE + b"rest"`):
  - `test_logo_served`: GET `/brand/logo.png` anonymous → 200, `Content-Type` `image/png`, body equals the file, `Cache-Control` contains `max-age=3600`.
  - `test_missing_logo_is_404`: no file → 404; `LETTERHEAD_DIR=""` → 404.
  - `test_not_png_is_404`: file `b"<html>"` → 404; file `b"\xff\xd8\xff"` → 404.
  - `test_too_big_is_404`: signature + 500_001 bytes → 404.
  - `test_logo_open_during_two_step`: `client.login` without `pass_two_step` → GET `/brand/logo.png` → 200 (not 302).
  - `test_context_true_when_present` / `test_context_false_for_not_png`: GET `/login/` → `response.context["brand_logo"]` True / False.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test sheet.tests_brand` → errors (no module / 404 on URL).
- [ ] **Step 3: Implement** `sheet/branding.py`, `views.brand_logo(request)` (GET only via `require_GET`; 404 with `Http404` when `logo_bytes()` is None; `HttpResponse(data, content_type="image/png")` with `Cache-Control: max-age=3600`), the URL, `context_processors.brand(request) -> {"brand_logo": branding.logo_available()}`, the settings entry, and `reverse("brand_logo")` in `_always_open`'s `open_paths`.
- [ ] **Step 4: Run** `manage.py test sheet.tests_brand sheet.tests_twostep` → all pass.

### Task 2: Brand block in the templates

**Files:**
- Modify: `sheet/templates/sheet/index.html` (sidebar brand, `<title>`), `sheet/templates/sheet/login.html`, `sheet/templates/sheet/locked.html`, `sheet/templates/404.html`, `sheet/templates/500.html`, the `<title>` of every other page in `sheet/templates/sheet/` (`password_change*.html`, `two_step_*.html`), `sheet/views.py` (`not_found`, `server_error` pass `{"brand_logo": branding.logo_available()}`)
- Test: `sheet/tests_brand.py`

**Interfaces:**
- Consumes: context `brand_logo`, URL name `brand_logo` (Task 1).
- Produces (CSS hooks for Task 3): sidebar `<div class="brand-tile"><img class="brand-logo" src="{% url 'brand_logo' %}" alt="ARKAS"></div>` when `brand_logo`, else today's `anchor-icon`; `<div class="brand-text">ARKAS<span>EGYPT HUSBANDRY</span></div>`. Sign-in / locked / 404 / 500: `<img class="login-brand" src="…" alt="ARKAS">` + `<h1 class="brand-sub">EGYPT HUSBANDRY</h1>` when `brand_logo`; else anchor + `<h1>ARKAS <span>EGYPT HUSBANDRY</span></h1>`.

- [ ] **Step 1: Write the failing tests**:
  - `test_sidebar_shows_logo_and_name`: logo present, signed in (`pass_two_step`), GET `/` → contains `class="brand-logo"`, `ARKAS<span>EGYPT HUSBANDRY</span>`, not `SERVICE SHEET`.
  - `test_pages_fall_back_to_anchor`: no logo → `/` and `/login/` contain `#i-anchor` and no `brand-logo` / `login-brand`.
  - `test_login_shows_logo`: logo present → `/login/` contains `class="login-brand"` and `EGYPT HUSBANDRY`.
  - `test_error_pages_show_logo`: logo present → GET `/no-such-page/` (404) contains `login-brand`; `views.server_error(RequestFactory().get("/x/"))` content contains `login-brand`; without the logo both contain `#i-anchor`.
  - `test_titles`: no template under `sheet/templates` contains `Marine Service Sheet`; `index.html` has `<title>ARKAS Egypt Husbandry</title>`.
- [ ] **Step 2: Run** `manage.py test sheet.tests_brand` → the new tests fail.
- [ ] **Step 3: Implement** the template and view changes above (the `<p>Sign in to continue</p>` on the sign-in page stays).
- [ ] **Step 4: Run** `manage.py test sheet` → all pass (fix any test that asserted the old brand text).

### Task 3: Navy sidebar and cards

**Files:**
- Modify: `sheet/static/sheet/app.css`
- Test: `sheet/tests_look.py`

**Interfaces:**
- Consumes: classes `brand-tile`, `brand-logo`, `login-brand`, `brand-sub` (Task 2).
- Produces: tokens `--side-bg`, `--side-text`, `--side-muted`, `--side-active`, `--side-hover`, `--card-shadow`,
  `--logo-tile` (`#fff` in every mode: the logo is dark lettering, so its tile stays white in dark mode too).

Values (light): `--bg:#f3f5f8`, `--line:#e3e7ec`, `--side-bg:#0f2340`, `--side-text:#ffffff`, `--side-muted:#b3c3d8`,
`--side-active:#1d3a63`, `--side-hover:#17304f`, `--card-shadow:0 2px 8px rgba(15,35,65,.06)`. Dark: `--side-bg:#0c1a2e`,
`--side-active:#1a3354`, `--side-hover:#132743`, same text tokens, `--card-shadow:none`. Print: `--side-*` set to the
light surface / text values, `--card-shadow:none`. (Update `LIGHT` in `tests_look.py` for the new `--bg` / `--line`.)

- [ ] **Step 1: Write the failing tests** in `tests_look.py`:
  - `test_sidebar_tokens_in_every_mode`: the seven tokens exist in light, dark and the print block.
  - `test_sidebar_contrast`: in light and dark, `contrast(--side-text, --side-bg)`, `contrast(--side-text, --side-active)` and `contrast(--side-muted, --side-bg)` are each >= 4.5.
  - `test_cards_have_shadow_and_radius`: the rules `.table-wrap`, `.panel`, `.svc-card`, `.modal`, `.login-card` each contain `box-shadow:var(--card-shadow)` and `border-radius:10px`; `.btn` and `.input` contain `border-radius:8px`.
  - `test_sidebar_uses_side_tokens`: `.sidebar` rule contains `background:var(--side-bg)`; `.nav-item.active` contains `var(--side-active)`.
- [ ] **Step 2: Run** `manage.py test sheet.tests_look` → the new tests fail.
- [ ] **Step 3: Implement**: tokens; `.sidebar`, `.brand`, `.brand-text`, `.nav-item` (+ `:hover`, `.active`), `.sidebar-foot`, `.user-line` on the `--side-*` tokens (sidebar border-right dropped); `.brand-tile` (background `var(--logo-tile)`), `40px` square, radius 9px, the image `object-fit:contain`; `.login-brand` height 72px; `.brand-sub` 13px, `var(--muted)`; card rules from the test; `.svc-card` background `var(--surface)`. Keep the 900 px mobile slide-in and print rules working (print hides the sidebar already).
- [ ] **Step 4: Run** `manage.py test sheet` → all pass.

### Task 4: Docs, full check, show the user, then commit

**Files:**
- Modify: `docs/DEPLOYMENT.md` (letterhead row and checklist: `brand.png`, the ARKAS logo, PNG with a see-through background, under 500 KB), `docs/STATUS.md` (built, decisions: look C, logo + name, logo from the letterhead folder; branch unmerged), `CLAUDE.md` (Theme bullet: navy sidebar tokens and cards; the logo route and `branding.py`), `README.md` / `SECURITY.md` (backend test count).

- [ ] **Step 1:** Update the docs above.
- [ ] **Step 2: Run** `cd tools && npm run check` → green.
- [ ] **Step 3: Smoke test** on a throwaway database (CLAUDE.md recipe, `DJANGO_RATE_LIMIT_WRITES_PER_USER=300`, `DJANGO_LETTERHEAD_DIR` = a scratch folder holding the ARKAS `brand.png`) for `alex`, `admin`, `viewer` → all pass.
- [ ] **Step 4: Show the user** the running app (sidebar, Vessels, a dialog, sign-in, dark mode, phone width) in the browser pane, with screenshots; wait for their OK.
- [ ] **Step 5: Commit** on `feature/arkas-look` (code + spec + plan + docs; never the logo); merge only when the user agrees.
