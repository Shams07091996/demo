# Operation, round 2 — design

Date: 2026-11-25. Follows `2026-11-25-operation-app-design.md` (merged). The user tried the Operation pages on the
demo and asked for five changes.

## Why

The pages work, but entering a visit is slower than it should be (LOA typed every time, times in an order that does not
match how people read them), Live data shows every terminal at once, and the terminal details (lines, quay, cranes)
change over time and should be kept up to date by the people who know them, not only by Admins.

## What the user decided

1. **Times side by side.** Vessel Data's table and the visit dialog show the estimates together and the actuals
   together: **ETA, ETB, ETC**, then **ATA, ATB, ATD** (the user wrote "ATC"; the app has ATD, actual departure).
2. **Live data terminal filter.** Under the port choice, a row of buttons like the vessel list's All / ARK / MSK / Others:
   **All** plus one button per terminal of the chosen port (all the person's ports when no port is chosen). One
   terminal shows only its card.
3. **Estimate order.** A visit is refused when **ETB is before ETA** ("ETB cannot be before ETA.") or ETC before ETB
   (already refused). Same rule as the actual times: equal is allowed.
4. **Terminal details and fixed vessel LOA.**
   - New permission tick **"Edit terminals and vessel list"** (`operation.master`, needs the Vessel Data page). People
     with it add and edit terminals **in their own ports** on the Terminals page (Admins: every port, as now). The
     Terminals page moves into the Operation folder's reach: shown to Admins and to people with the tick. Off for
     existing accounts; on in the Branch manager template.
   - A terminal gets its **shipping lines**: a tick list from the Master data "Shipping line" list of its port and All
     ports. A visit's line box offers only that terminal's lines; a terminal with no lines ticked offers all of its
     port's lines. A visit keeps a line already saved on it.
   - Quay length, berth numbers, cranes: already editable on the Terminals page; nothing new.
   - **Vessel list** (separate from Marine's Ships, the user's choice): a new Operation table of vessels with **name**
     (upper-case, unique ignoring case) and **LOA** (more than 0, at most 500 m), shared by all ports. A page "Vessel
     list" in the Operation folder, for people with Vessel Data; adding / editing needs the new tick; deleting is for
     Admins only (visits keep the name and LOA as text, so deleting a list entry never changes a visit).
   - In the visit dialog, typing the vessel name offers the list's names; picking one fills the LOA (still editable,
     the visit keeps its own LOA). A name not on the list is still allowed. Nothing is added to the list automatically.
5. **Pictures on Live data.** Each terminal card shows its picture at the top, like the workbook's Dashboard banner.
   The user chose **files on the server, no upload in the app** (like the logo): one file per terminal in a folder
   `terminals/` inside the letterhead folder (`DJANGO_LETTERHEAD_DIR`), named after the terminal's code
   (`EGALY.png` or `.jpg`). Served by `GET /operation/terminal-picture/<id>/` to signed-in people who can see that
   terminal (PNG / JPEG only, checked by their first bytes, 1 MB at most); missing → the card has no picture.
   Never in git (the repository is public) and never under `static/`. I will cut the workbook's banner into five
   pictures and give them to the user (not committed). The quay / berths / cranes line keeps coming from the app, so
   it stays right when a terminal changes.

## Approaches considered

- LOA: a separate vessel list (chosen) vs. adding LOA to Ships (would fill Marine's ship list with every vessel at the
  terminals, each needing an IMO).
- Pictures: files on the server (chosen: no upload surface) vs. an upload box on the Terminals page.
- Terminal editing: a new tick (chosen) vs. Admins only.

## Left to the builder

Page layout details, the exact text of new messages beyond those above, the picture's height on the card.

## Not doing

Linking a visit to a vessel-list entry (visits keep the name as text), uploading pictures in the app, a vessel list per
port.
