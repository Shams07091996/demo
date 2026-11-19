# Hosting a demo

Three ways to show the app. Pick the one that fits the demo.

| | A. From your own PC | B. On PythonAnywhere | C. On your own server |
|---|---|---|---|
| Who can open it | only you (screen share or meeting) | anyone with the link and a demo password | anyone with the link and a demo password |
| Time to set up | about 5 minutes | about 30 minutes | about an hour |
| Cost | free | free plan | a server and a domain name |
| Needs | nothing new | a free PythonAnywhere account | a Linux server, a domain, gunicorn and Caddy |
| Address | `http://127.0.0.1:8000` | `https://<your-name>.pythonanywhere.com` | `https://demo.yourcompany.com` |

**To show the boss over the internet, use B.** C is the rehearsal for the real production setup.

Never use your real database (`marine_sheet` on PostgreSQL 17) for a demo.

---

## A. Show it from your own PC

This runs the app in development mode on your machine only (`127.0.0.1`), with its own throwaway database file.

In PowerShell, from the project folder:

```powershell
venv\Scripts\activate
$env:DJANGO_DEBUG = "1"
$env:DJANGO_DB_PATH = "$env:TEMP\marine_demo.sqlite3"
python manage.py migrate
python manage.py seed_demo --password "pick-a-long-demo-password"
python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in as one of the demo users. They all share the password you chose:

| User | What they see |
|---|---|
| `admin` | everything, plus Master data, exchange rates and History |
| `viewer` | every port, read-only |
| `alex` | Alexandria only, can edit |
| `portsaid`, `damietta`, `suez` | that port only |

When the demo is over, stop the server with Ctrl+C and delete `marine_demo.sqlite3` from your Temp folder.

Don't open development mode to other computers (`runserver 0.0.0.0`). It is for one person on one machine: it shows
error details and has no HTTPS. For other people, use B or C.

---

## B. Put it on PythonAnywhere (free)

PythonAnywhere is a hosting service made for Python apps. It runs Django by itself (no gunicorn or Caddy needed),
serves the CSS/JS files, and gives you HTTPS on `https://<your-name>.pythonanywhere.com`. The free plan has no
PostgreSQL, so the demo uses the app's built-in database file (SQLite) with the made-up demo vessels.

In the steps below, replace **`yourname`** with your PythonAnywhere user name everywhere.

### 1. Make the upload file (on your PC)

In the project folder, this packs exactly what is in git (no `venv`, no database, no `node_modules`, no secrets):

```bash
git archive --format=zip -o marine_sheet.zip HEAD
```

### 2. Create the account

Sign up at pythonanywhere.com for a free "Beginner" account. Your user name becomes the address
(`yourname.pythonanywhere.com`), so choose one you're happy for the boss to see.

### 3. Upload and unpack

- Open the **Files** page and upload `marine_sheet.zip` into your home folder (`/home/yourname`).
- Open the **Consoles** page and start a **Bash** console. In it:

```bash
unzip marine_sheet.zip -d marine_sheet && rm marine_sheet.zip
cd ~/marine_sheet
python3.11 -m venv venv
venv/bin/pip install --require-hashes -r requirements.txt
```

If `python3.11` is not found, use the newest one they offer (`python3.12`, `python3.13`).

### 4. The settings file

Make a secret key, then create the settings file with the editor built into the console:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
nano ~/marine.env
```

Paste this, put the secret key in the first line, and save (Ctrl+O, Enter, Ctrl+X):

```ini
DJANGO_SECRET_KEY=paste-the-secret-key-here
DJANGO_ALLOWED_HOSTS=yourname.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourname.pythonanywhere.com
DJANGO_ALLOW_SQLITE=1
DJANGO_DB_PATH=/home/yourname/marine_demo.sqlite3
DJANGO_BEHIND_PROXY=1
DJANGO_CLIENT_IP_HEADER=X-Forwarded-For
DJANGO_ADMIN_URL=private-admin-path/
DJANGO_HSTS_SECONDS=3600
```

No quotes and no spaces around `=`. Then lock it so only you can read it:

```bash
chmod 600 ~/marine.env
```

### 5. Database, demo users, CSS/JS files

Still in the Bash console:

```bash
cd ~/marine_sheet
set -a; . ~/marine.env; set +a
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py seed_demo --force --password "a-long-demo-password"
venv/bin/python manage.py check --deploy
```

`check --deploy` should report no issues. `seed_demo` lists the demo users: `admin`, `viewer`, `alex`, `portsaid`,
`damietta` and `suez`, all with the password you gave.

### 6. The web app

Open the **Web** page and click **Add a new web app**:

1. Confirm the address `yourname.pythonanywhere.com`.
2. Choose **Manual configuration** (not "Django"), then the same Python version as in step 3.

On the web app's page, set:

- **Virtualenv:** `/home/yourname/marine_sheet/venv`
- **Source code** and **Working directory:** `/home/yourname/marine_sheet`
- **Static files:** add one line, URL `/static/`, Directory `/home/yourname/marine_sheet/staticfiles`
- **Force HTTPS:** on

Then click the **WSGI configuration file** link (`/var/www/yourname_pythonanywhere_com_wsgi.py`), delete everything in
it, paste this and save:

```python
import os
import sys
from pathlib import Path

