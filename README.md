# Nigeria Artisan Marketplace — V2 Backend (Growth Build)

A complete, production-ready Django project implementing **every part** of the
*V2 Backend Build Manual*: PostGIS geospatial matching, Celery + Redis background jobs,
staged artisan verification (L0–L4), structured disputes, a financial ledger with
automated Paystack payouts and human approval above a threshold, and the full Part 18
security hardening checklist.

> This repository contains the V1 foundation (accounts, services, job_requests,
> bookings, payments, ratings, support_app, whatsappbot) **with the V2 changes already
> merged in**, so it stands alone. If you already have a running V1, see
> [`docs/MANUAL_COMPLIANCE.md`](docs/MANUAL_COMPLIANCE.md) — it maps every Part/Step of
> the manual to the exact file here, so you can port changes into your existing repo
> instead of replacing it.

**Verified working:** 99 tests pass against real PostgreSQL 16 + PostGIS 3.4 (67 from
the original V2 build, 32 new for the web chat channel below — 4 of those skip
depending on `ENABLE_DEV_CONSOLE`, and the suite has been run green in both states),
`manage.py check --deploy` reports zero issues in production mode,
`check_production_ready` runs clean modulo the secrets/config rows you're expected to
fill in yourself, and the Celery worker registers both tasks.

### 💬 Web chat replaces WhatsApp as the required channel

