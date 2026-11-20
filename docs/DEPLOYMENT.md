# Deploying Marine Service Sheet

How to put the app on a real server and set up the people who use it. Read `SECURITY.md` §4 (deployment checklist)
alongside this. Commands are shown for **Linux**; the Windows equivalent is given where it differs.

## 1. What you need

| Item | Notes |
|---|---|
| A server | Linux (Ubuntu / Debian) or Windows Server, reachable by the company's users |
| A host name and an HTTPS certificate | e.g. `sheet.company.com`. The app must be served from the **root** of its own host (not `/sheet/`) and only over HTTPS: its cookies are `__Host-` cookies, which browsers accept only that way |
| Python 3.11 or newer | The app is tested on 3.11 |
| PostgreSQL 17 | The full test suite passes on it. SQLite is for development only; the app refuses it in production |
| A program that runs Django | **Not included yet** — choose one: **gunicorn** (Linux) or **waitress** (Windows). Add it to `requirements.in` and rebuild the hash-locked `requirements.txt` (step 3) |
| A web server in front | nginx (Linux) or IIS (Windows): HTTPS, the static files, and passing the rest to Django |
| A mail server (optional) | For security alerts to the admins |

## 2. The database

On the PostgreSQL server, as the `postgres` superuser:

```sql
CREATE ROLE marine_app LOGIN PASSWORD 'a long random password';
CREATE DATABASE marine_sheet OWNER marine_app;
```

- `marine_app` is **not** a superuser and owns only this database.
- PostgreSQL: `ssl = on` with a real certificate; in `pg_hba.conf` only `hostssl` lines with `scram-sha-256` (no
  `trust`); listen only where needed and firewall port 5432.
- Encrypt the disk the database and its backups live on (PostgreSQL does not encrypt data on disk by itself).

## 3. Get the code and install it

```bash
git clone https://github.com/<owner>/<repo>.git /srv/marine_sheet
cd /srv/marine_sheet
python3 -m venv venv
source venv/bin/activate                      # Windows: venv\Scripts\activate
```

Add the program that runs Django (once; gunicorn on Linux, waitress on Windows), then rebuild the lock:

```bash
echo "gunicorn>=23,<24" >> requirements.in    # or: waitress>=3,<4
pip install pip-tools
pip-compile --generate-hashes --strip-extras requirements.in -o requirements.txt
pip install --require-hashes -r requirements.txt
```

Commit the changed `requirements.in` / `requirements.txt` so every server installs exactly the same files.

## 4. Settings (environment variables)

