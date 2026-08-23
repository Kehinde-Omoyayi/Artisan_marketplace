# Changes made in this review

Everything below was verified by actually installing the project (real Postgres +
PostGIS + Redis, not SQLite) and running its test suite — not just reading code.
**67/67 tests pass** (46 original + 21 new, listed below).

## Slot cap changed: 10 → 40

`marketplace/services.py` — `MAX_ACTIVE_MATCHES` is the single source of truth for
how many artisans can hold an open offer on one request at once; both the initial
broadcast and the decline-backfill read from it, so this was a one-line change.
Locked in with a new test that builds 45 candidates and asserts the *default* cap
is actually 40 (not just that an explicit override is honored).

## Bugs fixed

1. **`devconsole` — 11 endpoints (including one that moves real payouts and one
   that resets application state) had no authentication at all.** Every view
   called the same `_guard()` helper, which only re-checked the identical
   `ENABLE_DEV_CONSOLE` flag already gating URL registration — a single
   misconfigured environment variable, not two independent layers as the code's
   own docstring and the console's UI both claimed. That comment also asserted
   the console "refuses to load when DEBUG=False without an explicit opt-in" —
   never actually implemented anywhere. Fixed: `_guard()` now also requires
   `request.user.is_staff` (same account you'd use for `/admin/`), so leaving
   `ENABLE_DEV_CONSOLE=True` on by accident no longer means public exposure.
   Comment and UI text corrected to describe what's actually there. New tests
   in `tests/test_devconsole_auth.py` hit every guarded path as anonymous,
   non-staff, and staff to confirm it holds.

2. **`config/settings.py` — app was never actually using your database.**
   The real PostGIS `DATABASES` config (reading `DATABASE_URL`) was commented out
   and silently replaced by a hardcoded local SQLite file. On a host with an
   ephemeral filesystem (Railway, most Docker-based PaaS), this means every
   deploy would wipe the database back to empty. Restored to use `DATABASE_URL`.

3. **`accounts/models.py` — signup broke after the first user.**
   `email`, `bank_account_number`, and `bank_account_name` were `unique=True`
   without `null=True`. A second user without an email/bank details collided on
   the empty-string unique constraint. Added `null=True` to all three
   (migrations `0005`, `0006`). This was causing 25 of 46 existing tests to fail.

4. **Personal Windows dev-machine paths, in both `.env` and `config/settings.py`
   itself, would break GDAL on your Linux host.** `GDAL_LIBRARY_PATH` /
   `GEOS_LIBRARY_PATH` pointed at a local machine's `.dll` files — in `.env` as a
   value, and in `settings.py` as a *hardcoded default* (`OSGEO4W_BIN =
   r"C:\Users\omoya\..."`), which an AST scan for "variable assigned twice at
   module level" caught: it was set once to that Windows default, then
   immediately overwritten by a second, safe assignment a few lines later. Not
   a live bug — the second assignment always won — but exactly the kind of
   thing that becomes one the moment someone "cleans up" what looks like
   redundant code. Removed the dead first assignment, the hardcoded path, and
   the Windows-only `os.add_dll_directory` call; `SPATIALITE_LIBRARY_PATH` is
   gone too since nothing reads it now that fix #2 moved this project off
   SQLite/SpatiaLite entirely. Django auto-detects the system `libgdal`/`libgeos`
   on Linux when these are left unset — don't fill them back in for deployment.

5. **`whatsappbot/views.py` — the WhatsApp webhook verification handshake
   compared the verify token with plain `==` instead of a constant-time
   comparison,** unlike the message-signature check a few lines below it in the
   same file (which correctly uses `hmac.compare_digest`). Low real-world risk —
   this token doesn't authenticate message traffic or money movement, only a
   one-time setup handshake — but a real inconsistency, and cheap to fix.
   Switched to `hmac.compare_digest` for consistency with the rest of the
   project's own stated non-negotiable rules.

## Features built (previously modeled in the schema but not wired up)

6. **Artisan accept/decline over WhatsApp** (`marketplace/models.py`,
   `marketplace/services.py`, `marketplace/tasks.py`, `whatsappbot/views.py`).
   The bot already said "Reply YES to accept" but nothing ever read the reply —
   an artisan typing YES was misrouted into the customer flow. Now:
   - `Match` gained `offer_code`, `response_status`, `responded_at`.
   - Artisan replies `YES <code>` / `NO <code>` (or just `YES`/`NO` if they only
     have one open offer; `OFFERS` lists open codes if they have more than one).
   - **Accept**: creates the `Booking`, marks the request `matched`, expires the
     other pending offers for that request, notifies the customer. Race-safe —
     if two artisans accept near-simultaneously, the second is told the job's
     already taken (`select_for_update`).
   - **Decline**: marks the offer declined and queues `backfill_match_slot`,
     which offers the job to the next-best-ranked artisan who doesn't already
     have a slot for it — this is the "extra slot opens up" behavior.

7. **Saved address / prefetch for returning customers** (`accounts/models.py`,
   `whatsappbot/views.py`). `CustomerProfile.default_area` existed but was never
   read or written. Now, after picking a category, a returning customer with a
   saved address is asked "Use your saved address ({area})? Reply YES or NEW"
   instead of being asked for area + GPS pin from scratch. The profile is
   refreshed (address + `total_requests`) after every completed request.

## New tests

`tests/test_offer_response_and_prefetch.py` — 13 tests covering: accept creates
a booking and expires other offers; a second artisan accepting a filled job is
told it's too late; decline queues and correctly runs the backfill; backfill is
a no-op once filled or when no replacement candidate exists; multiple open
offers require a code; unknown codes don't crash; first-time vs. returning
customer address flow, including choosing "NEW" instead of the saved one.

## New: `.env.production.example`

A companion to the project's existing `docs/DEPLOYMENT.md` runbook (that file
already covers the deploy mechanics well — services, first-run commands,
webhook registration, a troubleshooting table — so this doesn't repeat it).
This file exists to answer one question per variable: **where does the real
value actually come from.** Verified current (Aug 2026) navigation steps for
each: Supabase (create project → enable PostGIS via SQL Editor → copy the
*session pooler* connection string, not transaction pooler), Meta's WhatsApp
Cloud API (create app → System User → permanent token → App Secret), Paystack
(Settings → API Keys & Webhooks), and Railway Redis (one-click add, but check
the variable name it creates — flagged in DEPLOYMENT.md too). Comes with a
freshly generated, unique `SECRET_KEY` already filled in — nothing to do there.

Your local `.env` also got a real generated `SECRET_KEY` (different from the
production one) in place of the placeholder text — no action needed from you.

## Additional verification pass (not fixes — checks that came back clean)

- **`core/views.ReadinessView`**: its docstring claims "staff-only," relying on a
  global DRF default rather than an explicit `permission_classes`. That's the
  kind of claim that silently stops being true if the global default ever
  changes. Added `tests/test_readiness_endpoint.py`, which empirically confirms
  (not just reads settings): anonymous → rejected, logged-in non-staff →
  rejected, staff → allowed. This endpoint reports live/test Paystack mode and
  the payout approval threshold, so it mattered to actually check.
- **Swept the whole codebase for the same `unique=True` + `blank=True` +
  missing `null=True` pattern** that caused the signup bug — every other
  `unique=True` field elsewhere (bookings, payments, services, core) is on a
  required field that's never blank, so this doesn't recur anywhere else.
- **AST-scanned every non-migration file for any module-level variable assigned
  more than once** — the exact shape of the DATABASES bug — to check it doesn't
  recur silently anywhere else. Found the GDAL/GEOS dead-code case (fix #4
  above); nothing else matched.
- **Enumerated every `urls.py` in the project (5 files, all reviewed)** to
  confirm which endpoints exist and how each is protected — this is what
  surfaced the devconsole gap (fix #1).
- **Raw SQL / template XSS**: the only `cursor.execute()` in the project is a
  hardcoded, parameter-free `SELECT postgis_version();` — no user input
  anywhere near it. Zero uses of `|safe`, `mark_safe`, or `{% autoescape off %}`
  in any template.
- **File upload path** (`core/storage.py`, WhatsApp ID-photo verification):
  the storage key is built from a server-generated UUID, never user input: no
  path-traversal or injection surface. `media_id` comes from Meta via a
  signature-verified webhook, not from anything an outside caller controls.
- **Rate limiting**: `django-ratelimit` is actually wired to both webhooks
  (60/min per IP, blocking), backed by a real Redis cache in production —
  confirmed it's not just a dependency sitting unused in `requirements.txt`.
- **`requirements.txt` dependency freshness**: `Django==5.2.17` is the actual
  current patched release as of Aug 4, 2026 — no newer security release is
  outstanding as of this review (Aug 18, 2026).
- **Upload size / CORS**: no explicit `DATA_UPLOAD_MAX_MEMORY_SIZE` override
  means Django's 2.5MB default request-body cap applies, which is appropriate
  here (no direct large-file-upload endpoint exists). No CORS package is
  installed, which is correct — nothing cross-origin consumes this API.
- **`collectstatic`**, which the real deploy start command runs, succeeds
  cleanly (171 files, no errors).

## Still needs you, not code — can't be fixed by editing the repo

- **Real WhatsApp Cloud API credentials** (`WHATSAPP_TOKEN`,
  `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`).
- **Real Paystack keys** (`PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`) — this is
  Paystack, not literally "WhatsApp Pay."
- **Real database URL** (`DATABASE_URL`) — currently your Supabase placeholder.
- **Email fallback credentials** (`EMAIL_HOST`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`) — used when a WhatsApp send fails.
- **Private object storage** (`STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`,
  `STORAGE_ENDPOINT_URL`) — currently empty; artisan ID-verification photo
  uploads have nowhere to go without this. Blocking per
  `check_production_ready`.
- **`DEBUG=False`** before going live (currently `True` for local dev).
- **Set `ENABLE_DEV_CONSOLE=False`** before production. It now requires a staff
  login even when left on (fix #1), but the smallest production footprint is
  still to turn it off entirely rather than rely on that second layer alone.

Already done for you, no action needed: `SECRET_KEY` (real generated values in
both `.env` and `.env.production.example`, not the placeholder text).

Run `python manage.py check_production_ready` any time to see exactly which of
the above are still outstanding — it's a real command already in the project.
