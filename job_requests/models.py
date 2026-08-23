"""
job_requests — V1 app, upgraded in V2 Part 5 Step 1 with a real coordinate field.

`area_name` (V1 text matching) stays exactly where it was — it is still the display
value and the fallback. `location` is added alongside it, nullable because historical
V1 requests have no coordinates.
"""

import uuid

from django.contrib.gis.db import models as gis_models
from django.db import models

from accounts.models import User
from services.models import ServiceCategory


class ServiceRequest(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("matched", "Matched"),
        ("booked", "Booked"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]
    TIMING_CHOICES = [
        ("Today", "Today"),
        ("This week", "This week"),
        ("Flexible", "Flexible"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="service_requests"
    )
    category = models.ForeignKey(
        ServiceCategory, on_delete=models.PROTECT, related_name="requests"
    )
    area_name = models.CharField(max_length=100)
    # --- V2 addition (Part 5 Step 1) ---
    location = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    timing = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.category} in {self.area_name} for {self.customer}"


class RequestOffer(models.Model):
    """An offer sent to a specific artisan for a specific request (V1)."""

    RESPONSE_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("expired", "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="offers"
    )
    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="offers_received"
    )
    response_status = models.CharField(
        max_length=20, choices=RESPONSE_CHOICES, default="pending"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("request", "artisan")
        ordering = ("-created_at",)

    def __str__(self):
        return f"Offer {self.request} → {self.artisan} ({self.response_status})"