The app reads its settings from environment variables only; nothing secret goes in the code. `.env.example` lists
them all. Put them where the service starts (a systemd unit's `Environment=` / `EnvironmentFile=`, or the Windows
service's environment), readable only by the account that runs the app.

**Required**

| Variable | Example | What it is |
|---|---|---|
| `DJANGO_SECRET_KEY` | (60 random characters) | `python -c "import secrets; print(secrets.token_urlsafe(60))"`. Never share it; changing it signs everyone out |
| `DJANGO_ALLOWED_HOSTS` | `sheet.company.com` | The host name(s) the site answers to |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://sheet.company.com` | The same, with `https://` |
| `DJANGO_DB_NAME` / `DJANGO_DB_USER` / `DJANGO_DB_PASSWORD` | `marine_sheet` / `marine_app` / … | The database from step 2 |
| `DJANGO_DB_HOST` / `DJANGO_DB_PORT` | `db.internal` / `5432` | Where PostgreSQL is |
| `DJANGO_DB_SSLMODE` / `DJANGO_DB_SSLROOTCERT` | `verify-full` / `/etc/ssl/certs/db-ca.pem` | Encrypted and verified database connection |
| `DJANGO_LETTERHEAD_DIR` | `/srv/letterhead` | Folder with `logo.jpg`, `stamp.jpg`, `footer.jpg` for the LOG letter; **outside** the project, readable only by the app's account, never in git |

**Never set `DJANGO_DEBUG`** on the server (debug mode is off unless it is `1`).

**Behind nginx / IIS** (the usual case)

| Variable | Value |
|---|---|
| `DJANGO_BEHIND_PROXY` | `1` (trust the web server's "this was HTTPS" header) |
| `DJANGO_CLIENT_IP_HEADER` | `X-Forwarded-For` (so lock-outs, rate limits and the history see each visitor's real address) |

Make sure nobody can reach the Django program directly, only through the web server.

**Optional**

| Variable | Default | What it does |
|---|---|---|
| `DJANGO_ADMIN_URL` | `admin/` | Move the admin pages to a private path, e.g. `ops-7f3k/` |
| `DJANGO_SESSION_IDLE_MINUTES` | `60` | Sign out after this long without activity |
| `DJANGO_ALERT_EMAILS` + `DJANGO_EMAIL_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM` | — | E-mail the admins on repeated lock-outs, refused requests or errors |
| `DJANGO_LOG_FILE` | — | Also write logs to a rotating file (10 × 10 MB) |
| `DJANGO_RATE_LIMIT_WRITES_PER_USER` / `_PER_IP` / `DJANGO_RATE_LIMIT_EXPORTS_PER_USER` | 120 / 600 / 20 per 10 min | API limits |
| `DJANGO_HSTS_PRELOAD` | `0` | Ask browsers to always use HTTPS for the whole domain (the domain owner decides) |

## 5. First setup

With the environment variables set:

```bash
python manage.py migrate                      # creates every table
python manage.py collectstatic --noinput      # copies CSS / scripts / icons into staticfiles/
python manage.py check --deploy --database default
```

`check --deploy` must show no errors. Right after setup it warns `sheet.W002` (fewer than two superusers with an
Authenticator); that goes away after step 7.

## 6. Run it

**The Django program** (listens only on the server itself):

```bash
# Linux
gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 3
# Windows
waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

Run it as a service that restarts by itself (a systemd unit on Linux; NSSM or the Task Scheduler on Windows), under
an account that is not an administrator.

**The web server**: HTTPS on port 443 (and port 80 redirecting to it), `/static/` from the `staticfiles/` folder with
`Cache-Control: no-cache`, everything else passed to `127.0.0.1:8000`. The nginx example is in `README.md`,
"Static files … in production"; for IIS, use URL Rewrite + Application Request Routing to pass requests on, and a
virtual directory for `/static`.

Open `https://sheet.company.com/` — you should see the sign-in page.

## 7. Creating users

### The first superuser (on the server)

```bash
python manage.py createsuperuser
```

It asks for a username, e-mail (optional) and a password of **at least 12 characters**. A superuser gets the
**admin** role automatically. Then, in a browser:

1. Sign in at `https://sheet.company.com/` with that username and password.
2. Scan the QR code with **Microsoft Authenticator** (any authenticator app works) and type the six-digit code. This
   must be done **within 72 hours** of creating the account.

**Create a second superuser the same way and set up their Authenticator too.** If one loses their phone, the other
can reset it. With only one, a lost phone means a reset on the server (`python manage.py reset_two_step <username>`).

### Everyone else (in the admin pages)

Only superusers can manage accounts. Go to `https://sheet.company.com/admin/` (or your `DJANGO_ADMIN_URL`):

1. **Users → Add user.** Type the username and a temporary password (12+ characters), then **Save**.
2. On the next page, under **Profile**, choose the **Role** (table below), then **Save**.
   Leave *Staff status* and *Superuser status* off for normal users: those open the admin pages.
3. Give the person their username and temporary password (in person or by phone, not in the same e-mail as the
   address of the site).
4. At their first sign-in they must **choose their own password**, then **set up Authenticator** — within **72 hours**
   of the account being created. After that the link expires and a superuser has to reset it.

| Role | Sees | Can change |
|---|---|---|
| **Admin** | All ports | Everything, including exchange rates and shared Master data |
| **Read-only** | All ports, money included | Nothing (new accounts start here) |
| **Alexandria / Port Said / Damietta / Suez** | Their port only | Their port's vessels, services, bookings, closures and Master data |

### Day-to-day

| Situation | What to do |
|---|---|
| Lost or new phone | Admin pages → Users → tick the person → action **"Reset two-step login"** → Go. They set up Authenticator again within 72 hours. (On the server: `python manage.py reset_two_step <username>`) |
| Forgotten password | Admin pages → Users → the person → **Reset password** (under Password). They must choose their own at the next sign-in |
| Someone leaves | Untick **Active** on their user and Save. Don't delete the user: the change history keeps who did what |
| Change what someone may do | Change the **Role** in their Profile |
| Password only, no Authenticator | A superuser may tick *Two-step exempt* in the Profile, for non-admin users only. Avoid it |

## 8. Before people start using it

- Delete any demo users (`seed_demo` is for testing only; never run it on the real database).
- **Master data** (sidebar): add the OPR, POC, Agent, Hotel, Airport and Port values, and **Delay reason** and
  **Closure reason**. While those last two are empty, a vessel that berthed more than 2 hours late can't be saved and
  no port closure can be added.
- **Exchange rates**: add the current month's USD → EGP rate.
- Put the LOG pictures in `DJANGO_LETTERHEAD_DIR` and download one LOG to check the logo, stamp and footer.
- Run a **ZAP baseline scan** (zaproxy.org) against the server before it goes live, and fix what it reports.

## 9. Updating to a new version

```bash
cd /srv/marine_sheet
git pull
source venv/bin/activate
pip install --require-hashes -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy --database default
# then restart the service (systemctl restart marine-sheet, or restart the Windows service)
```

Take a database backup before `migrate`.

## 10. Backups

- Every night: `pg_dump --format=custom marine_sheet > marine_sheet-YYYY-MM-DD.dump`, stored encrypted and away from
  the server.
- Keep the `DJANGO_LETTERHEAD_DIR` pictures and the environment settings (secret key included) backed up separately
  and safely.
- **Test a restore** now and then (`pg_restore` into an empty database, point a test copy of the app at it, sign in).
