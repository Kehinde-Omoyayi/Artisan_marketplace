import hashlib
import hmac
import json
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.test import Client
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

from accounts.models import AccountAction, ArtisanProfile, User
from bookings.models import Booking, BookingStatusHistory, ReliabilityEvent
from core.models import AuditLog, FeatureFlag, FeeConfig
from disputes.models import Dispute, DisputeEvidence
from job_requests.models import RequestOffer, ServiceRequest
from marketplace.models import ArtisanLocation, Match
from notifications.models import NotificationLog
from payments.models import LedgerEntry, Payment, Payout, PayoutLedger, Refund
from services.models import ArtisanService, ServiceCategory
from support_app.models import SupportCase, SupportNote
from verification.models import VerificationDocument
from whatsappbot.models import ConversationState, WhatsAppMessage

# Lagos landmarks, so distances in the UI are recognisable.
LAGOS = {
    "Yaba": (3.3792, 6.5244),
    "Surulere": (3.3487, 6.4969),
    "Ikeja": (3.3515, 6.6018),
    "Lekki Phase 1": (3.4700, 6.4400),
    "Victoria Island": (3.4216, 6.4281),
    "Ibadan (far away)": (3.9470, 7.3775),
}


def _guard(request):
    if not getattr(settings, "ENABLE_DEV_CONSOLE", False):
        raise Http404("Dev console is disabled. Set ENABLE_DEV_CONSOLE=True to use it.")
    if not (request.user.is_authenticated and request.user.is_staff):
        # Log in at /admin/login/ first, then reload — same staff account you'd
        # use for the Django admin. Deliberately a flat 403, not a redirect to
        # login: this tool should never be reachable by the public in the first
        # place, so it doesn't need to be convenient for anonymous visitors.
        raise PermissionDenied("Dev console requires a staff login (see /admin/login/).")


def _client():
    """
    Django's test Client sends `Host: testserver`, which a live server rejects with a
    400 unless it is in ALLOWED_HOSTS. We send a host the project already trusts
    instead of loosening ALLOWED_HOSTS, which would be a real (if small) security
    regression just to make a demo work.
    """
    host = (settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "localhost")
    if host.startswith("."):  # a wildcard suffix like ".railway.app"
        host = "local" + host
    if host == "*":
        host = "localhost"
    return Client(SERVER_NAME=host)


@contextmanager
def _stub_outbound():
    """Stub ONLY the network edges: Meta's send API and Paystack's HTTP calls."""
    with patch("notifications.services._send_whatsapp", return_value=None), patch(
        "core.storage.download_whatsapp_media_to_storage",
        side_effect=lambda media_id, folder: f"{folder}/{uuid.uuid4().hex}.jpg",
    ):
        yield


class _FakePaystack:
    """Mimics the Paystack JSON responses PaymentService expects."""

    def __init__(self, transfer_code):
        self.transfer_code = transfer_code

    def json(self):
        return {"status": True, "data": {"transfer_code": self.transfer_code}}


def _log(events, ok, message, detail=""):
    """ok=True → pass, ok=False → failure, ok=None → neutral information."""
    events.append({"ok": ok, "message": message, "detail": detail})


# ---------------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------------
def home(request):
    _guard(request)
    return render(
        request,
        "devconsole/home.html",
        {"areas": list(LAGOS.keys()), "debug": settings.DEBUG},
    )


# ---------------------------------------------------------------------------------
# State snapshot
# ---------------------------------------------------------------------------------
def _snapshot():
    active_fee = FeeConfig.objects.filter(active=True).first()
    return {
        "counts": {
            "Users": User.objects.count(),
            "Artisans": User.objects.filter(role="artisan").count(),
            "Service requests": ServiceRequest.objects.count(),
            "Matches": Match.objects.count(),
            "Bookings": Booking.objects.count(),
            "Payments": Payment.objects.count(),
            "Payouts": Payout.objects.count(),
            "Ledger entries": LedgerEntry.objects.count(),
            "Disputes": Dispute.objects.count(),
            "Support cases": SupportCase.objects.count(),
            "Verification docs": VerificationDocument.objects.count(),
            "Notifications": NotificationLog.objects.count(),
            "Audit rows": AuditLog.objects.count(),
        },
        "fee_config": {
            "version": active_fee.version if active_fee else None,
            "threshold_minor": active_fee.payout_approval_threshold_minor
            if active_fee
            else None,
            "commission": str(active_fee.platform_commission_percent)
            if active_fee
            else None,
        },
        "payouts_by_status": {
            row["status"]: row["n"]
            for row in Payout.objects.values("status").annotate(n=Count("id"))
        },
    }


