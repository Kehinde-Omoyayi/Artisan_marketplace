"""
payments — V1 `Payment` and `PayoutLedger`, upgraded in Part 7 with the double-entry
style `LedgerEntry`, the structured `Payout`, and `Refund`.

`amount_minor` EVERYWHERE in this project means kobo, not naira. ₦50,000 is 5000000.

`Payout` replaces `PayoutLedger` for every booking going forward. `PayoutLedger` stays
in the codebase only because V1's historical payout data lives there (Part 20 backfills
it into LedgerEntry). Never write to PayoutLedger again.
"""

import uuid

from django.db import models

from accounts.models import User
from bookings.models import Booking


class Payment(models.Model):
    STATUS_CHOICES = [
        ("initiated", "Initiated"),
        ("confirmed", "Confirmed"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="payments"
    )
    provider = models.CharField(max_length=30, default="paystack")
    provider_reference = models.CharField(max_length=100, unique=True, db_index=True)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="initiated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Payment {self.provider_reference} ({self.status})"


class PayoutLedger(models.Model):
    """V1 manual payout record. Historical only — do not write new rows here."""

    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="payout_ledgers"
    )
    artisan = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="payout_ledgers"
    )
    amount_minor = models.BigIntegerField()
    note = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"V1 payout {self.amount_minor} to {self.artisan}"


# --- V2 additions, Part 7 Step 1 ---
class LedgerEntry(models.Model):
    ENTRY_TYPE_CHOICES = [
        ("charge", "Customer Charge"),
        ("platform_fee", "Platform Fee"),
        ("artisan_earning", "Artisan Earning"),
        ("refund", "Refund"),
        ("adjustment", "Adjustment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "ledger entries"

    def __str__(self):
        return f"{self.entry_type} {self.amount_minor} — {self.booking}"


class Payout(models.Model):
    STATUS_CHOICES = [
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("processing", "Processing"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="structured_payouts"
    )
    artisan = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="payouts"
    )
    amount_minor = models.BigIntegerField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending_approval"
    )
    paystack_recipient_code = models.CharField(max_length=100, blank=True)
    paystack_transfer_code = models.CharField(max_length=100, blank=True)
    approved_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Payout {self.amount_minor} to {self.artisan} ({self.status})"


class Refund(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="refunds"
    )
    amount_minor = models.BigIntegerField()
    reason = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Refund {self.amount_minor} for {self.payment}"
