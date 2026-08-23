# Operations checklist — the non-code steps

These cannot be written in Python. Work top to bottom; the first item takes days, so
start it and keep building while you wait.

---

## 1. CAC registration (Part 1) — start this FIRST, 1–7 working days

- [ ] Create an account at `icrp.cac.gov.ng`
- [ ] Free public search for name availability — have **two backups** ready. Avoid
      generic names like "Quick Fix Services"; they get rejected more often
- [ ] Reserve the name (small fee, holds it 60 days)
- [ ] Start a **Business Name** registration — *not* Limited Company. Cheaper, faster,
      and enough to unlock Paystack's business tier. Upgrade to Ltd later if investors
      require it
- [ ] Upload: government ID (passport / driver's licence / NIN), passport photograph,
      digital signature, business address. **Scan clearly** — a blurry ID is the single
      most common cause of delay
- [ ] Pay the statutory fee (roughly ₦15,000–₦25,000 self-filed as of 2026 — check the
      portal, prices move)
- [ ] Check the dashboard **daily** for a "Query". The clock does not restart until you
      answer one
- [ ] Download the certificate **and** the status report PDF

> Do not wait for approval to keep building. You only need the certificate in hand for
> item 2 below.

---

## 2. Paystack business tier (Part 2)

- [ ] Settings → Compliance: submit CAC certificate, status report and ID documents
- [ ] **Settings → Preferences → uncheck "Confirm transfers before sending"** (sometimes
      "OTP on transfers")

  > ⚠️ **This is the single most common reason a junior dev's "working" payout code pays
  > nobody.** Leave it checked and every automated transfer sits silently waiting for an
  > OTP you will never enter.

- [ ] Note your bank codes: `GET https://api.paystack.co/bank` with your secret key
- [ ] Stay in **Test Mode** until everything else is done

---

## 3. Supabase (Part 4 Step 6, Part 23 Step 1)

- [ ] SQL Editor → New Query → run:

      create extension if not exists postgis;

      Use plain SQL. Do **not** use Dashboard → Database → Extensions with a custom
      schema — it causes `type "geography" does not exist`. If you hit that anyway:

      alter database postgres set search_path to public, extensions;

- [ ] Upgrade to the **Pro** tier before going live (same project, same connection
      string — you are not switching providers)

---

## 4. Private object storage (Part 18.2)

- [ ] Create a **private** bucket (Supabase Storage or Backblaze B2 — both S3-compatible)
      named e.g. `artisan-verification-private`
- [ ] Confirm it is private: paste an object URL into an incognito window. If the file
      loads, it is public — fix it before storing a single ID document
- [ ] Copy endpoint URL, access key, secret key into `STORAGE_*` variables

---

## 5. Permanent WhatsApp token (Part 18.5)

The V1 test token expires roughly every 24 hours — a production outage waiting to happen.

- [ ] business.facebook.com → Business Settings → **Users → System Users** → Add, role Admin
- [ ] Assign Assets → your App → **Manage app** (Full control); your WhatsApp Business
      Account → **Manage WhatsApp Business accounts** (Full control)
- [ ] Generate New Token → select your app → check `whatsapp_business_messaging` and
      `whatsapp_business_management`
- [ ] **Copy it immediately — Meta shows it only once.** Put it in `WHATSAPP_TOKEN`
- [ ] Also grab the **App Secret** (App Settings → Basic → Show) for `WHATSAPP_APP_SECRET`.
      This is a *different value* from the token, and V1 never used it

---

## 6. Staff accounts (Part 11 Step 4)

- [ ] `python manage.py setup_staff_roles` (or `bootstrap_v2`, which includes it)
- [ ] For each real staff member: /admin → Users → Add user → **uncheck Superuser**,
      **check Staff**, add to **exactly one** group:
      `finance_staff`, `verification_staff`, or `support_staff`
- [ ] Sanity check: log in as a `verification_staff` user. You must **not** see Payouts

---

## 7. Sentry (Part 23 Step 8)

- [ ] Free account at sentry.io → new Django project → copy the DSN into `SENTRY_DSN`

---

## 8. Cloudflare (optional, Part 18.6)

- [ ] Point DNS through Cloudflare's proxy instead of directly at Railway. Free bot/DDoS
      filtering, 15-minute DNS change, zero code

---

## 9. Secret rotation

Rotate `PAYSTACK_SECRET_KEY` and `WHATSAPP_APP_SECRET` **immediately** if either is ever
committed to Git, posted in a screenshot, or pasted into a support ticket. A leaked
secret is compromised the moment it is exposed, not the moment you notice misuse.