APP = "/home/yourname/marine_sheet"
if APP not in sys.path:
    sys.path.insert(0, APP)

# The settings live in ~/marine.env (readable only by you), not in this file.
for line in Path("/home/yourname/marine.env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
```

Back on the **Web** page, click **Reload**.

### 7. Try it before you send the link

Open `https://yourname.pythonanywhere.com/` and check:

- The sign-in page looks right (colours and icons load). If it looks unstyled, the Static files line in step 6 is
  wrong.
- `admin` sees every page, including History. `alex` sees only Alexandria vessels. `viewer` cannot edit.
- `https://yourname.pythonanywhere.com/admin/` says "not found" (the admin lives at your private path).
- **Visitors' addresses:** sign in as `admin`, change something, and open **History**. The change should show your own
  internet address, not one shared by everyone. The sign-in lock-out counts failed attempts by that address.

If something fails, the **Web** page has an **Error log** link. Send me its last lines.

- **"Bad Request (400)":** the address in `DJANGO_ALLOWED_HOSTS` does not match the one in the browser.
- **The page keeps reloading itself ("too many redirects"):** add `DJANGO_SSL_REDIRECT=0` to `~/marine.env` and click
  **Reload**. "Force HTTPS" from step 6 still keeps everyone on HTTPS.

### 8. Send it to the boss

Send the link, one user name (for example `admin` or `viewer`) and the password. If you can, send the password a
different way from the link. Every demo user has the same password, so name only the users you want the boss to try.

### 9. Keep it, update it, remove it

- **Free plan upkeep:** PythonAnywhere e-mails you every three months. Click **Run until 3 months from today** on the
  Web page or the site switches off.
- **Update to a newer version:** make a new zip (step 1), upload it, then in a Bash console:

  ```bash
  rm -rf ~/marine_sheet_old && mv ~/marine_sheet ~/marine_sheet_old
  unzip marine_sheet.zip -d marine_sheet && rm marine_sheet.zip
  mv ~/marine_sheet_old/venv ~/marine_sheet/venv
  cd ~/marine_sheet && venv/bin/pip install --require-hashes -r requirements.txt
  set -a; . ~/marine.env; set +a
  venv/bin/python manage.py migrate && venv/bin/python manage.py collectstatic --noinput
  venv/bin/python manage.py seed_demo --force
  ```

  Then click **Reload** on the Web page. `seed_demo` again only adds what is new (for example the Delay reason and
  Closure reason lists); it never changes existing users, passwords or vessels.
- **Two-step login (since 2026-11-18):** every demo user signs in with a Microsoft Authenticator code too. At the
  first sign-in after the update, each person scans the QR code shown and types the 6-digit code. They have 72 hours
  from the update (or from when the account was made); after that they are blocked until reset:
  `venv/bin/python manage.py reset_two_step <username>` (in the Bash console, after the `set -a` line). A lost phone
  is reset the same way.
- **When the demo is over:** delete the web app on the Web page, and delete `marine_demo.sqlite3` and `marine.env`.
- **Demo data only.** No real crew names or passports. Real data waits for the production setup in `SECURITY.md` §4.

---

## C. Put it on your own server

The app is built for production: it refuses to start without HTTPS settings, a secret key and PostgreSQL. A demo
server follows the same rules, so it is also a rehearsal for the real setup.

**Parts:**

- **A small Linux server.** Ubuntu 24.04 with 1–2 GB of RAM is enough. It can be any cloud provider or a machine at the
  office.
- **A domain name** pointing at the server, e.g. `demo.yourcompany.com`. HTTPS needs a name, not a bare IP address.
- **PostgreSQL**, on the same server.
- **gunicorn**, the program that runs the Django app.
- **Caddy**, the front door. It gets the HTTPS certificate on its own, serves the CSS/JS files and passes everything
  else to gunicorn.

gunicorn and Caddy are new third-party programs, so whether to use them is your call. gunicorn is not in
`requirements.txt` yet. If you go ahead, it should be added to `requirements.in` and the lock rebuilt, so the server
installs it hash-checked like everything else.

### 1. Server basics

```bash
sudo apt update && sudo apt install -y python3 python3-venv postgresql git
sudo adduser --system --group --home /srv/marine marine
```

Turn on the firewall and open only SSH, HTTP and HTTPS. PostgreSQL stays closed to the outside.

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

### 2. The database

Create a database owned by a user that can only use that database (not a superuser):

```bash
sudo -u postgres psql -c "CREATE ROLE marine_demo LOGIN PASSWORD 'a-long-random-password';"
sudo -u postgres psql -c "CREATE DATABASE marine_demo OWNER marine_demo;"
```

Ubuntu's PostgreSQL has encryption (SSL) switched on by default, so the app's default `DJANGO_DB_SSLMODE=require`
works as it is.

### 3. The app

Copy the project to `/srv/marine/app` with `git clone`, or by copying the folder without `venv`, `db.sqlite3` and
`node_modules`. Then:

```bash
cd /srv/marine/app
python3 -m venv venv
venv/bin/pip install --require-hashes -r requirements.txt
```

Create the settings file `/srv/marine/env` (only the `marine` user may read it: `chmod 600`, `chown marine`):

```ini
DJANGO_SECRET_KEY=<paste a long random value: python3 -c "import secrets; print(secrets.token_urlsafe(50))">
DJANGO_ALLOWED_HOSTS=demo.yourcompany.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://demo.yourcompany.com
DJANGO_BEHIND_PROXY=1
DJANGO_CLIENT_IP_HEADER=X-Forwarded-For
DJANGO_DB_NAME=marine_demo
DJANGO_DB_USER=marine_demo
DJANGO_DB_PASSWORD=a-long-random-password
DJANGO_DB_HOST=localhost
DJANGO_ADMIN_URL=private-admin-path/
DJANGO_HSTS_SECONDS=3600
```

`DJANGO_HSTS_SECONDS=3600` keeps the "HTTPS only" rule short in visitors' browsers while it is a demo. Production
leaves it at the default (one year).

Load those settings, then set up the database, collect the CSS/JS files and run the checks:

```bash
set -a; . /srv/marine/env; set +a
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py check --deploy
```

`check --deploy` must report no issues.

Demo users and demo vessels: `seed_demo` refuses to run in production unless you add `--force`. That's on purpose,
and fine on a demo server:

```bash
venv/bin/python manage.py seed_demo --force --password "a-long-demo-password"
```

### 4. Keep the app running (gunicorn)

Once gunicorn is installed in the venv, create `/etc/systemd/system/marine.service`:

```ini
[Unit]
Description=Marine Service Sheet
After=network.target postgresql.service

[Service]
User=marine
WorkingDirectory=/srv/marine/app
EnvironmentFile=/srv/marine/env
ExecStart=/srv/marine/app/venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now marine
```

gunicorn listens only on `127.0.0.1`, so nobody can reach it except through Caddy. This matters: the app trusts the
`X-Forwarded-For` header to learn each visitor's address for its sign-in limits and change history.

### 5. The front door with HTTPS (Caddy)

Install Caddy from its official instructions (caddyserver.com/docs/install). Then write `/etc/caddy/Caddyfile`:

```
demo.yourcompany.com {
    handle_path /static/* {
        root * /srv/marine/app/staticfiles
        file_server
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
```

```bash
sudo systemctl reload caddy
```

Caddy gets and renews the HTTPS certificate by itself. It adds the visitor's real address to `X-Forwarded-For`.

Open `https://demo.yourcompany.com/` and sign in as one of the demo users (the same list as in A).

### 6. Check it is safe before you share it

- Plain `http://` sends you to `https://`.
- `https://demo.yourcompany.com/admin/` gives "not found" (the admin lives at your private path).
- Five wrong passwords for one user lock that user out from your address for 15 minutes.
- Sign in as `alex`: only Alexandria vessels are shown.

### 7. After the demo

- Change the demo password, or delete the demo users from the admin page.
- Or remove it all: `sudo systemctl disable --now marine caddy` and drop the `marine_demo` database.
- Don't type real crew names or passports into the demo server. Real data waits for the production setup in
  `SECURITY.md` §4: verified database encryption, encrypted disk and backups, alert e-mails.

### Updating the demo to a newer version

```bash
cd /srv/marine/app && git pull   # or copy the new files
venv/bin/pip install --require-hashes -r requirements.txt
set -a; . /srv/marine/env; set +a
venv/bin/python manage.py migrate && venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart marine
```
