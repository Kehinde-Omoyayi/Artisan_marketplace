"""
payments/views.py — Part 17 Step 2 (+ Part 18.3 rate limiting).

The webhook now handles charge confirmation (V1's job) AND transfer results (new in V2).

NON-NEGOTIABLE RULE #4: never mark a Payment confirmed, or a Payout paid/failed,
anywhere except inside this signature-checked webhook. A transfer that "looks"
successful in your own logs is not proof — only this webhook is proof.
"""

import json
import logging

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from bookings.views import change_booking_status
from core.services import log_audit

from .models import Payment, Payout
from .services import verify_paystack_signature

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(
    ratelimit(key="ip", rate="60/m", method="POST", block=True), name="post"
)
class PaystackWebhookView(View):
    def post(self, request):
        # NON-NEGOTIABLE RULE (from V1, now guarding TWO kinds of event, not one):
        # never trust anything in this body until the signature checks out.
        if not verify_paystack_signature(request):
            return JsonResponse({"status": "invalid signature"}, status=401)

        event = json.loads(request.body.decode("utf-8"))
        event_type = event.get("event")

        if event_type == "charge.success":
            self._handle_charge_success(event)
        elif event_type == "transfer.success":
            self._handle_transfer_result(event, "paid")
        elif event_type in ("transfer.failed", "transfer.reversed"):
            self._handle_transfer_result(event, "failed")

        return JsonResponse({"status": "ok"})

    def _handle_charge_success(self, event):
        reference = event["data"]["reference"]
        payment = Payment.objects.filter(provider_reference=reference).first()
        if payment and payment.status != "confirmed":
            payment.status = "confirmed"
            payment.save()
            change_booking_status(payment.booking, "payment_confirmed")
            log_audit(
                actor="paystack_webhook", action="charge_confirmed", target=payment
            )

    def _handle_transfer_result(self, event, new_status):
        transfer_code = event["data"]["transfer_code"]
        payout = Payout.objects.filter(paystack_transfer_code=transfer_code).first()
        if payout and payout.status != new_status:
            payout.status = new_status
            payout.save()
            log_audit(
                actor="paystack_webhook",
                action=f"transfer_{new_status}",
                target=payout,
            )
