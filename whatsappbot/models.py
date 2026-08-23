"""whatsappbot — V1 models: raw message log and per-number conversation state."""

import uuid

from django.db import models


class WhatsAppMessage(models.Model):
    DIRECTION_CHOICES = [("in", "Inbound"), ("out", "Outbound")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_e164 = models.CharField(max_length=20, db_index=True)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.direction} {self.phone_e164}"


class ConversationState(models.Model):
    phone_e164 = models.CharField(max_length=20, unique=True, db_index=True)
    state = models.CharField(max_length=50, default="start")
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.phone_e164} @ {self.state}"
