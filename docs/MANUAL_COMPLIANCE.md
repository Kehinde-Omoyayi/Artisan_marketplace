# Manual → code map

Every Part and Step of the *V2 Backend Build Manual*, and where it lives in this
repository. Use this if you are porting into an existing V1 repo rather than adopting
this one wholesale.

Legend: **Code** = implemented in a file here · **Ops** = an action you must perform
outside the codebase (a dashboard, a registrar, a bank).

| Part | Step | What the manual asks for | Where it is | Type |
|---|---|---|---|---|
| 0 | — | App inventory: what carries over, what's new | `README.md` §1 | Code |
| 1 | 1–8 | CAC business-name registration | `docs/OPERATIONS_CHECKLIST.md` | **Ops** |
| 2 | 1 | Paystack business-tier upgrade | `docs/OPERATIONS_CHECKLIST.md` | **Ops** |
| 2 | 2 | **Uncheck "Confirm transfers before sending"** | `docs/OPERATIONS_CHECKLIST.md` | **Ops** |
| 2 | 3 | Bank codes | `PaymentService.resolve_bank_account()` | Code |
| 2 | 4 | Stay in Test Mode until Part 23 | `PAYSTACK_ENVIRONMENT` in `.env.example` | Code |
| 3 | 1–3 | GDAL/GEOS/PROJ + Redis system libraries | `README.md` §3, `Dockerfile`, `nixpacks.toml` | Code |
| 3 | 4–5 | New pip packages, pinned | `requirements.txt` | Code |
| 3 | 6 | `REDIS_URL`, `PAYSTACK_ENVIRONMENT`, `SENTRY_DSN` | `.env.example` | Code |
| 4 | 1 | `INSTALLED_APPS` with `django.contrib.gis`, `axes`, 4 new apps | `config/settings.py` | Code |
| 4 | 2 | `DATABASES` with the PostGIS engine | `config/settings.py` | Code |
| 4 | 3 | Celery, axes, security-hardening settings | `config/settings.py` | Code |
| 4 | 4 | `WHATSAPP_APP_SECRET` | `config/settings.py`, `.env.example` | Code |
| 4 | 5 | `.gitignore` | `.gitignore` | Code |
| 4 | 6 | `create extension postgis` on Supabase | `README.md` §3 Step 3 | **Ops** |
| 4 | 7 | Create the 4 new apps | `verification/`, `disputes/`, `notifications/`, `core/` | Code |
| 5 | 1 | `ServiceRequest.location` PointField | `job_requests/models.py` | Code |
| 5 | 2 | `ArtisanLocation`, `ServiceArea`, `AvailabilitySlot`, `Match` | `marketplace/models.py` | Code |
| 5 | 3 | Marketplace admin | `marketplace/admin.py` | Code |
| 6 | 1 | `ArtisanProfile.verification_level` | `accounts/models.py` | Code |
| 6 | 2 | `VerificationDocument` | `verification/models.py` | Code |
| 6 | 3 | Approve action, level bump, audit | `verification/admin.py` | Code |
| 7 | 1 | `LedgerEntry`, `Payout`, `Refund` | `payments/models.py` | Code |
| 8 | 1 | `Dispute`, `DisputeEvidence` | `disputes/models.py` | Code |
| 8 | 2 | `open_dispute()` freezes payouts | `disputes/services.py` | Code |
| 8 | 3 | Disputes admin | `disputes/admin.py` | Code |
| 9 | 1 | `SupportCase` (string FK to break the import cycle) | `support_app/models.py` | Code |
| 9 | 2 | Support admin | `support_app/admin.py` | Code |
| 10 | 1 | `ReliabilityEvent` | `bookings/models.py` | Code |
| 10 | 2 | Bookings admin | `bookings/admin.py` | Code |
| 11 | 1 | `AccountAction` | `accounts/models.py` | Code |
| 11 | 2 | Accounts admin | `accounts/admin.py` | Code |
| 11 | 4 | Three RBAC staff groups | `manage.py setup_staff_roles` | Code |
| 12 | 1 | `NotificationLog` | `notifications/models.py` | Code |
| 12 | 2 | `send_notification()` — WhatsApp then email | `notifications/services.py` | Code |
| 12 | 3 | SMTP settings | `config/settings.py`, `.env.example` | Code |
| 12 | 4 | Notifications admin | `notifications/admin.py` | Code |
| 13 | 1 | `FeatureFlag`, `FeeConfig`, `AuditLog` | `core/models.py` | Code |
| 13 | 2 | `log_audit()` | `core/services.py` | Code |
| 13 | 3 | Append-only audit admin | `core/admin.py` | Code |
| 13 | 5 | Create the active FeeConfig row | `manage.py bootstrap_v2` | Code |
| 14 | 1 | Full bot rewrite: location pins, artisan onboarding, ID capture | `whatsappbot/views.py` | Code |
| 14 | 2 | Bot URLs | `whatsappbot/urls.py` | Code |
| 15 | 1 | `config/celery.py` | `config/celery.py` | Code |
| 15 | 2 | `config/__init__.py` | `config/__init__.py` | Code |
| 15 | 3 | `run_matching_for_request`, `process_approved_payouts` | `marketplace/tasks.py` | Code |
| 15 | 5 | 5-minute Beat schedule | `manage.py bootstrap_v2` | Code |
| 16 | 1 | PostGIS search + explainable scoring | `marketplace/services.py` | Code |
| 16 | 3 | Sanity-check the ranking | `tests/test_ranking_engine.py` | Code |
| 17 | 1 | `PaymentService` (init, verify, resolve, recipient, payout, release, refund) | `payments/services.py` | Code |
| 17 | 2 | Webhook handling charges **and** transfers | `payments/views.py` | Code |
| 17 | 3 | Payout approval admin action | `payments/admin.py` | Code |
| 17 | 4 | `complete_booking_and_create_payout()` | `bookings/views.py` | Code |
| 18.1 | 1 | `verify_whatsapp_signature()` | `whatsappbot/security.py` | Code |
| 18.2 | 1–2 | Private bucket + credentials | `.env.example`, `docs/OPERATIONS_CHECKLIST.md` | **Ops** |
| 18.2 | 3–4 | Storage settings, media download, signed URLs | `config/settings.py`, `core/storage.py` | Code |
| 18.2 | note | Signed-URL link in admin (left as an exercise) | **Done for you** in `verification/admin.py`, `disputes/admin.py` | Code |
| 18.3 | 1–2 | 60/min rate limit on both webhooks | `whatsappbot/views.py`, `payments/views.py` | Code |
| 18.3 | 3 | Redis cache backend | `config/settings.py` | Code |
| 18.4 | 1–3 | `AxesMiddleware` last, migrate | `config/settings.py` | Code |
| 18.5 | 1–4 | Permanent Meta System User token | `docs/OPERATIONS_CHECKLIST.md` | **Ops** |
| 18.6 | — | Headers, HTTPS, CSRF, SQLi, RBAC, audit, pinning | `config/settings.py`, `requirements.txt`, `README.md` §7 | Code |
| 19 | — | No AI in V2 | Ranking is a plain formula; no ML dependency exists | Code |
| 20 | 1–3 | Backfill `PayoutLedger` → `LedgerEntry` | `manage.py backfill_v1_ledger` | Code |
| 21 | 1–9 | Four terminals, end-to-end local test | `README.md` §3, `docker-compose.yml` | Code |
| 22 | — | Push to GitHub | `.gitignore` protects `.env` | Code |
| 23 | 1–7 | Supabase Pro, Railway Redis + paid tier, worker/beat services, Procfile | `Procfile`, `railway.json`, `nixpacks.toml`, `docs/DEPLOYMENT.md` | Code + **Ops** |
| 23 | 8 | Sentry | `config/settings.py` | Code |
| 23 | 10–11 | Live keys, final webhook URLs | `manage.py check_production_ready`, `docs/DEPLOYMENT.md` | Code + **Ops** |
| 24 | 1–18 | Order of operations, four rules | `README.md` §2, `tests/test_security_rules.py` | Code |

