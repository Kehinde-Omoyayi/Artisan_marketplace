"""notifications — Part 12. WhatsApp with an email fallback, every attempt logged."""

import uuid

from django.db import models

from accounts.models import User


class NotificationLog(models.Model):
    CHANNEL_CHOICES = [
        ("webchat", "Web Chat"),
        ("whatsapp", "WhatsApp"),
        ("email", "Email"),
    ]
    STATUS_CHOICES = [("sent", "Sent"), ("failed", "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    template_name = models.CharField(max_length=80)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error_message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.channel} to {self.user} ({self.status})"