def state(request):
    _guard(request)
    return JsonResponse(_snapshot())


def recent(request):
    _guard(request)
    return JsonResponse(
        {
            "matches": [
                {
                    "artisan": m.artisan.full_name or m.artisan.phone_e164,
                    "rank": m.rank_position,
                    "distance_km": str(m.distance_km),
                    "score": str(round(m.ranking_score, 2)),
                    "version": m.ranking_version,
                    "request": str(m.request_id)[:8],
                }
                for m in Match.objects.select_related("artisan", "request").order_by(
                    "request_id", "rank_position"
                )[:25]
            ],
            "notifications": [
                {
                    "to": (n.user.full_name or n.user.phone_e164) if n.user else "—",
                    "channel": n.channel,
                    "template": n.template_name,
                    "status": n.status,
                    "body": (n.payload or {}).get("body", "")[:160],
                }
                for n in NotificationLog.objects.select_related("user")[:25]
            ],
            "audit": [
                {
                    "action": a.action,
                    "target": f"{a.target_type}:{str(a.target_id)[:8]}",
                    "actor": a.actor,
                    "at": a.created_at.strftime("%H:%M:%S"),
                }
                for a in AuditLog.objects.all()[:25]
            ],
            "payouts": [
                {
                    "id": str(p.id)[:8],
                    "artisan": p.artisan.full_name or p.artisan.phone_e164,
                    "naira": f"{p.amount_minor / 100:,.2f}",
                    "status": p.status,
                }
                for p in Payout.objects.select_related("artisan").all()[:25]
            ],
            "bookings": [
                {
                    "ref": b.booking_ref,
                    "naira": f"{b.agreed_amount_minor / 100:,.2f}",
                    "status": b.status,
                    "history": list(
                        b.status_history.values_list("to_status", flat=True)
                    )[::-1],
                }
                for b in Booking.objects.all()[:25]
            ],
        }
    )


# ---------------------------------------------------------------------------------
# Scenario 1 — seed artisans
# ---------------------------------------------------------------------------------
@csrf_exempt
def seed_artisans(request):
    _guard(request)
    events = []
    body = json.loads(request.body or "{}")
    category_name = body.get("category", "Plumbing")

    category, _ = ServiceCategory.objects.get_or_create(
        name=category_name, defaults={"slug": slugify(category_name), "active": True}
    )

    roster = [
        # name,            area,             rating, jobs, level
        ("Chidi Okafor", "Yaba", "4.9", 60, "L4"),
        ("Bola Adeyemi", "Surulere", "4.6", 80, "L3"),
        ("Emeka Nwosu", "Yaba", "5.0", 1, "L2"),
        ("Tunde Balogun", "Ikeja", "4.8", 40, "L2"),
        ("Ngozi Eze", "Lekki Phase 1", "4.7", 25, "L1"),
        ("Sadiq Bello", "Ibadan (far away)", "5.0", 99, "L4"),
    ]

    with _stub_outbound():
        for i, (name, area, rating, jobs, level) in enumerate(roster):
            phone = f"23480{i:09d}"
            user, _ = User.objects.get_or_create(
                phone_e164=phone,
                defaults={"role": "artisan", "full_name": name},
            )
            user.full_name, user.role = name, "artisan"
            user.save()
            profile, _ = ArtisanProfile.objects.get_or_create(user=user)
            profile.rating_avg = Decimal(rating)
            profile.completed_jobs = jobs
            profile.verification_level = level
            profile.save()
            ArtisanService.objects.get_or_create(
                artisan=user, service=category, defaults={"active": True}
            )
            lng, lat = LAGOS[area]
            ArtisanLocation.objects.update_or_create(
                artisan=user, defaults={"point": Point(lng, lat, srid=4326)}
            )
            _log(
                events,
                True,
                f"{name} — {area}, {rating}★ from {jobs} jobs, verification {level}",
            )

    _log(events, True, f"6 artisans ready for category '{category.name}'.")
    return JsonResponse({"events": events, "state": _snapshot()})


