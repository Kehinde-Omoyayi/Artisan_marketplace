"""
webchat/services.py — OTP issuance/verification and the transcript the browser chat
widget polls. See models.py for the security rationale behind the OTP step.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import User

from .models import PhoneVerificationCode, WebChatMessage, WebChatSession
from .sms_backends import send_otp_sms

logger = logging.getLogger(__name__)


def _otp_ttl_seconds():
    return getattr(settings, "WEBCHAT_OTP_TTL_SECONDS", 300)


def _resend_cooldown_seconds():
    return getattr(settings, "WEBCHAT_OTP_RESEND_COOLDOWN_SECONDS", 45)


def _active_window_hours():
    return getattr(settings, "WEBCHAT_ACTIVE_WINDOW_HOURS", 24)


def get_or_create_session(session_key):
    session, _ = WebChatSession.objects.get_or_create(session_key=session_key)
    return session


def touch_session(session_key):
    WebChatSession.objects.filter(session_key=session_key).update(
        last_seen_at=timezone.now()
    )


def bound_phone_for_session(session_key):
    """Returns the verified phone_e164 for this browser session, or None."""
    session = (
        WebChatSession.objects.filter(session_key=session_key)
        .select_related("user")
        .first()
    )
    if session and session.user_id:
        touch_session(session_key)
        return session.user.phone_e164
    return None


def request_phone_code(session_key, phone_e164):
    """Issues and attempts delivery of a fresh OTP. Returns (ok, detail_dict).

    Locks on (session_key, phone_e164) for the duration of the check-and-issue so
    two near-simultaneous "resend" clicks from the same tab can't both slip past the
    cooldown check and both dispatch a paid SMS.
    """
    with transaction.atomic():
        recent = (
            PhoneVerificationCode.objects.select_for_update()
            .filter(session_key=session_key, phone_e164=phone_e164)
            .order_by("-created_at")
            .first()
        )
        if recent:
            elapsed = (timezone.now() - recent.created_at).total_seconds()
            cooldown = _resend_cooldown_seconds()
            if elapsed < cooldown:
                return False, {"retry_after_seconds": max(int(cooldown - elapsed), 1)}

        _record, code = PhoneVerificationCode.issue(
            session_key, phone_e164, _otp_ttl_seconds()
        )

    # Delivery happens outside the transaction — an SMS provider's network latency
    # (up to the 10s timeout in sms_backends) has no business holding a DB row lock
    # or a Postgres connection open.
    delivery = send_otp_sms(phone_e164, code)
    logger.info(
        "OTP issued for %s via %s (session %s\u2026)",
        phone_e164,
        delivery["channel"],
        session_key[:8],
    )

    detail = {
        "expires_in_seconds": _otp_ttl_seconds(),
        "delivery_channel": delivery["channel"],
    }
    # Only ever echo the code back when nothing could actually deliver it AND we're
    # in DEBUG — mirrors devconsole's "exercisable with no real provider account,
    # never in production" approach. In production DEBUG is False, so this branch
    # is structurally unreachable there regardless of provider configuration.
    if delivery["channel"] == "console" and settings.DEBUG:
        detail["debug_code"] = code
    return True, detail


def confirm_phone_code(session_key, phone_e164, code):
    """Returns (True, User) on success, or (False, reason) where reason is one of
    "expired_or_missing" | "incorrect" | "locked".

    `select_for_update()` serializes concurrent verification attempts against the
    *same* outstanding code (e.g. a double-tapped Verify button, or two tabs open
    to the same phone number) so two requests can't both observe "still valid" and
    both act on it — one wins the row lock, consumes the code, and binds the
    session; the other blocks briefly and then correctly sees it already consumed.
    """
    with transaction.atomic():
        record = (
            PhoneVerificationCode.objects.select_for_update()
            .filter(session_key=session_key, phone_e164=phone_e164, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if not record:
            return False, "expired_or_missing"
        # Checked before touching verify_code so the reason reported back is
        # accurate: a maxed-out code is locked, not merely "expired", even though
        # is_valid() (verify_code's own internal guard) would also correctly block
        # it either way — this is about giving the right explanation, not the
        # underlying protection, which holds regardless of message wording.
        if record.attempts >= record.MAX_ATTEMPTS:
            return False, "locked"
        if record.expires_at <= timezone.now():
            return False, "expired_or_missing"
        if not record.verify_code(code):
            return False, "locked" if record.attempts >= record.MAX_ATTEMPTS else "incorrect"

        user, _ = User.objects.get_or_create(
            phone_e164=phone_e164, defaults={"role": "customer"}
        )
        session = get_or_create_session(session_key)
        session.user = user
        session.save(update_fields=["user"])

    touch_session(session_key)
    return True, user


def is_webchat_user(user):
    """Used by notifications.services to decide whether a reply belongs in the chat
    transcript instead of WhatsApp/email. Scoped to a recent window so a browser
    tab closed for good doesn't permanently steal a user's WhatsApp delivery."""
    if not user or not user.pk:
        return False
    cutoff = timezone.now() - timezone.timedelta(hours=_active_window_hours())
    return WebChatSession.objects.filter(
        user_id=user.pk, last_seen_at__gte=cutoff
    ).exists()


def log_inbound(phone_e164, body, kind="text"):
    return WebChatMessage.objects.create(
        phone_e164=phone_e164, direction="in", body=body, kind=kind
    )


def log_outbound(phone_e164, body, kind="text"):
    return WebChatMessage.objects.create(
        phone_e164=phone_e164, direction="out", body=body, kind=kind
    )


def latest_message_id(phone_e164):
    return (
        WebChatMessage.objects.filter(phone_e164=phone_e164).aggregate(m=Max("id"))["m"]
        or 0
    )


def messages_since(phone_e164, since_id):
    qs = WebChatMessage.objects.filter(phone_e164=phone_e164)
    if since_id:
        qs = qs.filter(id__gt=since_id)
    return list(qs.order_by("id"))
