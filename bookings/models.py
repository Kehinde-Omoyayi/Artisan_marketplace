"""
bookings — V1 app (`Booking`, `BookingStatusHistory`), upgraded in V2 Part 10
with `ReliabilityEvent`.

ReliabilityEvent lives here, not in `ratings`, on purpose: it records a *fact about a
job* (someone did not show up), not an *opinion about a job* (a star rating).
"""

import uuid

from django.db import models

from accounts.models import User
from job_requests.models import ServiceRequest


class Booking(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("payment_pending", "Payment Pending"),
        ("payment_confirmed", "Payment Confirmed"),
        ("in_progress", "In Progress"),
        ("artisan_completed", "Artisan Marked Complete"),
        ("customer_completed", "Customer Confirmed Complete"),
        ("cancelled", "Cancelled"),
        ("disputed", "Disputed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_ref = models.CharField(max_length=36, unique=True, default=uuid.uuid4, db_index=True)
    request = models.ForeignKey(
        ServiceRequest, on_delete=models.PROTECT, related_name="bookings"
    )
    customer = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="bookings_as_customer"
    )
    artisan = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="bookings_as_artisan"
    )
    agreed_amount_minor = models.BigIntegerField(default=0)  # kobo, never naira
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")
    scheduled_for = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        if not self.booking_ref:
            self.booking_ref = f"BK{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.booking_ref} ({self.status})"


class BookingStatusHistory(models.Model):
    """Non-negotiable rule (V1, still true): never change status without a row here."""

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    actor = models.CharField(max_length=150, blank=True)
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "booking status histories"

    def __str__(self):
        return f"{self.booking} — {self.from_status} → {self.to_status}"


# --- V2 addition, Part 10 Step 1 ---
class ReliabilityEvent(models.Model):
    EVENT_CHOICES = [
        ("late_cancel_customer", "Customer Cancelled Late"),
        ("late_cancel_artisan", "Artisan Cancelled Late"),
        ("no_show_customer", "Customer No-Show"),
        ("no_show_artisan", "Artisan No-Show"),
    ]

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="reliability_events"
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    logged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.event_type} — {self.booking}"