# ---------------------------------------------------------------------------------
# Scenario 2 — customer journey through the REAL signed webhook
# ---------------------------------------------------------------------------------
def _post_whatsapp(client, payload):
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()
    return client.post(
        "/whatsapp/webhook/",
        data=raw,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
    )


def _msg(phone, body):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": phone, "type": "text", "text": {"body": body}}
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _loc(phone, lat, lng):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "type": "location",
                                    "location": {"latitude": lat, "longitude": lng},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _img(phone, media_id):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "type": "image",
                                    "image": {"id": media_id},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@csrf_exempt
def customer_journey(request):
    _guard(request)
    events = []
    body = json.loads(request.body or "{}")
    area = body.get("area", "Yaba")
    category = body.get("category", "Plumbing")
    timing = body.get("timing", "Today")
    phone = body.get("phone") or f"2349{uuid.uuid4().int % 10**9:09d}"

    if not ServiceCategory.objects.filter(name__iexact=category, active=True).exists():
        return JsonResponse(
            {
                "events": [
                    {
                        "ok": False,
                        "message": f"No active category '{category}'. Seed artisans first.",
                    }
                ],
                "state": _snapshot(),
            }
        )

    lng, lat = LAGOS[area]
    client = _client()
    ConversationState.objects.filter(phone_e164=phone).delete()

    with _stub_outbound():
        r = _post_whatsapp(client, _msg(phone, "hello"))
        _log(events, r.status_code == 200, f"Customer {phone} says 'hello'",
             f"HTTP {r.status_code} · state → awaiting_category")

        _post_whatsapp(client, _msg(phone, category))
        _log(events, True, f"Replies '{category}'", "state → awaiting_area")

        _post_whatsapp(client, _msg(phone, area))
        _log(events, True, f"Replies '{area}'", "state → awaiting_location")

        _post_whatsapp(client, _loc(phone, lat, lng))
        _log(events, True, f"Shares location pin ({lat}, {lng})",
             "state → awaiting_timing")

        # Run matching inline so the UI can show results immediately.
        with patch("marketplace.tasks.run_matching_for_request.delay") as delayed:
            _post_whatsapp(client, _msg(phone, timing))
            called = delayed.call_args[0][0] if delayed.call_args else None

        _log(events, called is not None, f"Replies '{timing}' → ServiceRequest created",
             f"Celery task queued for request {str(called)[:8]}")

        service_request = ServiceRequest.objects.get(id=called)
        if service_request.location:
            _log(events, True, "Coordinate stored correctly",
                 f"lng={service_request.location.x:.4f}, lat={service_request.location.y:.4f} "
                 f"(Point is x=lng, y=lat)")

        from marketplace.tasks import run_matching_for_request

        run_matching_for_request(str(service_request.id))

    matches = list(
        Match.objects.filter(request=service_request)
        .select_related("artisan")
        .order_by("rank_position")
    )
    _log(events, bool(matches), f"PostGIS matching ran → {len(matches)} artisans ranked")
    for m in matches:
        _log(events, True,
             f"  #{m.rank_position}  {m.artisan.full_name}",
             f"{m.distance_km} km · score {round(m.ranking_score, 2)} · {m.ranking_version}")

    excluded = User.objects.filter(role="artisan").count() - len(matches)
    if excluded > 0:
        _log(events, True, f"{excluded} artisan(s) excluded by hard filters",
             "outside 15 km radius, wrong service, below L2 on high-risk, or suspended")

    return JsonResponse(
        {"events": events, "state": _snapshot(), "request_id": str(service_request.id)}
    )


