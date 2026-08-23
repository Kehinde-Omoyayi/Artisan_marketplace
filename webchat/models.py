"""
webchat — the web-based replacement transport for the conversation engine that used
to be reachable only over WhatsApp.

Every business rule (customer request flow, artisan onboarding, offer accept/decline,
ID capture) still lives in whatsappbot/views.py's state machine, keyed by
`phone_e164` exactly as before — this app only supplies:

  1. A way to prove "this browser tab speaks for this phone number" (WhatsApp gets
     this for free from Meta; a web form has to earn it with an OTP), and
  2. A transcript the browser can poll to render as a chat window.

Nothing here bypasses a non-negotiable rule from the README — this app never touches
Paystack, never changes a Booking/Payout/Dispute status itself, and never processes
a WhatsApp webhook. It is a new front door to the same house.
"""

import hashlib
import secrets
import uuid

from django.db import models, transaction
from django.utils import timezone


def _hash_code(code, salt):
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


class WebChatSession(models.Model):
    """One row per browser session that has talked to the chat widget.

    `session_key` is Django's own session key — never a value the client can set
    itself — so the phone binding lives exactly as long as the session cookie does
    and is exactly as hard to hijack as any other Django session.
    """

    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="webchat_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "last_seen_at"])]

    def __str__(self):
        return f"session {self.session_key[:8]}\u2026 \u2192 {self.user or 'unverified'}"


class PhoneVerificationCode(models.Model):
    """A one-time code proving control of a phone number for the web channel.

    WhatsApp gives phone-ownership proof for free: Meta only calls the webhook for a
    message that genuinely came from that WhatsApp number. A web text box does not —
    anyone can type any digits in — so the web channel does its own proof of
    ownership before a browser session is ever allowed to act as somebody's phone
    identity. Codes are stored hashed+salted, never in plaintext.
    """

    MAX_ATTEMPTS = 5

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=40, db_index=True)
    phone_e164 = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=64)
    salt = models.CharField(max_length=16)
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["session_key", "phone_e164", "-created_at"])]

    def __str__(self):
        return f"OTP for {self.phone_e164} ({'used' if self.consumed_at else 'active'})"

    @classmethod
    def issue(cls, session_key, phone_e164, ttl_seconds):
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(8)
        obj = cls.objects.create(
            session_key=session_key,
            phone_e164=phone_e164,
            code_hash=_hash_code(code, salt),
            salt=salt,
            expires_at=timezone.now() + timezone.timedelta(seconds=ttl_seconds),
        )
        return obj, code

    def is_valid(self):
        return (
            self.consumed_at is None
            and self.expires_at > timezone.now()
            and self.attempts < self.MAX_ATTEMPTS
        )

    def verify_code(self, code):
        """Verifies `code`. Always records the attempt, even on a miss, so a
        brute-force loop against one code is capped at MAX_ATTEMPTS regardless of
        how the caller behaves."""
        if not self.is_valid():
            return False
        if self.code_hash == _hash_code(code, self.salt):
            self.consumed_at = timezone.now()
            self.save(update_fields=["consumed_at"])
            return True
        self.attempts = models.F("attempts") + 1
        self.save(update_fields=["attempts"])
        self.refresh_from_db(fields=["attempts"])
        return False


class WebChatMessage(models.Model):
    """The transcript the chat widget renders and polls.

    Mirrors whatsappbot.WhatsAppMessage (direction + phone_e164 as the identity key)
    so the two channels stay directly comparable, but stores a plain text `body`
    instead of a raw provider payload, since there's no provider envelope to keep
    here — the browser IS the provider.
    """

    DIRECTION_CHOICES = [("in", "From visitor"), ("out", "From platform")]
    KIND_CHOICES = [
        ("text", "Text"),
        ("location", "Location shared"),
        ("image", "Image uploaded"),
        ("system", "System"),
    ]

    phone_e164 = models.CharField(max_length=20, db_index=True)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    body = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="text")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("id",)
        indexes = [models.Index(fields=["phone_e164", "id"])]

    def __str__(self):
        return f"{self.direction} {self.phone_e164}: {self.body[:40]}"
