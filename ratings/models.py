"""
ratings — V1 app, unchanged in V2 (Part 0: "Apps that stay exactly as V1 left them").

Reliability signals deliberately do NOT live here — see bookings.ReliabilityEvent.
A rating is an opinion; a reliability event is a fact.
"""

from django.db import models

from accounts.models import User
from bookings.models import Booking


class Rating(models.Model):
    booking = models.OneToOneField(
        Booking, on_delete=models.PROTECT, related_name="rating"
    )
    rated_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="ratings_given"
    )
    artisan = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="ratings_received"
    )
    stars = models.PositiveSmallIntegerField()
    comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.stars}★ for {self.artisan}"