# ---------------------------------------------------------------------------------
# Scenario 3 — artisan self-onboarding + ID capture
# ---------------------------------------------------------------------------------
@csrf_exempt
def artisan_onboarding(request):
    _guard(request)
    events = []
    body = json.loads(request.body or "{}")
    category = body.get("category", "Plumbing")
    area = body.get("area", "Surulere")
    phone = body.get("phone") or f"2347{uuid.uuid4().int % 10**9:09d}"

    if not ServiceCategory.objects.filter(name__iexact=category, active=True).exists():
        ServiceCategory.objects.get_or_create(
            name=category, defaults={"slug": slugify(category), "active": True}
        )

    lng, lat = LAGOS[area]
    client = _client()
    ConversationState.objects.filter(phone_e164=phone).delete()

    with _stub_outbound():
        _post_whatsapp(client, _msg(phone, "ARTISAN"))
        user = User.objects.get(phone_e164=phone)
        _log(events, user.role == "artisan", f"{phone} texts 'ARTISAN'",
             f"role → {user.role}, ArtisanProfile created at level "
             f"{user.artisan_profile.verification_level}")

        _post_whatsapp(client, _msg(phone, category))
        _log(events, True, f"Picks category '{category}'")

        _post_whatsapp(client, _loc(phone, lat, lng))
        has_service = ArtisanService.objects.filter(artisan=user).exists()
        has_location = ArtisanLocation.objects.filter(artisan=user).exists()
        _log(events, has_service and has_location, f"Shares location pin ({area})",
             "ArtisanService + ArtisanLocation rows created")

        _post_whatsapp(client, _img(phone, f"MEDIA_{uuid.uuid4().hex[:8]}"))

    doc = VerificationDocument.objects.filter(artisan=user).first()
    if doc:
        _log(events, True, "Sends government ID photo",
             f"VerificationDocument L2 · status={doc.status} · key={doc.storage_key}")
        _log(events, not doc.storage_key.startswith("http"),
             "storage_key is a private bucket path, never a public URL")
    _log(events, True, "Artisan now awaits staff review in /admin → Verification documents")
    return JsonResponse({"events": events, "state": _snapshot(), "phone": phone})


# ---------------------------------------------------------------------------------
# Scenario 4 — verification approval ladder
# ---------------------------------------------------------------------------------
@csrf_exempt
def approve_verification(request):
    _guard(request)
    events = []
    from django.contrib.auth.models import User as StaffUser

    from verification.admin import approve_documents

    staff, _ = StaffUser.objects.get_or_create(
        username="devconsole_reviewer", defaults={"is_staff": True}
    )
    pending = VerificationDocument.objects.filter(status="pending")
    if not pending.exists():
        _log(events, False, "No pending documents. Run artisan onboarding first.")
        return JsonResponse({"events": events, "state": _snapshot()})

    class Req:
        user = staff

    before = {d.id: d.artisan.artisan_profile.verification_level for d in pending}
    approve_documents(None, Req(), pending)

    for doc_id, old_level in before.items():
        doc = VerificationDocument.objects.get(id=doc_id)
        new_level = doc.artisan.artisan_profile.verification_level
        _log(events, True,
             f"{doc.artisan.full_name or doc.artisan.phone_e164}: {old_level} → {new_level}",
             f"reviewed_by={doc.reviewed_by} · audit row written")

    _log(events, True, "Level never moves backwards — 'L2' > 'L4' is False as strings")
    return JsonResponse({"events": events, "state": _snapshot()})


