# The interactive test console

`devconsole/` is **not part of the V2 manual**. It is an addition for verifying the
build: a single page that drives the real code paths and prints what the backend
actually did, so you can confirm the system works without a Meta account, a Paystack
account, or a phone.

Open the site root (`/`) with the console enabled.

## Enabling it

```bash
# .env
ENABLE_DEV_CONSOLE=True
```

It is **off by default**. With the flag unset, `devconsole` is not added to
`INSTALLED_APPS` and no `/dev/*` route is registered at all — the code is inert. Every
view also calls `_guard()`, which raises `Http404` if the flag is off, so even a
manually constructed URL returns nothing.

> **Never set `ENABLE_DEV_CONSOLE=True` in production.** The console can create bookings
> and move payouts between states. Leave it unset on Railway, or delete the
> `devconsole/` directory before deploying — nothing else imports it.

## What is real, and what is stubbed

This matters, because a demo that fakes everything proves nothing.

**Real** — the console exercises the genuine implementation:

- WhatsApp messages are **real HTTP POSTs to `/whatsapp/webhook/`**, signed with
  HMAC-SHA256 using `WHATSAPP_APP_SECRET`, hitting the real `WhatsAppWebhookView`
- Paystack events are **real signed POSTs to `/payments/webhook/`** (HMAC-SHA512)
- The conversation state machine, PostGIS distance queries, the ranking formula, the
  fee threshold, the payout state machine, the dispute freeze, the verification ladder
  and every audit row are all the actual production code
- The security probe sends genuinely unsigned and forged requests and asserts 401

**Stubbed** — only two outbound network edges, so you need no third-party accounts:

| Stub | Why |
|---|---|
| `notifications.services._send_whatsapp` | Would POST to Meta's Graph API. The `send_notification` wrapper, `NotificationLog` rows and fallback logic all still run |
| `payments.services.requests.post` | Would move **real money**. `PaymentService.release_payout()` still builds the request and is still the only thing allowed to |
| `core.storage.download_whatsapp_media_to_storage` | Would need a configured S3 bucket. Returns a realistic storage key |

Nothing is stubbed inside the signature checks, the ranking engine, or the state
machines.

## The scenarios

| # | Scenario | Proves |
|---|---|---|
| 1 | Seed 6 artisans | Fixtures across Lagos with varied ratings, job counts, verification levels — plus one in Ibadan |
| 2 | Customer journey | Five signed webhook POSTs walk the state machine; a real `ServiceRequest` with a coordinate is created; PostGIS ranks candidates |
| 3 | Artisan onboarding | `ARTISAN` → category → pin → ID photo produces a pending L2 document with a private storage key |
| 4 | Verification approval | The real admin action raises `verification_level` and writes an audit row |
| 5 | Money flow | Threshold routing, `release_payout`, and the signed webhook marking it `paid` |
| 6 | Dispute | Freezes a non-final payout to `pending_approval` and opens a high-priority case |
| 7 | Security probe | Unsigned and forged requests to both webhooks → 401, and rules #1/#3 verified statically |
| 8 | Infrastructure | PostGIS, Redis, Celery tasks and worker, FeeConfig, Beat schedule, RBAC groups, storage, DEBUG |

### Things worth trying

- **Run money flow at `20000`, then `75000`.** Below ₦50,000 the payout is created
  already `approved` and goes out unattended; at or above it, it is held at
  `pending_approval` for `finance_staff`. This is the "human in the loop above a
  threshold" rule, and it is the single most important behaviour to see with your own
  eyes.
- **Set the customer area to "Ibadan (far away)".** Watch the Lagos artisans drop out
  of the results — that is the 15 km radius filter in PostGIS, not application code.
- **Pick category "Electrical"** (a high-risk slug). Artisans below L2 are excluded
  entirely rather than merely ranked lower.
- **Look at rank #4 in the default run.** Emeka Nwosu has a perfect 5.0★ and is 0 km
  away, yet loses to a 4.6★ artisan 4.5 km away. That is the sample-size damping:
  one 5-star job should not outrank eighty good ones.
- **Open `/admin`** (admin / admin12345) after a run and inspect the rows the console
  created — bookings with their status history, payouts, audit log, notifications.

## Endpoints

All under `/dev/`, all POST except `state`, `recent` and `infra`:

`state` · `recent` · `seed-artisans` · `customer-journey` · `artisan-onboarding` ·
`approve-verification` · `money-flow` · `raise-dispute` · `security-probe` · `infra` ·
`reset`

Each returns `{"events": [{ok, message, detail}], "state": {...}}`, where `ok` is
`true` (pass), `false` (failure) or `null` (neutral information).

## Removing it before production

```bash
rm -rf devconsole/
```

Then remove `ENABLE_DEV_CONSOLE` from `.env`. The two guarded blocks in
`config/settings.py` and `config/urls.py` are already no-ops when the flag is absent,
so nothing else needs to change and the test suite still passes.
