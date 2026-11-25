# Sidebar scroll, Services by vessel, Dashboard views — design

2026-11-26. Three separate pieces, built in this order on one branch (`feature/services-dashboard-views`).
Reference: the user's `ARKAS_EGYPT_AGENCY_V19_FINAL_INTEGRATED_TEST.html` (vessel cards on Services, report cards).

## 1. Sidebar scroll

**Why:** with every folder open the nav is taller than the screen and shows the plain Windows scrollbar, light
grey on the navy sidebar; it looks broken.

**Design (my call):** `.nav` keeps `overflow-y:auto`; add a thin scrollbar in the sidebar colours
(`scrollbar-width:thin; scrollbar-color: var(--side-active) transparent` plus the `::-webkit-scrollbar` rules),
new tokens only if `--side-*` has nothing fitting (light and dark). Brand and sidebar foot stay fixed. Checked in the
browser with all folders open, light and dark, before showing the user.

## 2. Services page: vessels with their services

**Why:** the team thinks in vessels; the HTML's vessel cards that open to service cards read better than one row
per service.

**Approaches:** (a) keep the service rows; (b) vessel cards that open to service cards (picked, my
recommendation, user agreed); (c) a switch between both — more to build and test, no need stated.

**Design:**
- Same filters as today (status ticks, Missing details only, From–To, type, agent, search, port). They decide which
  services show; a vessel shows when at least one of its services matches, and shows only the matching ones.
- One card per vessel: name, port (when `ME.multiPort`), terminal / berth, vessel date, OPR, "N services", and a
  small tag when any of its services has missing details. Clicking the card (or its arrow button) opens / closes it.
- Inside: one small card per service: type, status pill, agent, completed date (if any), the missing tags
  (`Agent`, `Cost`, `Revenue`, `Rate`, `Bookings`, money tags only with `money.view`), and the actions it has today
  (open the service form for `services.edit`, otherwise open the vessel read-only).
- Order: oldest vessel first (only Completed ticked: newest first), services inside in today's order.
- Paging is by vessel. Which vessels are open is remembered while on the page (not stored).
- Server: `GET /api/services/` gains the grouping (`vessels: [{vessel, services}]`, count = vessels) built in
  `services.py` from the same `filtered` rows, still a fixed number of queries. The Excel export stays one row per
  service with today's columns: the export headings move to a constant the cards don't use, and
  `tests_page_excel` reads that constant.
- Text per the user's taste: compact, no help lines.

## 3. Dashboard: one view at a time

**Why:** the user wants each topic on the page by itself (like the HTML's report cards), and not everything as bars.

**Approaches:** (a) tabs, one view shown (picked); (b) everything on one long page reacting to filters — that is
today's page and what they want to move away from; (c) separate sidebar pages — clutters the nav.

**Design:**
- A row of view buttons under the toolbar: **Agent jobs · OPR · Customers · Overview**. Only the chosen view is on
  screen; the last one is remembered in this browser (`localStorage`, try/catch). From–To and Port are shared; each
  view shows only the filters that make sense for it (Agent jobs: OPR, agent, service; OPR: agent, service;
  Customers: OPR, service; Overview: all, as today).
- Each view starts with one short headline line of figures (e.g. total jobs · agents · top agent), not stat cards.
- **Agent jobs:** today's Jobs per agent (ranked horizontal bars + table; clicking an agent opens the jobs dialog as
  now).
- **OPR:** a donut of vessels per OPR (legend with counts) and a table OPR → vessels, services, jobs; today's OPR
  cards stay here.
- **Customers (new):** jobs per customer — a service's job goes to its billing party, else its ship's customer, else
  "No customer"; arrivals / sailings count for the ship's customer. A table customer → jobs, and a heat table rows =
  customer + POC (so it shows which customer works through which POC), columns = port, cell = jobs, shaded by size (port columns only when the person has several ports; else one
  column). Server: a `customers` block in `dashboard.response` (counts only, no money, so no `moneyaccess` change).
- **Overview:** today's Services per month, Money per month (with `money.view`), Service status.
- Charts drawn with `dom.js` SVG/elements and the `--c1…` tokens; no chart library. Management Excel and All data
  unchanged (a "Customers" sheet in the management Excel can come later if wanted).

## Not doing

No new permissions or pages; no change to money rules, exports' contents, or the Vessels page.

## Left to the builder

Exact spacing, colours within the tokens, the donut's small-slice "Other" grouping (more than 8 OPRs), empty states
("No data").