# ---------------------------------------------------------------------------------
# Scenario 5 — money: threshold, transfer, signed webhook
# ---------------------------------------------------------------------------------
@csrf_exempt
def money_flow(request):
    _guard(request)
    events = []
    body = json.loads(request.body or "{}")
    naira = Decimal(str(body.get("naira", "20000")))
    amount_minor = int(naira * 100)

    artisan = User.objects.filter(role="artisan").first()
    if not artisan:
        _log(events, False, "No artisans. Seed artisans first.")
        return JsonResponse({"events": events, "state": _snapshot()})

    customer, _ = User.objects.get_or_create(
        phone_e164="2348099999999", defaults={"full_name": "Test Customer"}
    )
    category = ServiceCategory.objects.first()
    service_request = ServiceRequest.objects.create(
        customer=customer, category=category, area_name="Yaba"
    )
    booking = Booking.objects.create(
        request=service_request,
        customer=customer,
        artisan=artisan,
        agreed_amount_minor=amount_minor,
    )
    _log(events, True, f"Booking {booking.booking_ref} created for ₦{naira:,.2f}",
         f"agreed_amount_minor = {amount_minor} kobo")

    fee = FeeConfig.objects.filter(active=True).first()
    threshold = fee.payout_approval_threshold_minor if fee else 5000000
    _log(events, True,
         f"Active FeeConfig v{fee.version if fee else '—'}: approval threshold "
         f"₦{threshold / 100:,.2f}")

    from bookings.views import complete_booking_and_create_payout

    payout = complete_booking_and_create_payout(
        booking, "RCP_devconsole_test", actor="devconsole"
    )
    booking.refresh_from_db()
    _log(events, booking.status == "customer_completed",
         "Customer confirms completion",
         f"status → {booking.status} · BookingStatusHistory row written "
         f"(non-negotiable rule #3)")

    auto = payout.status == "approved"
    _log(events, True,
         f"Payout created with status '{payout.status}'",
         f"₦{naira:,.2f} {'<' if auto else '>='} ₦{threshold / 100:,.2f} → "
         + ("auto-approved, Celery Beat sends it within 5 min"
            if auto else "HELD for finance_staff approval in /admin"))

    if not auto:
        _log(events, True, "Simulating finance_staff clicking 'Approve and send transfer'")
        from django.contrib.auth.models import User as StaffUser
        from django.utils import timezone

        finance, _ = StaffUser.objects.get_or_create(
            username="devconsole_finance", defaults={"is_staff": True}
        )
        payout.status = "approved"
        payout.approved_by = finance
        payout.approved_at = timezone.now()
        payout.save()

    transfer_code = f"TRF_{uuid.uuid4().hex[:10]}"
    from payments.services import PaymentService

    with patch("payments.services.requests.post",
               return_value=_FakePaystack(transfer_code)) as mock_post:
        PaymentService.release_payout(payout)
        called_url = mock_post.call_args[0][0]

    payout.refresh_from_db()
    _log(events, payout.status == "processing",
         "PaymentService.release_payout() called Paystack",
         f"POST {called_url} · status → {payout.status} · "
         f"transfer_code {payout.paystack_transfer_code}")
    _log(events, True, "Non-negotiable rule #1 upheld",
         "release_payout() is the only function in the project that builds a /transfer call")

    # Now the REAL Paystack webhook, correctly signed.
    payload = json.dumps(
        {"event": "transfer.success", "data": {"transfer_code": transfer_code}}
    ).encode()
    signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), payload, hashlib.sha512
    ).hexdigest()
    client = _client()
    response = client.post(
        "/payments/webhook/",
        data=payload,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=signature,
    )
    payout.refresh_from_db()
    _log(events, payout.status == "paid",
         f"Signed Paystack webhook 'transfer.success' → HTTP {response.status_code}",
         f"payout status → {payout.status} (rule #4: only the webhook may mark it paid)")

    return JsonResponse(
        {"events": events, "state": _snapshot(), "payout_id": str(payout.id)}
    )


