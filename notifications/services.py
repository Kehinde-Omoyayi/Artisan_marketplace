"""notifications/services.py — Part 12 Step 2. The single outbound-message gateway."""

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

from .models import NotificationLog

logger = logging.getLogger(__name__)


def _send_whatsapp(to_phone, body_text):
    url = (
        f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": body_text},
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()


def _is_webchat_user(user):
    # Local import: webchat depends on notifications.models (for the "webchat"
    # channel choice used nowhere else but conceptually shared), so importing
    # webchat.services at module load time here would risk a circular import
    # depending on Django's app-loading order. Importing inside the function call
    # avoids that entirely and costs nothing at runtime.
    from webchat.services import is_webchat_user

    return is_webchat_user(user)


def send_notification(user, template_name, body_text, email_subject=None):
    """
    Delivery order: the web chat transcript first, if this user currently has an
    active browser session on the website — no WhatsApp/email attempt is made in
    that case, so the project works with zero WhatsApp or SMTP credentials
    configured for anyone using the web channel. Otherwise, tries WhatsApp, then
    falls back to email if the user has one on file. Logs the outcome either way.

    This is the ONE place in the whole project that sends an outbound message —
    every other app should call this function, not requests.post to Meta (or
    Termii, or anything else) directly.
    """
    if user is not None and _is_webchat_user(user):
        from webchat.services import log_outbound

        log_outbound(user.phone_e164, body_text)
        NotificationLog.objects.create(
            user=user,
            channel="webchat",
            template_name=template_name,
            payload={"body": body_text},
            status="sent",
        )
        return True

    try:
        _send_whatsapp(user.phone_e164, body_text)
        NotificationLog.objects.create(
            user=user,
            channel="whatsapp",
            template_name=template_name,
            payload={"body": body_text},
            status="sent",
        )
        return True
    except Exception as exc:  # noqa: BLE001 — any failure must fall through to email
        logger.warning("WhatsApp send failed for %s: %s", user, exc)
        NotificationLog.objects.create(
            user=user,
            channel="whatsapp",
            template_name=template_name,
            payload={"body": body_text},
            status="failed",
            error_message=str(exc)[:300],
        )

    email = getattr(user, "email", None)
    if not email:
        return False

    try:
        send_mail(
            subject=email_subject or "Update from Nigeria Artisan Marketplace",
            message=body_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )
        NotificationLog.objects.create(
            user=user,
            channel="email",
            template_name=template_name,
            payload={"body": body_text},
            status="sent",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email fallback failed for %s: %s", user, exc)
        NotificationLog.objects.create(
            user=user,
            channel="email",
            template_name=template_name,
            payload={"body": body_text},
            status="failed",
            error_message=str(exc)[:300],
        )
        return False
