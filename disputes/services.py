"""
disputes/services.py — Part 8 Step 2.

Enforces the V2 blueprint rule that opening a dispute IMMEDIATELY freezes any related
payout that has not already gone out.
"""

from django.db import transaction

from support_app.models import SupportCase

from .models import Dispute


@transaction.atomic
def open_dispute(booking, raised_by, reason_code, description=""):
    from core.services import log_audit
    from payments.models import Payout

    dispute = Dispute.objects.create(
        booking=booking,
        raised_by=raised_by,
        reason_code=reason_code,
        description=description,
    )

    frozen = Payout.objects.filter(booking=booking).exclude(
        status__in=("paid", "failed")
    )
    for payout in frozen:
        payout.status = "pending_approval"
        payout.save()
        log_audit(
            actor=str(raised_by),
            action="payout_frozen_by_dispute",
            target=payout,
            metadata={"dispute_id": str(dispute.id)},
        )

    SupportCase.objects.create(
        booking=booking,
        dispute=dispute,
        subject=f"Dispute: {dispute.get_reason_code_display()}",
        priority="high",
    )

    log_audit(actor=str(raised_by), action="dispute_opened", target=dispute)
    return dispute
