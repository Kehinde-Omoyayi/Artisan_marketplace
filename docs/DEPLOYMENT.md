# Deployment runbook (Part 23)

## Before you deploy

```bash
python manage.py test tests          # 46 tests must pass
python manage.py check --deploy      # must be clean with DEBUG=False
```

## Generate a real SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 1. Supabase

Upgrade to **Pro** (Project Settings → Billing). Same project, same connection string.
Confirm PostGIS: `select postgis_version();`

## 2. Railway — Redis

New → Database → **Add Redis**. Railway injects a URL variable into every service in the
project. **Check its exact name** in the web service's Variables tab — if it is
`REDISURL` or `REDIS_PRIVATE_URL` rather than `REDIS_URL`, either rename it or change
what `config/settings.py` reads.

## 3. Railway — web service

Upgrade to a **paid always-on plan** so the app stops sleeping on idle.

Build: the Nixpacks config is in `nixpacks.toml`. **If the build fails to find GDAL,
switch to the Dockerfile** (Settings → Build → Dockerfile) — it is the more reliable
path for GeoDjango.

Start command:

```
python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 60
```

Health check path: `/healthz/`

## 4. Railway — worker and beat services

New → GitHub Repo → same repository, twice. Override the start commands:

| Service | Start command |
|---|---|
| worker | `celery -A config worker --loglevel=info` |
| beat | `celery -A config beat --loglevel=info` |

Both need **the same environment variables** as the web service. Use a shared variable
group. A worker missing `DATABASE_URL` fails in a way that looks like "matching just
doesn't run" with no error in the web logs.

## 5. Environment variables

Set on **all three** services:

```
SECRET_KEY               DEBUG=False              ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS     DATABASE_URL             REDIS_URL
SITE_NAME                TERMII_API_KEY           TERMII_SENDER_ID
PAYSTACK_SECRET_KEY      PAYSTACK_PUBLIC_KEY      PAYSTACK_ENVIRONMENT
STORAGE_ENDPOINT_URL     STORAGE_BUCKET           STORAGE_ACCESS_KEY
STORAGE_SECRET_KEY       STORAGE_REGION           EMAIL_HOST
EMAIL_PORT               EMAIL_HOST_USER          EMAIL_HOST_PASSWORD
DEFAULT_FROM_EMAIL       SENTRY_DSN
```

`TERMII_API_KEY` is the one that's easy to forget and silent about it: without it,
the web chat's phone verification step has no way to actually deliver a code to a
real visitor (see `docs/WEBCHAT.md`) — the site will look completely fine until
someone tries to verify their number. `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` are only needed if you're also
running the WhatsApp channel alongside web chat — set them if so, per §6 below;
otherwise leave them unset and the site works fine without them.

## 6. First-run commands

```bash
railway run python manage.py migrate
railway run python manage.py bootstrap_v2
railway run python manage.py createsuperuser
railway run python manage.py backfill_v1_ledger --dry-run   # inspect, then run for real
```

## 7. Point the webhooks at production

- **Meta** → your App → WhatsApp → Configuration → Callback URL:
  `https://<your-domain>/whatsapp/webhook/` · Verify Token = `WHATSAPP_VERIFY_TOKEN` ·
  confirm the `messages` field is subscribed
- **Paystack** → Settings → API Keys & Webhooks → Webhook URL:
  `https://<your-domain>/payments/webhook/`

## 8. Final gate before live money

```bash
railway run python manage.py check_production_ready
```

Only when everything passes, and only after Paystack's business-tier approval has come
through, switch `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` and
`PAYSTACK_ENVIRONMENT=live` in Railway. Re-verify the webhook URL in the **live**
Paystack dashboard — test and live webhook settings are configured separately.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `type "geography" does not exist` | PostGIS installed into a custom schema | `alter database postgres set search_path to public, extensions;` |
| `GDALException` / `Could not find the GDAL library` | System libraries missing in the build image | Use the `Dockerfile` build instead of Nixpacks |
| Transfers stay `processing` forever | "Confirm transfers before sending" still enabled in Paystack | Part 2 Step 2 — uncheck it |
| Webhook returns 401 | `WHATSAPP_APP_SECRET` wrong, or Paystack key mismatch between test/live | Re-copy from Meta App Settings → Basic; check which Paystack mode fired the event |
| Matching never runs | Worker missing env vars, or not running | Check the worker service's logs and variables |
| Payouts never auto-send | Beat not running, or no schedule row | `bootstrap_v2`, then check the beat service's logs |
| Admin lockout after 5 tries | django-axes working as designed | `python manage.py axes_reset` |
| `Match` rows created but no WhatsApp received | Token expired (24h test token) | Part 18.5 — permanent System User token |
