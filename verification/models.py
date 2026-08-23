"""verification — Part 6. Staged verification levels L0-L4."""

import uuid

from django.db import models

from accounts.models import User


class VerificationDocument(models.Model):
    LEVEL_CHOICES = [
        ("L2", "L2 — Government ID"),
        ("L3", "L3 — Service-area / address verification"),
        ("L4", "L4 — Skill reference or certificate"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artisan = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="verification_documents"
    )
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES)
    # Path inside the PRIVATE object-storage bucket. Never a public URL.
    storage_key = models.CharField(max_length=300)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending"
    )
    # auth.User = a staff member who logs into /admin, NOT accounts.User.
    reviewed_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.artisan} — {self.level} ({self.status})"
