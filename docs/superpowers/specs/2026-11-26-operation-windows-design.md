# Overdue vessels, vessel-list operator, distinct sidebar folders, berthing windows — design

2026-11-26. Branch `feature/operation-windows`. Four pieces, built in this order. (Separating the notifications by
Marine / Operation was raised and set aside by the user for now.)

## 1. Live data: vessels waiting past their ETA

**Why:** a vessel whose ETA has passed but that has not berthed drops out of **Next 7 days** unless someone typed an
ATA, so vessels waiting outside go missing from the screen.

**Design:** Next 7 days = every not-berthed visit (no ATB) that has arrived (ATA) **or whose ETA is before the end of
the 6th day after today** — so a passed ETA keeps it there. A passed-ETA vessel without ATA is marked **Overdue**
(`overdue: true`), one with ATA **Arrived** as today. Completed visits (ATD) and Working ones are unchanged. It stays
until someone types its ATB (or ATA / ATD); no cut-off (my call: an old forgotten visit showing is the reminder to fix
it). Server `operation/live.py`; page tag in `opLive.js` like Arrived.

## 2. Vessel list: operator next to LOA

**Why:** defining a vessel once should also give its line, so a new visit fills both.

**Design:** `ListedVessel.line` (text, 100, may be empty for existing entries; required for a new one), chosen from
the **Shipping line** values of any port (the list is per port; the vessel list is all ports), the saved value staying
allowed. Shown as **Operator** on the Vessel list page and its dialog. In the visit dialog, picking a listed vessel fills
LOA as now **and the line when that line is offered for the chosen terminal** (else the line is left as it is). The
visit keeps its own copy. Migration `operation 0004`.

## 3. Sidebar folders more distinct

**Why:** the folder names look like the pages under them and blend together.

**Design (shown to the user, adjusted on their feedback):** each folder name is a shaded band (`--side-active`) with
a light left bar, an icon (Marine anchor, Operation ship, Reports chart, Master data database), larger white text,
the chevron on the right; 14 px between folders; the pages indented under a faint left line. No capitals (the user's
2026-11-18 decision), no underline on the current folder. CSS + the four folder heads in `index.html`.

## 4. Berthing windows

**Why:** some lines have fixed weekly berthing windows at a terminal (some several, some none); when a visit is
entered the operator wants to see the nearest window for that line.

**What a window is (user's answers):** a **weekly** slot (start day + time → end day + time, Cairo time, may run over
the week's end, e.g. Sat 20:00 → Mon 06:00), tied to **a terminal and a line**. A line may have several windows at a
terminal, or none.

**Page:** **Berthing windows** in the Operation folder, below Terminals, for the same people as Terminals (Admins and
the tick **Edit terminals and vessel list**, own ports). One table: Terminal (with port when several ports), Line,
Window ("Tue 06:00 → Wed 18:00"), Length (h), and edit / delete. A Port / Terminal filter. + Add opens a dialog:
terminal (turned-on ones of the person's ports), line (that terminal's lines, i.e. its list or else every Shipping line
of its port), start day + time, end day + time. Refused, never fixed: end equal to start; a window longer than 7 days
is impossible by construction; two windows of the same terminal and line that overlap. Windows are deleted for real
(the History keeps the record). History tracks them (port = terminal's port, type in `PORT_TYPES`).

**Nearest window in the visit dialog:** under Line, once terminal, line and ETA are set: "Window: Fri 27.11 22:00 →
Sat 28.11 20:00 · ETA 14 h before" (or "ETA inside the window" / "ETA 3 h after the start"). Nearest = the window
occurrence (of every window of that terminal + line, repeated weekly) that contains the ETA, else the one whose start
is closest to the ETA, earlier or later (a tie goes to the later one). No window for the line → nothing shown. The
person reading Vessel Data does not need the edit tick: reading windows needs only the `op_vessels` page.
Worked out on the server (`operation/windows.py`, `GET /api/operation/windows/nearest/?terminal=&line=&eta=`), not
stored on the visit; the dialog asks again when terminal, line or ETA change.

**Server:** model `BerthingWindow` (terminal PROTECT, line, start_day 0–6 Mon–Sun, start_time, end_day, end_time),
migration `operation 0005`; routes `GET/POST /api/operation/windows/`, `PUT/DELETE …/<id>/` (writes:
`require_master`, scoped by the terminal's port like terminals), validation in `operation/validators.py`. No version
column (like terminals: last save wins). `seed_demo` adds a few windows (two for one line at one Alexandria
terminal, one elsewhere) so the smoke test can check the hint.

## Not doing

Notifications split by area (set aside); windows on the Vessel Data list or in its Excel; windows by date or every two
weeks; any automatic ETB from a window.

## Left to the builder

Exact wording of the hint, table spacing, the day picker (a select Mon–Sun + a time box).
