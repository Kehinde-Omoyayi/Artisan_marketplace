"""disputes — Part 8. Structured reason codes, evidence, case assignment."""

import uuid

from django.db import models

from accounts.models import User
from bookings.models import Booking


class Dispute(models.Model):
    REASON_CHOICES = [
        ("not_completed", "Job Not Completed"),
        ("different_service", "Materially Different Service"),
        ("poor_work", "Poor Quality Work"),
        ("no_show", "No Show"),
        ("price_change", "Price Changed Without Agreement"),
        ("safety_concern", "Safety Concern"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("investigating", "Investigating"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="disputes"
    )
    raised_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="disputes_raised"
    )
    reason_code = models.CharField(max_length=30, choices=REASON_CHOICES)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="normal"
    )
    assigned_to = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disputes_assigned",
    )
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Dispute on {self.booking} — {self.reason_code} ({self.status})"


class DisputeEvidence(models.Model):
    dispute = models.ForeignKey(
        Dispute, on_delete=models.CASCADE, related_name="evidence"
    )
    # Same rule as verification.VerificationDocument: private bucket, never a public URL.
    storage_key = models.CharField(max_length=300)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "dispute evidence"

    def __str__(self):
        return f"Evidence for {self.dispute}"
