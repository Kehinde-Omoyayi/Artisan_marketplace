"""
whatsappbot/security.py — Part 18.1.

Meta signs every webhook POST with your App Secret using HMAC-SHA256, sent in the
X-Hub-Signature-256 header as `sha256=<hex>`. Without this check, anyone who discovers
your webhook URL can send fake "messages" that create fake bookings or trigger fake
artisan notifications.

NON-NEGOTIABLE RULE #2: never process a WhatsApp webhook POST without this passing.
Never remove it "to debug faster", even temporarily, even on a branch.
"""

import hashlib
import hmac

from django.conf import settings


def verify_whatsapp_signature(request):
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        return False
    provided_signature = signature_header.split("=", 1)[1]
    computed_signature = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"), request.body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided_signature, computed_signature)
