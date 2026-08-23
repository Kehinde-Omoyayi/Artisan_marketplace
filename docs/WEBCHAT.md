# The web chat channel

`webchat/` + `pages/` replace WhatsApp as the product's required conversational
channel. This doc covers why it's built the way it is, what's genuinely
production-ready versus what you still need to configure, and what a larger-scale
upgrade looks like from here.

## The core idea: one engine, two doors

`whatsappbot/views.py` already contained a complete, channel-agnostic conversation
engine — `handle_incoming_text(phone_e164, text)`, `handle_incoming_location(...)`,
`handle_incoming_image(...)` — keyed entirely by `phone_e164`, not by anything
WhatsApp-specific. The WhatsApp webhook was already just one *caller* of that engine.

So the web channel isn't a second implementation of the request flow, matching,
offers, or ID capture — it's a second caller of the exact same functions, reached
over `/webchat/message/` instead of `/whatsapp/webhook/`. The two channels
structurally cannot drift apart, because there's only one state machine between them.
The one genuinely new function is `handle_incoming_image_upload`, which exists only
because the web browser hands us file bytes directly instead of a Meta media ID —
everything after that (`VerificationDocument`, the notification, the state reset) is
the same shared `_finish_id_capture` helper both transports call.

## Why phone verification exists at all

WhatsApp gets phone-ownership proof for free: Meta only calls the webhook for a
message that genuinely came from that WhatsApp number. A web `<input type="tel">`
gets nothing for free — anyone can type any digits in. Binding a browser session to a
phone identity without proving it first would mean anyone could act as anyone else's
account: see their booking history, respond to their job offers, redirect their
verification photos.

`webchat/models.py:PhoneVerificationCode` closes that gap:

- Codes are 6-digit, generated with `secrets.randbelow` (not `random`), and stored as
  a salted SHA-256 hash — never in plaintext, anywhere, including logs (the log line
  in `services.py` logs the delivery *channel*, never the code itself, except the
  one deliberate `debug_code` exception below).
- Single-use (`consumed_at`), time-limited (`WEBCHAT_OTP_TTL_SECONDS`, default 5 min),
  and capped at `MAX_ATTEMPTS = 5` guesses before lockout — enforced in
  `PhoneVerificationCode.verify_code()`, which increments `attempts` on every miss
  regardless of caller behavior, and in `webchat/services.py:confirm_phone_code`,
  which classifies *why* a code was rejected (expired vs. locked vs. wrong) so the
  widget can say something accurate rather than a generic "failed".
- Verification is wrapped in `select_for_update()` inside `transaction.atomic()` —
  see `tests/test_webchat.py:OTPConcurrencyTests`, which spins two real threads
  racing to consume the same code and asserts exactly one wins. This is not a
  hypothetical: a double-tapped "Verify" button, or two tabs open to the same
  number, produces exactly this race in practice.

Once verified, the browser session (`WebChatSession`, keyed by Django's own
`session_key` — never a client-supplied value) is bound to the resulting
`accounts.User`, and stays bound for `WEBCHAT_ACTIVE_WINDOW_HOURS` (default 24) of
activity. `notifications.services.send_notification` checks this binding
(`webchat.services.is_webchat_user`) before every outbound message: if the user has
an active web session, the reply goes to the transcript and WhatsApp/email are never
attempted; otherwise, delivery falls through to WhatsApp-then-email exactly as it did
before this channel existed. An abandoned browser tab doesn't permanently steal a
user's WhatsApp delivery — it just ages out of the window.

## Getting a real OTP into someone's hand

Delivery is pluggable (`webchat/sms_backends.py`). With `TERMII_API_KEY` set, codes
go out over Termii's DND/transactional SMS route — a working Nigerian SMS aggregator,
chosen to fit a Nigeria-first product. **Verify the request shape against
[developers.termii.com](https://developers.termii.com) before relying on it in
production** — this was implemented against their documented API as of this build,
but it's a third party's API, not something this repo controls.

With nothing configured, delivery falls through to a log line, and — **only when
`DEBUG=True`** — the code is echoed back in the API response and auto-filled in the
widget. This mirrors `devconsole`'s own philosophy exactly: fully exercisable in
development and CI with zero third-party accounts, and structurally incapable of
leaking a code in production, because `DEBUG` is false there regardless of which SMS
provider is or isn't configured. **You must set `TERMII_API_KEY` (or wire in a
different provider here) before a real launch** — without it, visitors can open the
chat widget but can never get past phone verification.

## Why polling instead of WebSockets

The widget short-polls (`GET /webchat/messages/?since=<id>`, default every 2.5s,
configurable via `WEBCHAT_POLL_INTERVAL_MS` without a frontend deploy) rather than
holding a WebSocket open. This was a deliberate call, not a default:

- It's directly sized to the project's own existing SLA target — "queue delay
  <30 seconds for normal notifications" (V2 report, Performance Targets) — a chat
  reply arriving within one poll interval is well inside that budget.
- Every query behind it is indexed (`WebChatMessage` on `(phone_e164, id)`) and O(1)
  regardless of transcript length.
- It needed no new infrastructure: no ASGI server swap (gunicorn → daphne/uvicorn),
  no channel layer, nothing added to `requirements.txt`. Every line of it is covered
  by `tests/test_webchat.py` using Django's ordinary test client — nothing was left
  half-verified to hit a deadline.
- Polling pauses while a tab is backgrounded (`visibilitychange` in `chat.js`), which
  keeps steady-state load roughly proportional to *visible* tabs, not open ones.

**When this stops being the right answer:** back-of-envelope, 10,000 concurrent
visible chat tabs at a 3s interval is about 3,300 requests/sec of poll traffic alone.
Each request is cheap (one indexed query), but that's still real app-server capacity
to provision — it's an HTTP-throughput problem, not a database problem, and it's
solved the boring way (more gunicorn workers/replicas behind a load balancer) long
before it requires anything exotic. If you outgrow that, the concrete upgrade is
Django Channels with a Redis channel layer — Redis is already a dependency here for
Celery, so the infrastructure exists — replacing the poll loop with a WebSocket
consumer keyed the same way everything else is, by `phone_e164`. That's a deliberate
future milestone with its own design review, not something to bolt on quietly; ship
it with `channels.testing.WebsocketCommunicator` tests of the same rigor as the rest
of this suite, not without them.

## What's genuinely tested vs. what you still need to do

**Verified in this repo** (`tests/test_webchat.py`, `tests/test_pages.py`, run
against real PostgreSQL): the full OTP lifecycle including its attack-shaped edge
cases, the message/location/upload flow reaching the real conversation engine end to
end, notification routing (webchat vs. WhatsApp vs. stale-session fallback), the
concurrency guarantee on code verification, and that an unexpected exception anywhere
in the engine call returns a clean JSON error instead of a leaked traceback — while
still preserving whatever the visitor had already typed.

**Not something a sandbox can verify, and still yours to do:** an actual OTP SMS
arriving on an actual Nigerian phone (needs `TERMII_API_KEY` and a real number);
how the widget actually looks and behaves in a real browser (needs eyes on it — the
CSS/JS were written carefully but never rendered by an actual browser during this
build); and load testing against real traffic, per the Scaling posture section of the
main README.