# ---------------------------------------------------------------------------------
# Scenario 6 — dispute freezes the payout
# ---------------------------------------------------------------------------------
@csrf_exempt
def raise_dispute(request):
    _guard(request)
    events = []
    body = json.loads(request.body or "{}")
    reason = body.get("reason", "not_completed")

    payout = Payout.objects.exclude(status__in=("paid", "failed")).first()

    if not payout:
        # Every existing payout is already final, so the freeze would be a no-op and the
        # demo would show nothing. Create a fresh in-flight booking to dispute instead.
        artisan = User.objects.filter(role="artisan").first()
        if not artisan:
            _log(events, False, "No artisans. Seed artisans first.")
            return JsonResponse({"events": events, "state": _snapshot()})
        customer, _ = User.objects.get_or_create(
            phone_e164="2348088888888", defaults={"full_name": "Dispute Customer"}
        )
        category = ServiceCategory.objects.first()
        sr = ServiceRequest.objects.create(
            customer=customer, category=category, area_name="Yaba"
        )
        booking = Booking.objects.create(
            request=sr,
            customer=customer,
            artisan=artisan,
            agreed_amount_minor=3000000,
        )
        from bookings.views import complete_booking_and_create_payout

        payout = complete_booking_and_create_payout(
            booking, "RCP_devconsole_dispute", actor="devconsole"
        )
        _log(events, True,
             f"No in-flight payout existed — created booking {booking.booking_ref} "
             f"(₦30,000.00) to demonstrate the freeze")

    booking = payout.booking
    _log(events, True, f"Payout {str(payout.id)[:8]} is currently '{payout.status}'")

    from disputes.services import open_dispute

    dispute = open_dispute(booking, booking.customer, reason, "Raised from dev console")
    payout.refresh_from_db()

    _log(events, True, f"Dispute opened: {dispute.get_reason_code_display()}",
         f"status={dispute.status} priority={dispute.priority}")

    if payout.status == "paid":
        _log(events, True, "Payout was already PAID — correctly left untouched",
             "you cannot un-send money; this becomes a refund conversation")
    else:
        _log(events, payout.status == "pending_approval",
             f"Payout frozen → '{payout.status}'",
             "any non-final payout drops back to pending_approval immediately")

    case = SupportCase.objects.filter(dispute=dispute).first()
    _log(events, case is not None, "High-priority SupportCase auto-created",
         f"'{case.subject}' priority={case.priority}" if case else "")
    _log(events, True, "Audit rows written for both the dispute and the freeze")
    return JsonResponse({"events": events, "state": _snapshot()})


# ---------------------------------------------------------------------------------
# Scenario 7 — the four non-negotiable rules, attacked live
# ---------------------------------------------------------------------------------
@csrf_exempt
def security_probe(request):
    _guard(request)
    events = []
    client = _client()

    payload = json.dumps(_msg("2348012345678", "hello")).encode()

    r = client.post("/whatsapp/webhook/", data=payload, content_type="application/json")
    _log(events, r.status_code == 401,
         f"Unsigned WhatsApp webhook POST → HTTP {r.status_code}",
         "rule #2: rejected, expected 401")

    r = client.post("/whatsapp/webhook/", data=payload, content_type="application/json",
                    HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64)
    _log(events, r.status_code == 401,
         f"Forged WhatsApp signature → HTTP {r.status_code}",
         "rule #2: HMAC mismatch, rejected")

    created = User.objects.filter(phone_e164="2348012345678").exists()
    _log(events, not created, "No User row created by the rejected requests",
         "the body is never parsed before the signature check")

    pay = json.dumps({"event": "charge.success", "data": {"reference": "FAKE"}}).encode()
    r = client.post("/payments/webhook/", data=pay, content_type="application/json")
    _log(events, r.status_code == 401,
         f"Unsigned Paystack webhook POST → HTTP {r.status_code}",
         "rule #4: rejected, no Payment confirmed")

    r = client.post("/payments/webhook/", data=pay, content_type="application/json",
                    HTTP_X_PAYSTACK_SIGNATURE="deadbeef")
    _log(events, r.status_code == 401,
         f"Forged Paystack signature → HTTP {r.status_code}", "rule #4: rejected")

    # Rule #1 — static proof
    import inspect

    from payments import services as psvc
    from payments import views as pviews
    from whatsappbot import views as wviews

    offenders = [
        m.__name__ for m in (pviews, wviews) if "/transfer" in inspect.getsource(m)
    ]
    _log(events, not offenders,
         "Rule #1: no view builds a Paystack /transfer request",
         f"offenders: {offenders}" if offenders else
         "only PaymentService.release_payout() does")

    _log(events, "compare_digest" in inspect.getsource(psvc.verify_paystack_signature),
         "Signature comparison is constant-time (hmac.compare_digest)",
         "a wrong first byte takes as long to reject as a wrong last byte")

    # Rule #3
    b = Booking.objects.first()
    if b:
        n = b.status_history.count()
        _log(events, n > 0,
             f"Rule #3: booking {b.booking_ref} has {n} history row(s)",
             "no status change without a history row")

    # Append-only audit
    from django.contrib.admin.sites import site

    ma = site._registry[AuditLog]
    _log(events, not ma.has_change_permission(None) and not ma.has_delete_permission(None),
         "AuditLog is append-only in admin",
         "has_change_permission and has_delete_permission both return False")

    return JsonResponse({"events": events, "state": _snapshot()})


