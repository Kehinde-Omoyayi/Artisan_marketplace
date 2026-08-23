"""core — Part 13. Feature flags, versioned fee config, append-only audit log."""

import uuid

from django.db import models


class FeatureFlag(models.Model):
    key = models.SlugField(unique=True)
    is_enabled = models.BooleanField(default=False)
    description = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key} ({'ON' if self.is_enabled else 'OFF'})"


class FeeConfig(models.Model):
    version = models.PositiveIntegerField(unique=True)
    platform_commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    # 5,000,000 kobo = ₦50,000. Payouts at or above this need a human approval.
    payout_approval_threshold_minor = models.BigIntegerField(default=5000000)
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version",)

    def __str__(self):
        return f"FeeConfig v{self.version} ({'active' if self.active else 'inactive'})"


class AuditLog(models.Model):
    """Append-only by convention; the admin removes change/delete (Part 13 Step 3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=60)
    target_id = models.CharField(max_length=60)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.action} on {self.target_type}:{self.target_id} by {self.actor}"
