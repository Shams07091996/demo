# Deploying Marine Service Sheet — step by step

How to put the app on the company's server, create everyone's account, keep it backed up, and what happens when
something goes wrong. Work through it top to bottom and tick each box. Read `SECURITY.md` §4 (deployment checklist)
alongside it.

The steps are written for a **Windows server** (what this project is developed on). Where Linux differs, a
**Linux:** line says how.

---

## 0. The picture first

```
 People's browsers ──HTTPS──▶ Web server (IIS / nginx) ──▶ Django app (waitress / gunicorn) ──▶ PostgreSQL
                               serves /static/ itself       127.0.0.1:8000, never reachable      database
                                                             from outside
```

### Two kinds of accounts — don't mix them up

| Kind | Who has one | Where it lives | Created how |
|---|---|---|---|
| **PostgreSQL logins** | Only **three**: `postgres` (the database's own administrator), `marine_app` (the app itself), `marine_backup` (the nightly backup) | PostgreSQL | Once, with SQL (step 2) |
| **App accounts** | **Every person** who uses the site (Admins and Users) | Also stored in PostgreSQL (tables `auth_user` and `sheet_profile`), but made **through the app** | `createsuperuser` for the Admins, then the Accounts page (step 8) |

**People never get a PostgreSQL login.** They sign in to the website; the app talks to the database for them,
and only lets each person see and change what their ports allow. A person with a PostgreSQL login could bypass every
rule of the app (ports, the change history, two-step login). Never create users by writing SQL either: the
passwords are scrambled (hashed), and the ports, two-step setup and history would be skipped.

---

## 1. What you need

- [ ] **A server** the company's users can reach: Windows Server 2019 or newer (or Linux: Ubuntu / Debian).
- [ ] **A host name and an HTTPS certificate**, e.g. `sheet.company.com`. The app must be at the **root** of its own
      host (not `/sheet/`) and only on HTTPS: its cookies are `__Host-` cookies, which browsers accept only that way.
- [ ] **Python 3.11 or newer** (python.org; tick "Add python.exe to PATH" in the installer).
- [ ] **Git** (git-scm.com), to fetch the code.
- [ ] **PostgreSQL 17** (postgresql.org/download/windows). SQLite is for development only; the app refuses it in
      production.
- [ ] **IIS** with the **URL Rewrite** and **Application Request Routing (ARR)** add-ons (both free from Microsoft).
      **Linux:** nginx.
- [ ] **NSSM** (nssm.cc), to run the app as a Windows service. **Linux:** systemd (built in).
- [ ] *(Optional)* a mail server account, for security alert e-mails to the admins.

---

## 2. The database (PostgreSQL)

### 2.1 Install

- [ ] Run the PostgreSQL 17 installer. Choose a **strong password for `postgres`** and keep it in the company's
      password manager. Keep port **5432**. Untick Stack Builder.
- [ ] If the database is on the **same server** as the app (simplest): in `C:\Program Files\PostgreSQL\17\data\
      postgresql.conf` set `listen_addresses = 'localhost'`, so nothing outside the server can reach it.
- [ ] If it is on **another server**: set `ssl = on` with a real certificate, allow port 5432 in the firewall only
      from the app server, and use `DJANGO_DB_SSLMODE=verify-full` later (step 4).

### 2.2 Create the database and its three logins

Open **SQL Shell (psql)** from the Start menu (press Enter for the defaults, then type the `postgres` password), or
pgAdmin → Query Tool, and run — each password long, random and different:

```sql
CREATE ROLE marine_app LOGIN PASSWORD 'a long random password';
CREATE DATABASE marine_sheet OWNER marine_app;

CREATE ROLE marine_backup LOGIN PASSWORD 'another long random password';
GRANT pg_read_all_data TO marine_backup;     -- may read everything (for pg_dump), may change nothing
```

- `marine_app` is **not** a superuser and owns only `marine_sheet`. The app's history table refuses edits and
  deletes even from it (a database trigger, migration 0010).
- `marine_backup` can only read.

### 2.3 Allow only those logins, only with passwords

At the end of `C:\Program Files\PostgreSQL\17\data\pg_hba.conf`, make sure the lines for this database look like this
(no `trust` anywhere in the file):

```
# same server:
host     marine_sheet  marine_app     127.0.0.1/32  scram-sha-256
host     marine_sheet  marine_backup  127.0.0.1/32  scram-sha-256
# another server (replace with the app server's address):
# hostssl  marine_sheet  marine_app   10.0.0.20/32  scram-sha-256
```

- [ ] Restart PostgreSQL: Services → *postgresql-x64-17* → Restart. **Linux:** `sudo systemctl restart postgresql`.
- [ ] Encrypt the disk the database and its backups live on (BitLocker on Windows). PostgreSQL doesn't encrypt data
      on disk by itself.

---

## 3. Get the code and install it

In PowerShell **as the administrator** (the folder `C:\marine_sheet` is used below; any folder works):

```powershell
git clone https://github.com/<owner>/<repo>.git C:\marine_sheet
cd C:\marine_sheet
py -3.11 -m venv venv
venv\Scripts\activate
```

**Linux:** `git clone … /srv/marine_sheet`, `python3 -m venv venv`, `source venv/bin/activate`.

Add the program that runs Django — **once**, then commit it so every server installs exactly the same files:

```powershell
Add-Content requirements.in "waitress>=3,<4"           # Linux: gunicorn>=23,<24
pip install pip-tools
pip-compile --generate-hashes --strip-extras requirements.in -o requirements.txt
pip install --require-hashes -r requirements.txt
```

`--require-hashes` means pip refuses any file that isn't exactly the one recorded in `requirements.txt`.

---

## 4. Settings (environment variables)

The app reads its settings only from environment variables; nothing secret is in the code. `.env.example` lists
them all. **Never put the real values in git.**

| Variable | Example | What it is |
|---|---|---|
| `DJANGO_SECRET_KEY` | 60 random characters | Make one: `python -c "import secrets; print(secrets.token_urlsafe(60))"`. Never share it; changing it signs everyone out |
| `DJANGO_ALLOWED_HOSTS` | `sheet.company.com` | The host name(s) the site answers to |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://sheet.company.com` | The same, with `https://` |
| `DJANGO_DB_NAME` / `DJANGO_DB_USER` / `DJANGO_DB_PASSWORD` | `marine_sheet` / `marine_app` / … | Step 2.2 |
| `DJANGO_DB_HOST` / `DJANGO_DB_PORT` | `localhost` / `5432` | Where PostgreSQL is |
| `DJANGO_DB_SSLMODE` | `disable` (same server, `localhost` only) or `verify-full` (another server) | With `verify-full`, also `DJANGO_DB_SSLROOTCERT` = the certificate authority file |
| `DJANGO_LETTERHEAD_DIR` | `C:\marine_letterhead` | `logo.jpg`, `stamp.jpg`, `footer.jpg` for the LOG letter and master receipt, and `brand.png` (the ARKAS logo for the sidebar and sign-in page: a PNG with a see-through background, under 500 KB; without it the pages show an anchor icon). A sub-folder `terminals` holds one picture per terminal for Live data, named after its code (`EGALY.png` or `.jpg`, at most 1 MB). **Outside** the project, readable only by the app's account, never in git |
| `DJANGO_BEHIND_PROXY` | `1` | The web server tells the app the visit was HTTPS |
| `DJANGO_CLIENT_IP_HEADER` | `X-Forwarded-For` | So lock-outs, rate limits and the History see each visitor's real address |

**Never set `DJANGO_DEBUG`** on the server.

Optional:

| Variable | Default | What it does |
|---|---|---|
| `DJANGO_ADMIN_URL` | `admin/` | Move the admin pages to a private path, e.g. `ops-7f3k/` |
| `DJANGO_SESSION_IDLE_MINUTES` | `60` | Sign out after this long without activity |
| `DJANGO_ALERT_EMAILS` + `DJANGO_EMAIL_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM` | — | E-mail the admins on repeated lock-outs, refused requests or errors |
| `DJANGO_LOG_FILE` | — | Also write logs to a rotating file (10 × 10 MB) |
| `DJANGO_RATE_LIMIT_WRITES_PER_USER` / `_PER_IP` / `DJANGO_RATE_LIMIT_EXPORTS_PER_USER` | 120 / 600 / 20 per 10 min | API limits |
| `DJANGO_HSTS_PRELOAD` | `0` | Ask browsers to always use HTTPS for the whole domain (the domain owner decides) |

**Where to put them:** in the service (step 6), and — for running `manage.py` commands by hand — in a file only the
administrators can read, e.g. `C:\marine_secrets\env.ps1`:

```powershell
$env:DJANGO_SECRET_KEY = "…"
$env:DJANGO_ALLOWED_HOSTS = "sheet.company.com"
# … every variable from the table …
```

Load it in a PowerShell window with `. C:\marine_secrets\env.ps1` before any `python manage.py …` command.
**Linux:** an `EnvironmentFile=` for the systemd unit, `chmod 600`, and `set -a; . /etc/marine_sheet.env; set +a`
in the shell.

---

## 5. First setup

In PowerShell, in `C:\marine_sheet`, with `venv\Scripts\activate` and the settings loaded:

```powershell
python manage.py migrate                         # creates every table in marine_sheet
python manage.py collectstatic --noinput         # copies CSS / scripts / icons into staticfiles\
python manage.py check --deploy --database default
```

- [ ] `check --deploy` shows no errors. It warns `sheet.W002` (fewer than two superusers with Authenticator) until
      step 8.1 is done.

---

## 6. Run the app as a service

### Windows (NSSM + waitress)

```powershell
nssm install MarineSheet "C:\marine_sheet\venv\Scripts\waitress-serve.exe" "--listen=127.0.0.1:8000 config.wsgi:application"
nssm set MarineSheet AppDirectory C:\marine_sheet
nssm edit MarineSheet
```

In the window `nssm edit` opens:

- [ ] **Environment** tab: one `NAME=value` per line, every variable from step 4.
- [ ] **Log on** tab: a dedicated, non-administrator Windows account (e.g. `svc_marine`). Give that account read
      access to `C:\marine_sheet` and `C:\marine_letterhead`, and nothing else.
- [ ] **I/O** tab: point Output and Error at a log file, e.g. `C:\marine_logs\app.log`.
- [ ] Start it: `nssm start MarineSheet`. It now starts with Windows and restarts by itself if it stops.

**Linux:** a systemd unit running `venv/bin/gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 3` as a dedicated
user, `EnvironmentFile=/etc/marine_sheet.env`, `Restart=always`.

### The web server

**IIS:**

1. [ ] Install URL Rewrite and ARR. In IIS Manager → the server → *Application Request Routing Cache* → *Server Proxy
       Settings*: tick **Enable proxy**, keep "Preserve client IP in X-Forwarded-For", and Apply.
2. [ ] In an administrator PowerShell, keep the visitor's host name (needed by `DJANGO_ALLOWED_HOSTS`):
       `& $env:windir\system32\inetsrv\appcmd.exe set config -section:system.webServer/proxy -preserveHostHeader:true /commit:apphost`
3. [ ] Add a site `sheet.company.com` with an **https** binding on port 443 and the certificate. Its folder can be an
       empty folder, e.g. `C:\marine_site`.
4. [ ] Under the site, add a **virtual directory** `static` → `C:\marine_sheet\staticfiles`. On it: *HTTP Response
       Headers* → add `Cache-Control: no-cache` and `X-Content-Type-Options: nosniff`.
5. [ ] On the site, *URL Rewrite* → *View Server Variables* → add `HTTP_X_FORWARDED_PROTO`. Then put this
       `web.config` in `C:\marine_site`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="Static files" stopProcessing="true">
          <match url="^static/" />
          <action type="None" />
        </rule>
        <rule name="Django" stopProcessing="true">
          <match url="(.*)" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
          </serverVariables>
          <action type="Rewrite" url="http://127.0.0.1:8000/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

6. [ ] Add a second binding on port 80 that only redirects to `https://sheet.company.com/` (HTTP Redirect feature,
       or a separate small site).

**nginx (Linux):** the example in `README.md` ("Static files … in production"), plus `listen 443 ssl` with the
certificate and a port-80 server that returns `301 https://$host$request_uri`.

- [ ] Open `https://sheet.company.com/`: you should see the sign-in page. `http://127.0.0.1:8000` must **not** be
      reachable from other computers (only from the server itself).

---

## 7. Before people use it

- [ ] Never run `seed_demo` on this database (it is for testing only).
- [ ] Put the letterhead pictures (`logo.jpg`, `stamp.jpg`, `footer.jpg`) and the company logo `brand.png` in `DJANGO_LETTERHEAD_DIR`.
- [ ] *(Recommended)* run a **ZAP baseline scan** (zaproxy.org) against the site and fix what it reports.

The Master data, exchange rate and LOG checks come after the first admin can sign in (step 8.4).

---

## 8. Accounts for everyone

### 8.1 The Admins (superusers, on the server)

In PowerShell on the server, with the settings loaded (step 4):

```powershell
python manage.py createsuperuser
```

It asks for a username, an e-mail (optional) and a password of **at least 12 characters**. **An Admin is a
superuser**: there is no other way to be one, and the app itself never makes anyone an Admin. Keep them to the 2–3
trusted people who run the system. Then in a browser:

1. [ ] Sign in at `https://sheet.company.com/` with that username and password.
2. [ ] Scan the QR code with **Microsoft Authenticator** (any authenticator app works) and type the six-digit code —
       **within 72 hours** of creating the account.
3. [ ] **Repeat for a second superuser** (another trusted person). If one loses their phone, the other resets it.
       With only one, a lost phone means a reset on the server: `python manage.py reset_two_step <username>`.

### 8.2 Plan the list

Before typing anything, write the list (on paper or in a spreadsheet that is **not** shared by e-mail):

| Name | Username | Home port | Extra ports |
|---|---|---|---|
| e.g. Ahmed Hassan | `ahassan` | Alexandria | — |
| e.g. Mona Ali | `mali` | Port Said | Damietta |

Two kinds of people:

| Who | Sees | Can change |
|---|---|---|
| **Admin** (a superuser, 8.1) | Every port | Everything: accounts, ports, exchange rates, prices, shared (All ports) Master data, the History, the accounting **Open / Closed** switch on Calculations |
| **User** | Their **home port** and any **extra ports** an Admin gives them, and only the **pages** ticked for them | In those ports, only what their **permissions** (the "Can" ticks) allow |

Give each person only the ports they work in, and only the pages and permissions their job needs. An account with
no port can sign in but sees only "Your account has no port yet. Ask an admin."

**Templates** fill in the Pages and Can ticks in one go (you can change any tick afterwards; changing a template
later never changes people who already have an account):

| Template | Can | Pages (besides Vessels) |
|---|---|---|
| Marine employee | add / edit vessels and services, mark Completed, enter prices and costs | Services |
| Operations employee | Marine + cancel a service, customers and ships, hotels & transport bookings | Services, Hotels, Transport, Ships, Customers |
| Branch manager | all 19 | all |

The two money ticks: **Enter / edit prices and costs** shows (and lets them type) the money boxes of the forms —
services, hotel / transport prices, garbage & sludge money, customers' agreed rates, the amounts on the master
receipt; **See money (overviews)** shows vessel totals and profit, the Dashboard's money, totals rows and the money
columns of the Excel files. Without a tick the server never sends those figures, and their saves keep the money
already stored.

Some ticks need another: Calculations, Exchange rates and History need **See money (overviews)**; **Close / reopen
lines** needs the Calculations page. Vessels is always on. Everyone who had an account before this update keeps
everything until an Admin changes their ticks.

### 8.3 Create each account (Accounts page)

Only **Admins** manage accounts. Sign in to the app as an Admin: the sidebar has **Accounts** and **Ports** (nobody
else sees them). For each person on the list:

1. [ ] **+ Add account**: username (3–30 letters, digits, `.` `_` `-`; capitals don't make a new name), first and last
       name, **Home port**, any **Extra ports** (ticks; the home port's tick is always on), a **Template** (or tick
       **Pages** and **Can** yourself), and a temporary password (12+ characters, not a common one) → **Save**. Only ports that are turned on are offered. The page never makes
       anyone staff or superuser.
2. [ ] Tell the person their username and temporary password **in person or by phone** (never in the same message as
       the site's address).
3. [ ] At their first sign-in they **choose their own password**, then **set up Authenticator** — within **72 hours**
       of the account being created (the list shows "Waiting — until …"). After that it shows "Setup expired" and a
       superuser resets it (8.5).

Superuser and staff accounts are shown read-only on the Accounts page; change them in the admin pages
(`https://sheet.company.com/admin/`, or your `DJANGO_ADMIN_URL`).

### 8.3b Ports (Ports page)

The four ports (Alexandria, Port Said, Damietta, Suez) are already there. On the **Ports** page an Admin can:

- **+ Add port**: its name (2–40 characters, not the same as another port's). The app gives it a fixed key from the
  name (shown in the Key column); renaming never changes the key, so every record stays with its port.
- **Rename** a port: every screen, receipt and Excel file shows the new name at once.
- **Turn off** a port: nobody can add a new vessel, closure, Master-data value or garbage price month there, and it is
  no longer offered for new accounts. Everything already in it stays visible and editable. **Turn on** undoes it.

Ports are never deleted.

### 8.4 First admin tasks

- [ ] **Master data** (sidebar): OPR, POC, Agent, Hotel, Airport and Port values, plus **Delay reason** and **Closure
      reason**. While those two are empty, a vessel that berthed more than 2 hours late can't be saved and no port
      closure can be added.
- [ ] **Exchange rates**: this month's USD → EGP rate, and the Garbage & Sludge prices.
- [ ] **Customers** (with their agreed rates) and **Ships** (name, IMO or No IMO, OPR, customer): a new vessel
      is always for a ship, so add the regular ones before people start (anyone who edits can also add one
      from the vessel form).
- [ ] Download one **LOG** letter and one **master receipt** to check the logo, stamp and footer.

### 8.5 Day to day

| Situation | What to do |
|---|---|
| Lost or new phone | Admin pages → Users → tick the person → action **"Reset two-step login (lost phone)"** → Go. They set up Authenticator again within 72 hours. On the server: `python manage.py reset_two_step <username>` |
| Forgotten password | Admin pages → Users → the person → **Reset password** (under Password). They choose their own at the next sign-in |
| Someone leaves | **Accounts** page → the person → **Turn off**. They are signed out at once and can't sign in; **don't delete** the user: the History keeps who did what. **Turn on** brings them back |
| Change someone's ports | **Accounts** page → the person → **Home port** / **Extra ports** → Save (takes effect on their next click) |
| Password only, no Authenticator | An Admin may tick *Two-step exception* in the Profile (never for Admins). Avoid it |

Every one of these changes is itself recorded in the History (who changed which account, when, from where).

### 8.6 Looking at the accounts in PostgreSQL (read only)

To see the list from the database (e.g. for an audit), in psql connected to `marine_sheet`:

```sql
SELECT u.username, u.is_active, u.is_superuser, p.home_port, p.ports, u.last_login
FROM auth_user u LEFT JOIN sheet_profile p ON p.user_id = u.id
ORDER BY u.username;
```

Only **read** these tables. Create, change and turn off accounts on the Accounts page, never with `INSERT` / `UPDATE`.

---

## 9. Backups

### 9.1 Every night

Store the `marine_backup` password in `%APPDATA%\postgresql\pgpass.conf` of the account that runs the backup
(one line: `localhost:5432:marine_sheet:marine_backup:<password>`; readable only by that account). Then a
**Task Scheduler** task, daily, running:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h localhost -U marine_backup --format=custom `
  -f "D:\backups\marine_sheet-$(Get-Date -Format yyyy-MM-dd).dump" marine_sheet
```

**Linux:** the same `pg_dump` from cron, with `~/.pgpass` (`chmod 600`).

- [ ] Copy the dumps somewhere **away from the server** (another building or a cloud store), encrypted.
- [ ] Keep 30 daily copies at least.
- [ ] Back up separately and safely: the letterhead pictures, and the settings (the secret key included).

### 9.2 Test a restore (every few months)

```powershell
& "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres marine_restore_test
& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -U postgres -d marine_restore_test --no-owner D:\backups\marine_sheet-YYYY-MM-DD.dump
```

Point a test copy of the app at `marine_restore_test`, sign in, look at a few vessels, then drop the test database.
A backup that has never been restored is only a hope.

---

## 10. Updating to a new version

```powershell
cd C:\marine_sheet
. C:\marine_secrets\env.ps1
venv\Scripts\activate
# 1. back up first (the pg_dump command from 9.1)
git pull
pip install --require-hashes -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy --database default
nssm restart MarineSheet                          # Linux: sudo systemctl restart marine-sheet
```

`docs/STATUS.md` lists, for each change, whether it needs a migration and anything to do after it (for example
`0019_service_status`: every service already there becomes Completed; `0020_cancel_and_frozen`: nothing to do;
`0021_ships_customers`: existing vessels have no ship and keep working, add ships and customers afterwards;
`0022_service_completed_at`: nothing to do, services completed before it show their vessel date;
`0023_port`: nothing to do, the four ports become a table; `0024_profile_ports`: every port account keeps its port as
its home port, an "admin" account that isn't a superuser becomes a User of all four ports, **Read-only accounts are
turned off** (they have no port), and nobody but a superuser keeps staff status — check the Accounts page afterwards; undoing it with
`migrate sheet 0023` gives back each account's role, but not the staff flags or the turned-off accounts);
`0025_profile_permissions`: every existing account gets all 16 permissions and every page — take away on the
Accounts page what each job doesn't need; `operation 0001_initial` and `sheet 0030_option_line`: nothing to do —
the Operation pages and their two ticks start **off** for every existing account; tick them per person on the
Accounts page, add the terminals on the Terminals page and the shipping lines in Master data; `operation 0002_terminal_lines` and
`0003_listed_vessel`: nothing to do — the new tick "Edit terminals and vessel list" starts off; put the terminal
pictures in `DJANGO_LETTERHEAD_DIR\terminals`).
After an
update, people should reload the page: a page opened before it can't save edits until reloaded ("This page is out
of date. Reload it and try again.").

---

## 11. What happens if…

### …two people edit the same thing at the same time?

- **Different things** (two vessels, or two services / bookings of the same vessel) never clash: each is its own
  record, saved on its own.
- **The same vessel, service, hotel stay, transfer or port closure**: the first Save goes through. The second person's
  Save is **refused** (nothing of theirs is saved) and their dialog says who changed it, at what time and which
  fields, with two buttons: **Show their version** (reload what is saved now; what they typed is dropped) or **Save
  mine anyway** (their dialog's values replace the other person's). Typed values stay in the dialog until they choose.
  The same happens with two windows of the same person ("in another window"), and after an admin-page edit.
- Each save is complete or not at all (one database transaction per save), so a record is never half one person's
  and half the other's. The **History** page (admins) keeps every save — who, when, from where, old → new.
- Not covered by the warning: the Garbage & Sludge boxes, exchange rates, disposal prices, Master data and accounts
  (there the last save wins, both in the History).
- If one person **deletes** a vessel while the other has it open, the other's save answers "not found" and changes
  nothing.
- Screens don't refresh by themselves: someone sees another person's change when their list reloads (changing a
  filter, saving, or reloading the page).

### …the database stops (crash, restart, network cut)?

- While it is down, pages that need data answer **"Something went wrong (reference …)"**; a save shows **Failed** and
  its dialog stays open with what was typed. **Nothing is half-saved**: the database undoes an unfinished save.
  Sign-in doesn't work until it is back.
- Writes are refused (rather than let through) if the rate-limit counter can't be read; reads go on as long as the
  database answers.
- Each error is written to the app's log with its reference (and e-mailed to the admins when alerts are set up).
- When the database is back, the app **reconnects by itself** (no restart needed). People press Save again.

### …the app or the whole server restarts?

The service starts again by itself (NSSM / systemd). People who were signed in stay signed in (sessions are in the
database) unless they were idle longer than `DJANGO_SESSION_IDLE_MINUTES`. A save that was in flight at that moment
either finished or didn't happen at all.

### …the disk dies or the database is damaged?

Restore the last nightly backup (9.2, into the real database name), then start the app. **Work done since that
backup is lost** — with nightly backups, up to one day. If that is too much, ask whoever runs the server for
continuous archiving (PostgreSQL "WAL archiving / point-in-time recovery") or a managed PostgreSQL with automatic
backups and a standby copy; the app needs no change for either.
