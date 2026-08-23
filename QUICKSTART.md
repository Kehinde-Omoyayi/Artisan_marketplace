# Quick start — see it working in 5 minutes

Two paths. Docker needs nothing installed; the manual path follows the V2 manual's own
Part 3.

---

## Path A — Docker (recommended for a first look)

```bash
unzip artisan_marketplace_v2.zip
cd artisan_marketplace_v2
docker compose up
```

Wait for `Starting development server at http://0.0.0.0:8000/`, then open:

- **http://localhost:8000/** — the interactive test console
- **http://localhost:8000/admin/** — Django admin

Create the admin login in a second terminal:

```bash
docker compose exec web python manage.py createsuperuser
```

Compose already runs `migrate` and `bootstrap_v2` for you, and brings up PostGIS, Redis,
the web server, a Celery worker and Celery beat — the manual's four terminals in one
command.

---

## Path B — Local install

**1. System libraries.** GDAL/GEOS/PROJ are OS libraries, not pip packages.

```bash
# Ubuntu / Debian / WSL2
sudo apt-get update
sudo apt-get install -y binutils libproj-dev gdal-bin libgdal-dev redis-server postgresql postgresql-postgis

# macOS
brew install gdal geos proj redis postgresql postgis && brew services start redis
```

Verify: `gdal-config --version` prints a version, `redis-cli ping` prints `PONG`.
If `gdal-config` is not found, stop and fix that first — nothing else will work.

**2. Python.**

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**3. Database.** Point `DATABASE_URL` in `.env` at your Supabase project, or create a
local one:

```bash
sudo -u postgres psql -c "CREATE USER artisan WITH PASSWORD 'artisan' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE artisan_v2 OWNER artisan;"
sudo -u postgres psql -d artisan_v2 -c "CREATE EXTENSION IF NOT EXISTS postgis;"
# then in .env:
# DATABASE_URL=postgis://artisan:artisan@localhost:5432/artisan_v2
```

**4. Migrate, bootstrap, run.**

```bash
python manage.py migrate
python manage.py bootstrap_v2        # FeeConfig, Beat schedule, RBAC groups, categories
python manage.py createsuperuser
python manage.py runserver
```

Open **http://127.0.0.1:8000/**.

For the background jobs, in two more terminals:

```bash
celery -A config worker --loglevel=info
celery -A config beat   --loglevel=info
```

---

## What to click

On the console home page, press **“Run everything, in order.”** It seeds artisans, walks
a customer through the WhatsApp flow, onboards an artisan, approves their ID, moves
money both below and above the approval threshold, raises a dispute, and attacks both
webhooks — printing exactly what the backend did at each step.

Then try these, which are the most revealing:

| Try | What you should see |
|---|---|
| Money flow at `20000`, then `75000` | Below ₦50,000 auto-approves; ₦50,000+ is **held** for `finance_staff` |
| Customer area → *Ibadan (far away)* | Lagos artisans disappear — the 15 km PostGIS radius filter |
| Category → *Electrical* | Artisans below L2 are excluded outright (high-risk gate) |
| Rank #4 in a default run | A 5.0★/1-job artisan at 0 km **loses** to a 4.6★/80-job artisan — sample-size damping |
| “Attack the webhooks” | Five unsigned/forged requests, all rejected 401, no rows created |

---

## Verify it properly

```bash
python manage.py test tests            # 46 tests, real PostGIS
python manage.py check --deploy        # clean when DEBUG=False
python manage.py check_production_ready
```

---

## Before deploying

Remove the test console — it can create bookings and move payouts:

```bash
rm -rf devconsole/          # and drop ENABLE_DEV_CONSOLE from your env
```

Then work through `docs/OPERATIONS_CHECKLIST.md` (CAC, Paystack business tier, the
transfer-OTP setting, permanent Meta token) and `docs/DEPLOYMENT.md`.
