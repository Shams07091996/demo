# Accounts page — design

Date: 2026-11-24. Status: written, waiting for the user's approval.

## Why

Today accounts are made only by superusers in Django's admin pages (`DEPLOYMENT.md` 8.3): Users → Add user, then
the Role in the Profile inline, with Staff / Superuser boxes that must be left off. It works, but it is easy to get
wrong and it hands the person doing it the whole admin site. The company is about to set up everyone's account on
its server and will keep adding people as they join.

The user wants a page **inside the app** where a few trusted people (about **3**) do the day-to-day account work:

- **add a person when they join**,
- **change their role or port**,
- **turn off** someone who leaves (and turn them back on).

## Who may use it (the user's decision: option A)

**Superusers only.** The ~3 people who run the page are superusers. Everyone else — ordinary admins, port users,
the read-only accountants — never sees the page, and the server refuses its routes (403) whatever they send.
No new permission flag is added.

## Goals

- One list of every account and one dialog to add or change one.
- Every rule enforced on the server; the page only shows what the server allows.
- Every change in the History (who changed which account, when, from where), as today.
- The page can later grow into the access rework (below) without being thrown away.

## Non-goals (for now)

- **The access rework** the user plans next, as its own project: *Admins* (full power) and *Users* (limited, by
  port); admins **add ports** (ports stop being the fixed list in `constants.PORTS`); admins give a specific agent
  **extra ports** to see. Then the role box in this page becomes "Admin / User + home port + extra ports" and the
  page gains an "Add port" part. Nothing in this design may make that harder; nothing of it is built now.
- Resetting a password or a lost phone (two-step reset), the two-step exception, Staff / Superuser status, e-mail
  addresses, deleting accounts: these stay in the admin pages / `reset_two_step` command as today.
- Exporting the accounts list (names are personal data; no Excel).

## Anti-goals (a failure even if it works)

- Anyone who is not a superuser can read or change accounts through it.
- It can create or promote a superuser or staff user, or change a superuser's / staff user's account at all.
- A superuser can lock themselves (or the company) out with it.
- A password is ever shown back, stored in plain text, logged, or put in the History.
- A turned-off person keeps working in an open browser.

## Approaches (the user picked A)

- **A. A new page inside the app** (picked): a sidebar item for superusers only, its own list and dialog built like
  every other page, served by `/api/accounts/` routes that check for a superuser on every call. Its rules are ours, so
  it can refuse what is dangerous, and it is where the access rework will grow.
- **B. Trim Django's admin User page** to these fields: least work, but it keeps the admin pages' look and
  address, those pages still offer everything else, and the rework can't build on it.
- **C. A separate server-rendered form page**: not simpler than A here, and the only page of its kind. Dropped.

## What the page does

### The list

Sidebar item **Accounts** (after History; icon `i-key` — builder may pick another sprite icon), rendered in the
template only for superusers (like History for admins). A table, every account, turned-on ones first, then by
username:

| Username | Name | Role | Two-step | Last sign-in | State |
|---|---|---|---|---|---|

- **Role**: Admin / Read-only / the port's label. A superuser shows "Admin · Superuser", a staff user "… · Staff".
- **Two-step**: "Set up", "Waiting — until dd.mm.yyyy HH:MM" (inside the 72-hour window), "Setup expired" (needs a
  reset in the admin pages), "Exception" (password only).
- **Last sign-in**: Cairo time, "—" if never.
- **State**: On / Off; turned-off rows greyed.
- A row opens the dialog. A **+ Add account** button opens it empty. No search box (the company has a few dozen
  people); no paging (my call: one request, every account; revisit if it passes a few hundred).

### Add an account (dialog)

Fields: **Username**, **First name**, **Last name**, **Role** (Admin / Read-only / each port; Read-only preselected,
the least privilege, as today), **Temporary password** (typed twice is not needed: a show/hide toggle instead).

