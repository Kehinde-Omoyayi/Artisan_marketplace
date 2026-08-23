"""marketplace — Part 5. Geospatial matching tables (fills in the empty V1 app)."""

import uuid

from django.contrib.gis.db import models

from accounts.models import User
from job_requests.models import ServiceRequest


def generate_offer_code():
    return uuid.uuid4().hex[:6].upper()


class ArtisanLocation(models.Model):
    artisan = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="location"
    )
    point = models.PointField(geography=True, srid=4326)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Location of {self.artisan}"


class ServiceArea(models.Model):
    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="service_areas"
    )
    radius_km = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.artisan} — {self.radius_km}km radius"


class AvailabilitySlot(models.Model):
    DAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="availability_slots"
    )
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return (
            f"{self.artisan} — {self.get_day_of_week_display()} "
            f"{self.start_time}-{self.end_time}"
        )


class Match(models.Model):
    RESPONSE_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("expired", "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="matches"
    )
    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="matches_received"
    )
    distance_km = models.DecimalField(max_digits=6, decimal_places=2)
    ranking_score = models.DecimalField(max_digits=8, decimal_places=4)
    ranking_version = models.CharField(max_length=20)
    rank_position = models.PositiveSmallIntegerField()
    # --- V2 addition: accept/decline over WhatsApp (Part 24) ---
    # Short code so "YES A1B2C3" is unambiguous when an artisan has more than one
    # open offer at once. Not globally unique on purpose (we always filter by
    # artisan too) — a 16.7M-value space makes collisions a non-issue in practice.
    offer_code = models.CharField(
        max_length=6,
        db_index=True,
        default=generate_offer_code,
        editable=False,
    )
    response_status = models.CharField(
        max_length=20, choices=RESPONSE_CHOICES, default="pending"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("request", "artisan")
        ordering = ("rank_position",)

    def __str__(self):
        return (
            f"{self.request} → {self.artisan} "
            f"(score {self.ranking_score}, rank {self.rank_position})"
        )
