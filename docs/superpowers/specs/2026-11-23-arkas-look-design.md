# ARKAS look: navy sidebar, cards, company logo — design

Date: 2026-11-23. Branch: `feature/arkas-look` (from `main`). Restyles the look built on 2026-11-18
(`2026-11-18-new-look-design.md`); nothing about how the app works changes.

## Why

The user compared the app with a stand-alone mock-up the company had (`ARKAS_EGYPT_AGENCY_V19_FINAL_INTEGRATED_TEST.html`,
a browser-only prototype: data in localStorage, passwords in the file). Its users said that one looks better because of
its **colours and its cards**. The user wants those, plus the company logo, without losing what the 2026-11-18 look
fixed (it looked "AI-generated": gradients, navy-with-teal glow, all-caps labels, wide padding).

## Decisions the user made

- **Look C ("in between")**, approved from the mockup `look-options.html` in `.superpowers/brainstorm/1179-1795454996/`
  (not committed): a **plain navy sidebar (no gradient)**, the **blue accent kept** (no teal), **white cards with
  medium corners and a light shadow**.
- **The ARKAS logo**, small, on a white tile, with the name **"ARKAS" / "EGYPT HUSBANDRY"** beside it (mockup
  `look-c-name.html`, which also shows the sign-in page with the logo above "EGYPT HUSBANDRY").
- **Show the real app before anything is committed.**

## Goals

- Sidebar: solid navy (`--side-bg`), light text, current page a lighter navy band, hover a faint one. Brand block:
  logo tile + "ARKAS" / "EGYPT HUSBANDRY".
- Page background a slightly cooler grey; surfaces stay white.
- Cards: tables' wrappers, service cards, panels, dialogs, notification panel, form sections: white, radius 10 px
  (was 6), 1 px border, light shadow `0 2px 8px` (navy at ~6 %). Buttons and inputs radius 8 px.
- Dark mode keeps its greys; the sidebar becomes a deep navy that matches; shadows are dropped or near-invisible.
  Print stays plain (no sidebar, no shadows).
- Sign-in, 404, 500 and locked pages: logo above "EGYPT HUSBANDRY" instead of the anchor + "MARINE SERVICE SHEET".
  Browser tab titles: "ARKAS Egypt Husbandry" (e.g. "Sign in · ARKAS Egypt Husbandry").

## Non-goals / anti-goals

- No gradients, glows, teal, all-caps or letter-spaced eyebrow labels, subtitles, stat cards or extra help text
  (the user's standing preference for compact screens).
- No change to behaviour, data, the API, roles or the JS modules' logic.
- No third-party code, fonts or downloads.
- **The logo never goes into git or under `static/`** (the GitHub repo is public), the same rule as the letterhead.

## Constraints

- Colours exist only as tokens at the top of `app.css` (`tests_look`); new tokens: `--side-bg`, `--side-text`,
  `--side-muted`, `--side-active`, `--side-hover`, `--card-shadow`, each defined for light, dark (both selectors)
  and print.
- CSP: `img-src` must allow the logo URL (same origin). No inline styles (`style-src-attr 'none'`).
- Icons stay the inline sprite; the anchor remains as the fallback.

## Logo delivery

`GET /brand/logo.png` (`views.brand_logo`): reads `brand.png` from `settings.LETTERHEAD_DIR` (fixed name only, as
`_LETTERHEAD_FILES` does), checks it is a PNG (signature), answers `image/png` with a cache header; missing / not a PNG
→ 404. It needs no sign-in (the sign-in page shows it). Templates get `brand_logo` (true when the file exists) from
the context processor and show either `<img src="/brand/logo.png" alt="ARKAS">` on the white tile or the anchor.
`DEPLOYMENT.md` gains a step: put `brand.png` in the letterhead folder.

## Approaches

1. **Re-theme through tokens + a few rules** (chosen): change the token values, add the sidebar / shadow tokens, raise
   radii, add `box-shadow: var(--card-shadow)` to the card classes; templates only change the brand block. Small,
   keeps one stylesheet and dark mode working.
2. Second stylesheet for the new look: duplicated rules, two places to keep in step. Rejected.
3. Logo as a static file or inline data URI: puts a company asset into the public repo. Rejected.

## Left to the builder

Exact navy / grey values (start from the mockup: sidebar `#0f2340`, active `#1d3a63`, text `#cfdbea`, muted
`#b3c3d8`, background `#f3f5f8`, line `#e3e7ec`), which existing classes count as "cards", the dark-mode navy, and the
tests for the logo view (present / missing / not a PNG / no sign-in needed / no path tricks).