On save the server:
- checks the username: required, 3–30 characters, letters / digits / `.` `_` `-`, unique **ignoring case**
  (`Ahassan` is refused when `ahassan` exists);
- checks the names: optional, 150 characters each (Django's limit);
- checks the role is one of `constants.ROLES`;
- checks the password with Django's own validators (`AUTH_PASSWORD_VALIDATORS`: 12+ characters, not common, not
  all digits, not like the username / names) and refuses it with their messages;
- creates the user (`is_active=True`, never staff, never superuser) and the Profile with that role. The existing
  signal then marks **must change password** (someone else set it) and the Profile's default gives the **72-hour
  setup window** — exactly what the admin pages do today.

The person then signs in with the temporary password, chooses their own, and sets up Authenticator within 72 hours.
The superuser tells them the password in person or by phone (DEPLOYMENT.md wording stays).

### Change an account (same dialog)

- **Username**: shown, not editable (my call: it is how the History and the agents' names refer to people).
- **First / last name**: editable.
- **Role**: editable. Takes effect on the person's next click (the Profile is read on every request).
- **Turn off / Turn on** button in the dialog.
- No password field (resets stay in the admin pages).

### Turn off / turn on

- **Turn off** sets `is_active=False`. Django then treats the person as signed out on their next request (its
  session check refuses inactive users), so an open browser stops working at once; their remembered computers are
  deleted too. Nothing they did is touched: their name stays on records and in the History.
- **Turn on** sets `is_active=True`. If their 72-hour setup window ran out meanwhile they will be blocked at the
  setup step and need a two-step reset in the admin pages (the list's "Setup expired" says so).

## Server rules (all refused with a plain message, nothing saved)

1. Every `/api/accounts/` route: the signed-in user must be a **superuser** (two-step passed, which the middleware
   already guarantees); otherwise 403, logged like other 403s.
2. **Superuser and staff accounts are read-only on the page**: no role change, no turning off, no name change
   (they are managed in the admin pages). This also covers "can't change or turn off yourself", since every user
   of the page is a superuser.
3. The page never sets `is_staff` / `is_superuser`, whatever is sent (whitelisted keys only, `validators.py`).
4. A role of **Admin** on an account with the two-step exception is refused (the existing `Profile.clean` rule,
   message `EXEMPT_REFUSED`).
5. Input goes through a new cleaner in `validators.py` (refused, never silently fixed), like every other write.
6. Writes count against the normal API write rate limits; each change is audited (`api.audit`) and recorded in the
   History by the existing User / Profile signals (no password hash, no last_login).
7. Two superusers changing the same account at once: last save wins (my call — single short fields, three people;
   no `version` column). The History shows both.

## API

- `GET /api/accounts/` → `{"accounts": [{id, username, first_name, last_name, role, superuser, staff, active,
  two_step: "set_up" | "waiting" | "expired" | "exempt", setup_until (Cairo local), last_login (Cairo local)}],
  "roles": [[key, label], ...]}`.
- `POST /api/accounts/` `{username, first_name, last_name, role, password}` → 201 with the account.
- `PUT /api/accounts/<id>/` `{first_name, last_name, role, active}` (keys absent = kept) → 200 with the account.
- All through `api.json_api`; superuser check first in each.

## Docs to update

`DEPLOYMENT.md` 8.3 / 8.5 (accounts are now made on the Accounts page; resets, exception and superusers stay in the
admin pages), `CLAUDE.md` (an Accounts paragraph), `STATUS.md`, README / SECURITY test counts, `SECURITY.md`
(who may manage accounts).

## Left to the builder

The module split (e.g. `accounts.py` for the rules and the row, views in `views.py` or a small `views_accounts.py`),
exact messages, the icon, the table's look within the existing tokens, test layout (`sheet/tests_accounts.py`;
smoke test: alex and viewer don't see the item and get 403; `seed_demo`'s `admin` user is already a superuser and
staff, so it runs the page), and how the dialog shows the password rules (no help text: the server's message
says what is wrong).