As of this build, the product's primary — and only *required* — conversational
channel is a chat box embedded on the public site (`pages` + `webchat` apps), not
WhatsApp. Everything the WhatsApp bot could do (customer request flow, artisan
self-onboarding, offer accept/decline, ID photo capture, location sharing) now also
works entirely from a browser, with no WhatsApp account needed anywhere in the path.
This isn't a second implementation of that logic — the web channel calls straight
into the same `whatsappbot/views.py` conversation engine WhatsApp always used, so the
two channels can never drift out of sync with each other. WhatsApp itself still
works if you configure it (`whatsappbot`'s webhook is untouched), but every
`WHATSAPP_*` setting is now optional. See [`docs/WEBCHAT.md`](docs/WEBCHAT.md) for
the full design, the OTP security rationale, and what a "big-company scale" upgrade
path (WebSockets, read replicas) would look like from here.

### 🧪 Interactive test console

Set `ENABLE_DEV_CONSOLE=True` and open **`/`** to get a page that drives the whole
system end to end — signed WhatsApp and Paystack webhooks, PostGIS matching, the payout
threshold, the dispute freeze, and live attacks on both webhooks — with no Meta or
Paystack account required. **Off by default and never routed in production** — when
it's off (the default), `/` serves the real public site + chat widget instead; see
`config/urls.py` for the exact branch.
See [`docs/TEST_CONSOLE.md`](docs/TEST_CONSOLE.md).

---

## 1. Architecture

```
Browser (chat widget)          WhatsApp (Meta, optional)          Paystack
        │  session + CSRF              │  signed POST                  │  signed POST
        ▼                              ▼  X-Hub-Signature-256          ▼  X-Paystack-Signature
┌────────────────────────────────────────────────────────────────────────────────┐
│  Django (gunicorn) — webchat is first-party (session+CSRF); webhooks are the   │
│  only endpoints trusted by signature instead                                   │
│    webchat.SendMessageView (+ 6 more)   whatsappbot.WhatsAppWebhookView         │
│              │                                    │            payments.PaystackWebhookView
│              └───────────────┬────────────────────┘                    │       │
│                               ▼ same conversation engine either way    │       │
│                    whatsappbot.views.handle_incoming_*                 │       │
└───────────┬───────────────────────────────────────────────┬───────────┴───────┘
            │ .delay()                                       │ confirms money
            ▼                                                ▼
┌───────────────────────┐                        ┌──────────────────────────┐
│ Celery worker         │                        │ PostgreSQL + PostGIS     │
│  run_matching_...     │──────────queries───────►│  (Supabase)              │
│  process_approved_... │                         └──────────────────────────┘
└───────────┬───────────┘
            │ every 5 min
      ┌─────▼──────┐        ┌─────────────────────────────────┐
      │ Celery beat│        │ Private S3 bucket (IDs/evidence)│
      └────────────┘        │  signed URLs, 5-minute expiry   │
                            └─────────────────────────────────┘
```

### The 16 apps

| App | Status in V2 | What it owns |
|---|---|---|
| `accounts` | upgraded | `User`, `CustomerProfile`, `ArtisanProfile` (+ `verification_level`), `AccountAction` |
| `services` | unchanged | `ServiceCategory`, `ArtisanService`, `ArtisanArea` |
| `marketplace` | filled in | `ArtisanLocation`, `ServiceArea`, `AvailabilitySlot`, `Match` + the ranking engine |
| `job_requests` | upgraded | `ServiceRequest` (+ `location` PointField), `RequestOffer` |
| `bookings` | upgraded | `Booking`, `BookingStatusHistory`, `ReliabilityEvent` |
| `payments` | upgraded | `Payment`, `PayoutLedger` (historical), `LedgerEntry`, `Payout`, `Refund`, `PaymentService` |
| `whatsappbot` | upgraded | The shared conversation engine (state machine, location pins, self-onboarding, ID capture) + the WhatsApp webhook adapter for it |
| `webchat` | **new** | The web adapter for the same engine: OTP phone verification, message transcript, HTTP endpoints the chat widget calls |
| `pages` | **new** | The public marketing site the chat widget is embedded on |
| `ratings` | unchanged | `Rating` |
| `support_app` | upgraded | `SupportNote` (V1), `SupportCase` |
| `verification` | **new** | `VerificationDocument`, the L0→L4 approval ladder |
| `disputes` | **new** | `Dispute`, `DisputeEvidence`, the payout-freeze service |
| `notifications` | **new** | `NotificationLog`, the single outbound-message gateway (routes to webchat, WhatsApp, or email) |
| `core` | **new** | `FeatureFlag`, `FeeConfig`, `AuditLog`, private storage, audit helper |

---

## 2. The four non-negotiable rules

These are enforced by code **and** by tests in `tests/test_security_rules.py`, which
fail the build if anyone ever breaks one.

1. **Never call Paystack's Transfer endpoint from anywhere except
   `PaymentService.release_payout()`.** A test greps every other module for `/transfer`.
2. **Never process a WhatsApp webhook POST without checking `X-Hub-Signature-256`.**
   Tests assert unsigned and wrongly-signed requests get `401` and create no rows.
   (The webchat channel is a different trust model — first-party session + CSRF, not
   a webhook signature — see `docs/WEBCHAT.md` for why that's the right tool there.)
3. **Never change `Booking.status`, `Payout.status`, `Dispute.status` or an artisan's
   `verification_level` without writing a history/audit row.** `change_booking_status()`
   writes `BookingStatusHistory` atomically; `log_audit()` covers the rest.
4. **Never mark a `Payment` confirmed, or a `Payout` paid/failed, outside the
   signature-checked Paystack webhook.**

Run `python manage.py check_production_ready` to verify all four at any time.

---

## 3. Quick start


### Option A — Docker (one command, nothing to install)

```bash
cp .env.example .env          # fill in your secrets
docker compose up             # PostGIS + Redis + web + worker + beat
```

Then, in another shell:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py bootstrap_v2
docker compose exec web python manage.py createsuperuser
```

### Option B — Local install (the manual's Part 3 path)

**Step 1 — system libraries.** GDAL/GEOS/PROJ are OS libraries, not pip packages.

```bash
# Ubuntu / Debian / WSL2
sudo apt-get update
sudo apt-get install -y binutils libproj-dev gdal-bin libgdal-dev redis-server

# macOS
brew install gdal geos proj redis && brew services start redis
```

Confirm with `gdal-config --version` and `redis-cli ping` (expect `PONG`).
If `gdal-config` says "command not found", stop — nothing past Part 5 will work.

**Step 2 — Python environment.**

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Step 3 — enable PostGIS on your Supabase database.** In Supabase → SQL Editor:

```sql
create extension if not exists postgis;
```

Use the plain SQL, *not* the Extensions toggle with a custom schema — that produces the
confusing `type "geography" does not exist` error. If you ever hit it anyway:

```sql
alter database postgres set search_path to public, extensions;
```

**Step 4 — migrate and bootstrap.**

```bash
python manage.py migrate
python manage.py bootstrap_v2      # FeeConfig + Beat schedule + RBAC groups + categories
python manage.py createsuperuser
```

**Step 5 — run it.** The manual's four terminals:

```bash
python manage.py runserver                  # terminal 1
celery -A config worker --loglevel=info     # terminal 2
celery -A config beat   --loglevel=info     # terminal 3
ngrok http 8000                             # terminal 4 — only needed if you're also running WhatsApp
```

**Step 6 — see the actual site.** With `ENABLE_DEV_CONSOLE=False` (the default),
`http://localhost:8000/` is the public marketing page with the chat widget — try the
whole flow: verify a phone number (dev mode prints the code to the console/terminal
1's log, and pre-fills it in the widget, since no `TERMII_API_KEY` is set), then type
`ARTISAN` to walk the artisan onboarding path, or describe a job as a customer. Run
`python manage.py collectstatic` first if you're not using `runserver`'s built-in
static serving (Docker/production images already do this — see `Dockerfile` /
`nixpacks.toml`). With `ENABLE_DEV_CONSOLE=True`, `/` is the interactive test console
instead (see below) — flip the flag to see the other one.

---

## 4. Management commands

Every "go into /admin and click this" step in the manual also exists as a command, so
setup is reproducible and cannot be mis-clicked.

| Command | Replaces | Does |
|---|---|---|
| `bootstrap_v2` | Parts 11.4, 13.5, 15.5 | Creates the active `FeeConfig`, registers the 5-minute payout Beat task, builds the three RBAC groups, seeds service categories |
| `setup_staff_roles` | Part 11 Step 4 | Builds `finance_staff` / `verification_staff` / `support_staff` with least-privilege permissions |
| `backfill_v1_ledger` | Part 20 | Migrates historical `PayoutLedger` rows into `LedgerEntry`. Idempotent; supports `--dry-run` |
| `check_production_ready` | Part 23/24 | Pre-flight before switching to Paystack Live keys: verifies secrets, infra, config rows and all four rules |

---

## 5. The ranking engine (Part 16)

`marketplace/services.py` is the single place ranking weights live. There is **no AI**
here, deliberately (Part 19) — it is a transparent, versioned formula you can read top
to bottom and explain to an artisan who asks "why didn't I get this job?".

**Hard filters** (excluded entirely): outside `MAX_RADIUS_KM` (15 km), doesn't offer the
service, high-risk category without at least L2 ID verification, suspended/inactive.

**Score** = rating (0–40, damped by sample size) + verification bonus (0–30)
+ distance decay (0–30) − exposure penalty (5 per offer in the last 24 h).

Every `Match` row records `ranking_version`, so when you eventually change the formula
you can compare old and new output on the same historical requests instead of flying
blind.

**Performance:** scoring runs a fixed, small number of queries regardless of candidate
pool size — 1 geospatial query plus 3 bulk lookups, instead of looping per-candidate
queries. Verified at 60 candidates: 4 queries total (was 181 before this was fixed;
see `marketplace/services.py`'s docstring and `git log` for the benchmark). This
matters in any city dense enough that a popular category has hundreds of artisans
within `MAX_RADIUS_KM` — the old shape would have meant hundreds of queries per
incoming request.

To retune, edit the constants at the top of `marketplace/services.py` — and **check
`HIGH_RISK_CATEGORY_SLUGS` matches the slugs actually in your database.**

---

## 6. Money flow

```
booking marked customer_completed
        │  complete_booking_and_create_payout()   ← the only sanctioned entry point
        ▼
PaymentService.create_payout()
        │
        ├─ amount <  FeeConfig.payout_approval_threshold_minor  → status "approved"
        │       └─ Celery Beat picks it up within 5 minutes, no human involved
        │
        └─ amount >= threshold                            → status "pending_approval"
                └─ finance_staff selects it in /admin → "Approve and send transfer"
        ▼
PaymentService.release_payout()   ← the ONLY caller of Paystack /transfer
        ▼  status = processing
Paystack webhook (signature verified) → transfer.success → status = paid
                                      → transfer.failed  → status = failed
```

`amount_minor` is **always kobo, never naira**. ₦50,000 is `5000000`.

Opening a dispute (`disputes.services.open_dispute`) immediately drops any non-final
payout on that booking back to `pending_approval`, writes an audit row, and raises a
high-priority `SupportCase`.

---

## 7. Security (Part 18)

| Item | Where |
|---|---|
| Webchat OTP: hashed+salted storage, single-use, capped attempts, row-locked against concurrent double-submission | `webchat/models.py`, `webchat/services.py` |
| Webchat is first-party (session + CSRF), never `@csrf_exempt` — see `docs/WEBCHAT.md` for why this differs from the webhook pattern below | `webchat/views.py` |
| WhatsApp `X-Hub-Signature-256` HMAC-SHA256 verification | `whatsappbot/security.py` |
| Paystack `X-Paystack-Signature` HMAC-SHA512, constant-time compare | `payments/services.py` |
| Rate limiting on webhooks (60/min) and webchat endpoints (per-action limits — OTP request 5/h, message send 30/min, etc.) | `django-ratelimit` decorators throughout |
| Admin brute-force lockout (5 failures / 1 hour, keyed on username+IP) | `django-axes` |
| Private object storage, 5-minute signed URLs, direct-upload path for webchat as well as WhatsApp media | `core/storage.py`, wired into both admin classes |
| RBAC, least privilege, no delete permissions | `setup_staff_roles` |
| Append-only audit log | `core/admin.py` — `has_change_permission`/`has_delete_permission` return `False` |
| HSTS, SSL redirect, secure cookies, nosniff, `X-Frame-Options: DENY` | `config/settings.py`, active when `DEBUG=False` |
| DB connection health checks (survives a stale persistent connection instead of 500ing) | `config/settings.py` — `CONN_HEALTH_CHECKS` |
| Sentry (Django + Celery integrations) | `config/settings.py` |

**Remaining manual (non-code) steps you must still do yourself:** CAC registration
(Part 1), Paystack business-tier upgrade and **disabling "Confirm transfers before
sending"** (Part 2 — if you skip this, every automated transfer silently waits for an
OTP and your artisans never get paid), and generating a permanent Meta System User
token (Part 18.5).

---

## 8. Testing

```bash
python manage.py test tests
```

99 tests covering: the geospatial ranking engine against real PostGIS (radius filter,
verification gate, rating damping, exposure balancing, and its query-count shape),
the payout threshold boundary, the dispute freeze, the ledger backfill's idempotency,
the full customer and artisan journeys over **both** WhatsApp and web chat, OTP
security (hashing, single-use, lockout, a genuine threaded concurrency test proving
two simultaneous verify attempts can't both succeed), notification channel routing
(webchat vs. WhatsApp vs. email fallback), the notification email fallback, the
verification ladder's monotonicity, RBAC least privilege, and all four
non-negotiable rules.

4 of the 99 are `ENABLE_DEV_CONSOLE`-dependent (the dev console's own auth tests and
the public homepage's tests each own one half of the same `/` route — see
`config/urls.py`) and skip themselves under the configuration that doesn't apply.
Run the suite once with the flag on and once with it off for full coverage in CI:

```bash
python manage.py test tests                       # covers the dev-console-on branch
ENABLE_DEV_CONSOLE=False python manage.py test tests   # covers the public-site branch
```

---

## 9. Deployment (Part 23)

Three Railway services from the same repo:

| Service | Start command |
|---|---|
| web | `gunicorn config.wsgi --bind 0.0.0.0:$PORT` |
| worker | `celery -A config worker --loglevel=info` |
| beat | `celery -A config beat --loglevel=info` |

`Procfile`, `railway.json`, `nixpacks.toml` and `Dockerfile` are all included.
**Use the Dockerfile if the Nixpacks build has trouble finding GDAL** — it is the more
reliable path for GeoDjango.

Checklist: Supabase Pro · Railway paid always-on plan · add Redis (confirm the injected
variable is really named `REDIS_URL`) · copy every variable from `.env.example` to all
three services · `SENTRY_DSN` · point Meta's webhook at the permanent URL · and only
then switch Paystack to Live keys, after `check_production_ready` passes.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full runbook.

---

## 10. Scaling posture

The app tier is fully stateless (all durable state is in Postgres/Redis, sessions are
DB/cache-backed, never in-process), so horizontal scaling — more gunicorn workers,
more Railway replicas — needs no code change. Beyond that, honestly:

- **Proven in this repo:** the matching engine's O(1)-query shape (§5), DB connection
  health checks + persistent connections, indexed webchat/OTP queries, rate limiting
  on every write endpoint, and a homepage cache (`pages/views.py`, 5 min) that turns
  unbounded read fan-out on the highest-traffic page into one query per cache window.
- **Deliberately not built:** WebSocket push for the chat widget. It polls instead
  (see `docs/WEBCHAT.md` for the reasoning and the concrete numbers on when polling
  stops being the right call, plus what the Channels-based upgrade would involve).
- **Not done here at all, and genuinely can't be from inside a sandbox:** real load
  testing against production-shaped traffic. The same caveat the V2 report itself
  already carries applies with more force now that a public chat surface exists —
  run load tests against your actual infrastructure before a large launch, using
  real request/webhook/chat-message patterns, not planning-target arithmetic.

