"""
support_app — V1 `SupportNote`, upgraded in Part 9 with `SupportCase`.

Note the string reference "disputes.Dispute" instead of a direct import: it avoids the
circular import that would otherwise happen, because `disputes/services.py` imports
from `support_app`. One direction uses a normal import, the other uses the
"app_label.ModelName" string.
"""

import uuid

from django.db import models

from accounts.models import User
from bookings.models import Booking


class SupportNote(models.Model):
    """V1 freeform note. Kept — SupportCase does not delete it."""

    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name="support_notes",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Note on {self.booking}"


# --- V2 addition, Part 9 Step 1 ---
class SupportCase(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("closed", "Closed"),
    ]
    PRIORITY_CHOICES = [("low", "Low"), ("normal", "Normal"), ("high", "High")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name="support_cases",
        null=True,
        blank=True,
    )
    dispute = models.ForeignKey(
        "disputes.Dispute",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_case",
    )
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="normal"
    )
    assigned_to = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_cases_assigned",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Case on {self.booking} — {self.subject} ({self.status})"
