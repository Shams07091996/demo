# New look: line icons, neutral theme, dark / light mode, system font — design

Date: 2026-11-18. Branch: `feature/new-look` (from `main` after the agents and dashboards branches are merged, so
it restyles their screens too). Third of three pieces.

## Why

The app is being sold to the user's company and looks "AI-generated": emojis as icons (🚢 📥 🏨 🚗 💰 📊 🗂 💱 🕘 🔑 ⎋
🔔 🗑 ✏ ⚠ 🔴 🟡 ✅ …), navy-with-teal glow, gradients, all-caps display font, wide padding and unused space. The user
wants it to look like plain, professional office software, in dark or light mode, with **no third-party
dependency**.

## Decisions the user made

- **Look B**: neutral grey surfaces with **one blue accent**; colour only for the current page, primary buttons,
  warnings and charts. Approved from the mockup `look-b-dark.html` (dark) / `visual-style.html` option B (dark and
  light) in `.superpowers/brainstorm/` (not committed).
- **System font** (Segoe UI on Windows): the Google Fonts link is removed.
- **Dark and light mode**.
- **No third-party code or downloads**: icons are drawn for this project.

## Goals

1. **Icons**: every emoji / pictograph used as an icon is replaced by a line icon from one set (24×24 viewBox,
   1.75 stroke, round caps and joins, `currentColor`). Plain text arrows used for sorting (↕ ↑ ↓) and the "✕ / ×"
   close marks become icons too, so no emoji or dingbat remains in templates or JS (a test checks this). Icon set
   (at least): anchor (brand), ship, import, bed, car, calculator, chart, database, swap, clock, key, log-out, bell,
   trash, pencil, plus, x, check, alert, menu, sun, moon, chevron-down, chevron-up, sort, arrow-right, calendar,
   users, printer, globe, settings. Status dots (today / tomorrow / missing agent) become small CSS dots.
2. **Theme**: colours become CSS custom properties with a dark set and a light set (the mockup's values:
   dark `--bg #141517`, `--surface #1c1e21`, `--surface2 #232529`, `--line #2c2f34`, `--text #e8e9eb`,
   `--muted #9a9ea6`, `--accent #4c8dff`; light `--bg #f6f7f8`, `--surface #fff`, `--line #e1e3e6`,
   `--text #1b1d20`, `--muted #646a73`, `--accent #2563eb`; plus danger / warning / success per mode, all with
   readable contrast, WCAG AA for text). Every hard-coded colour in `app.css` and in JS (`CHART_COLORS`, the
   `style: {color}` in dashboard / notifications) goes through these variables or a per-mode chart palette.
3. **Mode switch**: the page follows the computer (`prefers-color-scheme`) until the user picks; a sidebar item
   "Light mode" / "Dark mode" toggles and remembers the choice in `localStorage` (wrapped in try/catch, as the alerts
   banner does). To avoid a flash, the server also reads a `theme` cookie (`light` / `dark`, whitelisted) and renders
   `data-theme` on `<html>`; the switch sets both. Login and password-change pages follow the same theme.
4. **Tidy**: system font stack (`"Segoe UI", system-ui, -apple-system, Roboto, sans-serif`); no Bebas Neue, no
   all-caps letter-spaced headings, no gradients, no glows / heavy shadows; thinner borders; smaller radii (6 px);
   tighter padding; pages use the **full width** (drop `max-width: 1500px`) with 18 px side padding; the "Click for
   details →" lines and other decorative text go (the cards stay clickable).

## Constraints (security — must keep)

- CSP unchanged except: **remove** `https://fonts.googleapis.com` from `style-src` / `style-src-elem` and
  `https://fonts.gstatic.com` from `font-src` (set `font-src 'self'` or `'none'`). No new sources.
- Icons in the page itself: **one inline SVG sprite** (`<svg hidden><symbol id="i-ship">…</symbol>…</svg>`)
  included once in each template from `templates/sheet/icons.svg` (a Django include of a file we wrote — static
  markup, no user data). Templates use `<svg class="ic" aria-hidden="true"><use href="#i-ship"></use></svg>`.
- `dom.js` gains an `icon(name)` helper that builds `<svg class="ic" aria-hidden="true"><use href="#i-NAME">` with
  `document.createElementNS` (SVG namespace). `name` must match `/^[a-z0-9-]+$/` and be in the sprite's known list,
  else it throws. `h()` itself stays HTML-only: no generic SVG / `href` support is added, so no new way to put a
  URL into the page. ESLint and `tests_frontend_safety` keep passing; `tests_frontend_safety` gains checks that
  templates and JS contain no emoji / pictographs, that the CSP has no Google hosts, and that every `icon('…')` /
  `#i-…` used exists in the sprite.
- No inline `style=` attributes, no `innerHTML`, no Trusted Types policy.

## Approaches considered

1. **Inline sprite in the page + `icon()` helper** (chosen): no extra request, no flash, icons usable from templates
   and JS, and the helper only ever points at `#i-…` fragments.
2. Separate `static/sheet/icons.svg` referenced by URL: one more file to fetch and allow; `<use>` with an external URL
   is a broader thing to permit.
3. Icons drawn by JS from path data: template icons (sidebar) would appear only after JS runs.
Theme: CSS variables + `data-theme` + cookie (chosen) vs two stylesheets (duplicated rules).

## Tests (test-first)

Safety tests above; a template test that `index.html` renders `data-theme` from a valid cookie and ignores a bad one;
a check that `app.css` has no hex colours outside the theme variable blocks; jsdom test that `icon()` throws on an
unknown / malformed name; smoke test passes for alex / admin / viewer / suez with the new markup (update selectors
that relied on emoji text, e.g. "🗑", "✏ Edit").

## Left to the builder

Exact icon drawings (keep them simple and consistent with the mockup's), spacing values, chart palette per mode, and
which leftover decorative text is removed (keep to "decorative only"; ask if a removal would drop information).
