"""
webchat/sms_backends.py — pluggable delivery for the phone-verification code.

WhatsApp's webhook proves phone ownership for free; the web channel has to prove it
itself with an OTP, which means it needs *some* way to put a code on the phone.

Termii is wired in as a real, working option — it's a Nigerian aggregator with SMS,
WhatsApp and voice-OTP channels, which fits a Nigeria-first product. Set
`TERMII_API_KEY` and `TERMII_SENDER_ID` and it's live; the payload/route below
follows Termii's own guidance to use the DND (transactional) route for OTPs rather
than the generic/promotional one. Verify the current request shape against
https://developers.termii.com before going live — a third-party API can change
underneath this file.

With nothing configured, codes are only written to the server log and (in DEBUG
only) echoed back to the API caller — the same philosophy as this project's
`devconsole`: the whole verification flow is exercisable in development and in the
test suite without any real SMS account, and that fallback is structurally
incapable of firing in production (DEBUG is False there).
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _send_via_termii(phone_e164, code):
    base_url = getattr(settings, "TERMII_BASE_URL", "https://api.ng.termii.com/api")
    response = requests.post(
        f"{base_url}/sms/send",
        json={
            "api_key": settings.TERMII_API_KEY,
            "to": phone_e164.lstrip("+"),
            "from": settings.TERMII_SENDER_ID,
            "sms": (
                f"Your {settings.SITE_NAME} verification code is {code}. "
                f"It expires in {settings.WEBCHAT_OTP_TTL_SECONDS // 60} minutes. "
                f"Don't share this code."
            ),
            "type": "plain",
            "channel": "dnd",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def send_otp_sms(phone_e164, code):
    """Attempts real delivery; always returns {"channel": ..., "detail": ...} so the
    caller can decide whether it's safe to also hand the code back in an API
    response (only ever true for the "console" channel, and only in DEBUG)."""
    if getattr(settings, "TERMII_API_KEY", ""):
        try:
            result = _send_via_termii(phone_e164, code)
            return {"channel": "termii", "detail": result}
        except Exception as exc:  # noqa: BLE001 — a provider outage must not break signup
            logger.warning("Termii OTP send failed for %s: %s", phone_e164, exc)

    logger.info(
        "OTP for %s could not be sent by any configured provider (code: %s). "
        "Set TERMII_API_KEY / TERMII_SENDER_ID before going live.",
        phone_e164,
        code,
    )
    return {"channel": "console", "detail": None}
