"""
payments/services.py — Part 17 Step 1.

The `PaymentService` abstraction: every Paystack call in the project lives here and
nowhere else, so swapping provider later never touches booking logic.
"""

import hashlib
import hmac
import logging
import uuid

import requests
from django.conf import settings

PAYSTACK_BASE = "https://api.paystack.co"

logger = logging.getLogger(__name__)


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


class PaymentService:
    @staticmethod
    def initialize_payment(booking):
        from .models import Payment

        reference = f"BOOK-{booking.booking_ref}-{uuid.uuid4().hex[:6]}"
        payload = {
            "email": f"{booking.customer.phone_e164}@placeholder.artisanmarketplace.ng",
            "amount": booking.agreed_amount_minor,
            "reference": reference,
        }
        response = requests.post(
            f"{PAYSTACK_BASE}/transaction/initialize",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        data = response.json()
        Payment.objects.create(
            booking=booking,
            provider_reference=reference,
            amount_minor=booking.agreed_amount_minor,
            status="initiated",
        )
        return data["data"]["authorization_url"]

    @staticmethod
    def verify_payment(reference):
        response = requests.get(
            f"{PAYSTACK_BASE}/transaction/verify/{reference}",
            headers=_headers(),
            timeout=10,
        )
        return response.json()

    @staticmethod
    def resolve_bank_account(account_number, bank_code):
        """Call this BEFORE create_transfer_recipient, every time — never trust a typed
        account number."""
        response = requests.get(
            f"{PAYSTACK_BASE}/bank/resolve",
            headers=_headers(),
            params={"account_number": account_number, "bank_code": bank_code},
            timeout=10,
        )
        return response.json()

    @staticmethod
    def create_transfer_recipient(account_number, bank_code, account_name):
        payload = {
            "type": "nuban",
            "name": account_name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": "NGN",
        }
        response = requests.post(
            f"{PAYSTACK_BASE}/transferrecipient",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        data = response.json()
        return data["data"]["recipient_code"]

    @staticmethod
    def create_payout(booking, recipient_code):
        from core.models import FeeConfig

        from .models import Payout

        fee_config = FeeConfig.objects.filter(active=True).first()
        threshold = (
            fee_config.payout_approval_threshold_minor if fee_config else 5000000
        )
        status = (
            "approved"
            if booking.agreed_amount_minor < threshold
            else "pending_approval"
        )
        return Payout.objects.create(
            booking=booking,
            artisan=booking.artisan,
            amount_minor=booking.agreed_amount_minor,
            status=status,
            paystack_recipient_code=recipient_code,
        )

    @staticmethod
    def release_payout(payout):
        """
        NON-NEGOTIABLE RULE #1: this is the ONLY function in the whole project allowed
        to call Paystack's /transfer endpoint. Nothing else — no view, no admin button,
        no shell command — should ever build that request itself. If you find yourself
        about to write `requests.post(".../transfer", ...)` anywhere else, stop, and
        call this function instead.
        """
        from core.services import log_audit

        if payout.status != "approved":
            raise ValueError("Payout must be status=approved before release_payout runs.")

        reference = f"PAYOUT-{payout.id}"
        payload = {
            "source": "balance",
            "reason": f"Artisan payout for booking {payout.booking.booking_ref}",
            "amount": payout.amount_minor,
            "reference": reference,
            "recipient": payout.paystack_recipient_code,
        }
        response = requests.post(
            f"{PAYSTACK_BASE}/transfer", headers=_headers(), json=payload, timeout=10
        )
        data = response.json()

        payout.status = "processing"
        payout.paystack_transfer_code = data.get("data", {}).get("transfer_code", "")
        payout.save()

        log_audit(
            actor="system",
            action="payout_transfer_initiated",
            target=payout,
            metadata={"reference": reference},
        )
        logger.info("Transfer initiated for payout %s (ref %s)", payout.id, reference)
        return data

    @staticmethod
    def initiate_refund(payment, amount_minor, reason):
        from .models import Refund

        payload = {"transaction": payment.provider_reference, "amount": amount_minor}
        response = requests.post(
            f"{PAYSTACK_BASE}/refund", headers=_headers(), json=payload, timeout=10
        )
        Refund.objects.create(
            payment=payment,
            amount_minor=amount_minor,
            reason=reason,
            status="processing",
        )
        return response.json()


def verify_paystack_signature(request):
    signature = request.headers.get("X-Paystack-Signature", "")
    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"), request.body, hashlib.sha512
    ).hexdigest()
    # hmac.compare_digest instead of a plain ==: constant time, so rejecting a signature
    # wrong in the first byte takes as long as one wrong in the last byte.
    return hmac.compare_digest(signature, computed)
