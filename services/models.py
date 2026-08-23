"""
services — V1 app, unchanged in V2 ("Apps that stay exactly as V1 left them", Part 0).

`ArtisanArea` is deliberately kept even though V2 introduces real coordinates in
`marketplace.ArtisanLocation`: it still drives display text like "serves Yaba, Surulere".
"""

from django.db import models

from accounts.models import User


class ServiceCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.CharField(max_length=250, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "service categories"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ArtisanService(models.Model):
    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="artisan_services"
    )
    service = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name="artisans"
    )
    base_price_minor = models.BigIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("artisan", "service")

    def __str__(self):
        return f"{self.artisan} — {self.service}"


class ArtisanArea(models.Model):
    """V1 text-based coverage. Kept for display; matching now uses PostGIS."""

    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="artisan_areas"
    )
    area_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("artisan", "area_name")

    def __str__(self):
        return f"{self.artisan} — {self.area_name}"