## Deliberate improvements on the manual

These go beyond the letter of the manual. Each one is defensive, not speculative — no
new tables, no new concepts, nothing that changes the schema you were told to build.

1. **The four rules are enforced by tests**, not just by comments. `test_security_rules.py`
   greps the codebase for stray `/transfer` calls and asserts unsigned webhooks are
   rejected. A future contributor who breaks a rule gets a red build.
2. **Clicking replaced by commands.** `bootstrap_v2` and `setup_staff_roles` make the
   FeeConfig row, Beat schedule and RBAC groups reproducible. The manual's hand-built
   permission lists are easy to mis-click in a way that silently grants a verification
   reviewer access to payouts.
3. **`backfill_v1_ledger` is a management command with `--dry-run`**, not a shell paste —
   same logic, but re-runnable and testable.
4. **`check_production_ready`** — one command answering "is it safe to switch to Live
   keys?", which the manual spreads across Parts 23 and 24.
5. **Signed-URL links wired into the admin.** Part 18.2 leaves this "as an exercise";
   it is done, because a staff member with no way to view a document will otherwise
   find an insecure way to view it.
6. **Axes locks on `username + ip_address`.** Locking on username alone lets an attacker
   deliberately lock out your finance staff.
7. **`change_booking_status` is transactional** with `select_for_update`, so two
   concurrent webhooks cannot interleave and write a contradictory history.
8. **`process_approved_payouts` catches per-payout exceptions**, so one bad recipient
   code cannot halt the whole payout batch.
9. **Hard filter #3 in ranking:** suspended or deactivated artisans never match. The
   manual has `AccountAction` for suspensions but never wires it into matching.
10. **`/healthz/` and `/api/readiness/`** for uptime monitoring and 2am debugging.
11. **Docker Compose** collapses the manual's four terminals into one command.
12. **`email` field on `accounts.User`** — the manual notes the email fallback silently
    does nothing without it and explicitly invites you to add it. Added, so the
    fallback in `notifications/services.py` actually works.