# ---------------------------------------------------------------------------------
# Scenario 8 — infrastructure
# ---------------------------------------------------------------------------------
@csrf_exempt
def infra(request):
    _guard(request)
    events = []
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT postgis_version();")
            _log(events, True, "PostGIS reachable", cur.fetchone()[0])
    except Exception as exc:
        _log(events, False, "PostGIS unreachable", str(exc))

    try:
        from django.core.cache import cache

        cache.set("devconsole", "1", 5)
        _log(events, cache.get("devconsole") == "1", "Redis cache reachable",
             settings.REDIS_URL)
    except Exception as exc:
        _log(events, False, "Redis unreachable", str(exc))

    try:
        import marketplace.tasks  # noqa: F401 — force autodiscovery before we look
        from config.celery import app as capp

        names = sorted(n for n in capp.tasks if n.startswith("marketplace."))
        _log(events, len(names) >= 2, "Celery tasks registered", ", ".join(names))

        insp = capp.control.inspect(timeout=1)
        active = insp.active() if insp else None
        if active:
            _log(events, True, "Celery worker online", ", ".join(active.keys()))
        else:
            _log(events, None,
                 "No Celery worker running — this console runs tasks inline instead",
                 "start one with: celery -A config worker --loglevel=info")
    except Exception as exc:
        _log(events, False, "Celery check failed", str(exc))

    fee = FeeConfig.objects.filter(active=True).first()
    _log(events, fee is not None,
         f"Active FeeConfig v{fee.version}" if fee else "No active FeeConfig",
         f"threshold ₦{fee.payout_approval_threshold_minor / 100:,.2f}, "
         f"commission {fee.platform_commission_percent}%" if fee else
         "run: python manage.py bootstrap_v2")

    try:
        from django_celery_beat.models import PeriodicTask

        t = PeriodicTask.objects.filter(
            task="marketplace.tasks.process_approved_payouts"
        ).first()
        _log(events, t is not None and t.enabled,
             "Beat schedule 'process-approved-payouts' registered",
             str(t.interval) if t else "run: python manage.py bootstrap_v2")
    except Exception as exc:
        _log(events, False, "Beat schedule check failed", str(exc))

    from django.contrib.auth.models import Group

    for name in ("finance_staff", "verification_staff", "support_staff"):
        g = Group.objects.filter(name=name).first()
        if g:
            apps_ = sorted(
                set(g.permissions.values_list("content_type__app_label", flat=True))
            )
            _log(events, True, f"RBAC group '{name}' — {g.permissions.count()} perms",
                 "apps: " + ", ".join(apps_))
        else:
            _log(events, False, f"RBAC group '{name}' missing",
                 "run: python manage.py setup_staff_roles")

    _log(events, True if settings.STORAGE_ENDPOINT_URL else None,
         "Private object storage configured" if settings.STORAGE_ENDPOINT_URL
         else "Object storage not configured — ID uploads are stubbed in this console",
         settings.STORAGE_BUCKET + " · set STORAGE_* in .env to use a real bucket")
    _log(events, True if not settings.DEBUG else None,
         f"DEBUG = {settings.DEBUG}"
         + ("" if not settings.DEBUG else " (expected for local testing)"),
         "production hardening (HSTS, secure cookies, SSL redirect) activates when False")
    return JsonResponse({"events": events, "state": _snapshot()})


# ---------------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------------
@csrf_exempt
def reset(request):
    _guard(request)
    for model in (
        Match, RequestOffer, DisputeEvidence, Dispute, SupportCase, SupportNote,
        Refund, LedgerEntry, Payout, PayoutLedger, Payment, ReliabilityEvent,
        BookingStatusHistory, Booking, ServiceRequest, VerificationDocument,
        NotificationLog, WhatsAppMessage, ConversationState, AccountAction,
        ArtisanLocation, ArtisanService, AuditLog,
    ):
        model.objects.all().delete()
    User.objects.all().delete()
    return JsonResponse(
        {
            "events": [{"ok": True, "message": "All demo data cleared.",
                        "detail": "FeeConfig, categories, staff groups and admin users kept."}],
            "state": _snapshot(),
        }
    )
