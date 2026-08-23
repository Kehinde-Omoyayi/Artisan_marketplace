"""
The four non-negotiable rules from the manual, expressed as tests that fail loudly
if anyone ever breaks them.

  #1 Only PaymentService.release_payout() may call Paystack's /transfer endpoint.
  #2 No WhatsApp webhook POST is processed without a valid X-Hub-Signature-256.
  #3 No status change without a history/audit row.
  #4 A Payment is only confirmed, and a Payout only paid/failed, inside the
     signature-checked Paystack webhook.
"""

import hashlib
import hmac
import inspect
import json

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse


class RuleOneTransferEndpointIsolation(TestCase):
    """Rule #1 — /transfer may only be built inside release_payout."""

    def test_only_release_payout_builds_a_transfer_request(self):
        from payments import services

        source = inspect.getsource(services)
        # Every occurrence of the transfer URL must be inside release_payout.
        release_src = inspect.getsource(services.PaymentService.release_payout)
        total = source.count('f"{PAYSTACK_BASE}/transfer"')
        inside = release_src.count('f"{PAYSTACK_BASE}/transfer"')
        self.assertEqual(total, 1, "The /transfer URL appears more than once in payments.services")
        self.assertEqual(inside, 1, "release_payout no longer builds the /transfer request")

    def test_no_other_module_posts_to_transfer(self):
        from bookings import views as booking_views
        from marketplace import tasks
        from payments import admin as payments_admin
        from payments import views as payment_views
        from whatsappbot import views as bot_views

        for module in (booking_views, tasks, payments_admin, payment_views, bot_views):
            src = inspect.getsource(module)
            self.assertNotIn(
                "/transfer",
                src,
                f"{module.__name__} references Paystack's transfer endpoint directly",
            )

    def test_release_payout_refuses_unapproved_payout(self):
        from payments.services import PaymentService

        class FakePayout:
            status = "pending_approval"

        with self.assertRaises(ValueError):
            PaymentService.release_payout(FakePayout())


@override_settings(
    WHATSAPP_APP_SECRET="test-app-secret",
    USE_LOCMEM_CACHE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    RATELIMIT_ENABLE=False,
)
class RuleTwoWhatsAppSignature(TestCase):
    """Rule #2 — an unsigned or wrongly-signed webhook POST is rejected with 401."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("whatsapp-webhook")
        self.body = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "2348012345678",
                                        "type": "text",
                                        "text": {"body": "hello"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    def _sign(self, raw, secret="test-app-secret"):
        return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    def test_missing_signature_is_rejected(self):
        response = self.client.post(
            self.url, data=json.dumps(self.body), content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_signature_is_rejected(self):
        raw = json.dumps(self.body).encode()
        response = self.client.post(
            self.url,
            data=raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(raw, secret="the-wrong-secret"),
        )
        self.assertEqual(response.status_code, 401)

    def test_no_user_row_is_created_by_an_unsigned_request(self):
        from accounts.models import User

        self.client.post(
            self.url, data=json.dumps(self.body), content_type="application/json"
        )
        self.assertFalse(User.objects.filter(phone_e164="2348012345678").exists())

    def test_signature_helper_is_constant_time(self):
        from whatsappbot import security

        self.assertIn("compare_digest", inspect.getsource(security.verify_whatsapp_signature))

    def test_get_handshake_still_works(self):
        with override_settings(WHATSAPP_VERIFY_TOKEN="tok"):
            response = self.client.get(
                self.url,
                {
                    "hub.mode": "subscribe",
                    "hub.verify_token": "tok",
                    "hub.challenge": "12345",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "12345")


@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_signaturetest",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    RATELIMIT_ENABLE=False,
)
class RuleFourPaystackWebhook(TestCase):
    """Rule #4 — money state only changes inside the signature-checked webhook."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("paystack-webhook")

    def test_unsigned_charge_success_is_rejected(self):
        body = json.dumps({"event": "charge.success", "data": {"reference": "X"}})
        response = self.client.post(self.url, data=body, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_signed_transfer_success_marks_payout_paid(self):
        from accounts.models import User
        from bookings.models import Booking
        from job_requests.models import ServiceRequest
        from payments.models import Payout
        from services.models import ServiceCategory

        customer = User.objects.create(phone_e164="2348011111111")
        artisan = User.objects.create(phone_e164="2348022222222", role="artisan")
        category = ServiceCategory.objects.create(name="Plumbing", slug="plumbing")
        req = ServiceRequest.objects.create(
            customer=customer, category=category, area_name="Yaba"
        )
        booking = Booking.objects.create(
            request=req, customer=customer, artisan=artisan, agreed_amount_minor=100000
        )
        payout = Payout.objects.create(
            booking=booking,
            artisan=artisan,
            amount_minor=100000,
            status="processing",
            paystack_transfer_code="TRF_abc123",
        )

        body = json.dumps(
            {"event": "transfer.success", "data": {"transfer_code": "TRF_abc123"}}
        ).encode()
        signature = hmac.new(
            b"sk_test_signaturetest", body, hashlib.sha512
        ).hexdigest()

        response = self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 200)

        payout.refresh_from_db()
        self.assertEqual(payout.status, "paid")

        # Rule #3 — the status change wrote an audit row.
        from core.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="transfer_paid", target_id=str(payout.id)
            ).exists()
        )
