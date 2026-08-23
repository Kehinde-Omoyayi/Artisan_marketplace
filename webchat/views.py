"""
webchat/views.py — the HTTP surface the browser chat widget talks to.

Design note: this is a *first-party* transport (the widget lives on our own pages),
so it authenticates with Django's ordinary session cookie + CSRF token — not a
webhook signature like whatsappbot/payments. That signature pattern exists because
Meta/Paystack are third parties calling us over the open internet; nothing here
plays that role, so CSRF protection (already enforced by the project's default
CsrfViewMiddleware — nothing in this file is @csrf_exempt) is the right tool, not a
new one.

Every view that needs a verified identity resolves it from the *session*, never from
a phone number the client sends in the request body — the whole point of the OTP
step in `services.py` is that a phone number typed into a form is not, by itself,
proof of anything.

Reliability note: every call into the shared conversation engine
(`handle_incoming_text` / `_location` / `_image_upload`) is wrapped in
`_run_engine_step`, which turns any unexpected exception into a clean JSON 500 and a
logged, Sentry-visible error — never a raw HTML traceback back to a visitor, and
never a half-applied conversation state (the engine's own state transitions are each
individually saved, and the failure is logged with enough context to reproduce).
"""

import json
import logging
import re

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from whatsappbot.views import (
    handle_incoming_image_upload,
    handle_incoming_location,
    handle_incoming_text,
)

from . import services

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
MAX_MESSAGE_LENGTH = 1000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}
GENERIC_ERROR = "Something went wrong on our end — please try again in a moment."

ERROR_MESSAGES = {
    "expired_or_missing": "That code has expired \u2014 request a new one.",
    "locked": "Too many incorrect attempts \u2014 request a new code.",
    "incorrect": "That code isn't right. Try again.",
}


def _session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _bound_phone(request):
    return services.bound_phone_for_session(_session_key(request))


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _serialize(message):
    return {
        "id": message.id,
        "direction": message.direction,
        "body": message.body,
        "kind": message.kind,
        "created_at": message.created_at.isoformat(),
    }


def _unverified():
    return JsonResponse(
        {"ok": False, "error": "Verify your phone number first."}, status=401
    )


def _run_engine_step(phone, step_name, fn, *args):
    """Runs one call into the shared whatsappbot conversation engine and converts
    any unexpected exception into a clean failure instead of a raw 500 page.

    Returns True on success, or a JsonResponse to return immediately on failure.
    A caller that gets True back should proceed to read `services.messages_since`;
    the underlying business logic (marketplace matching, notifications, etc.) has
    its own error handling further down the stack, so this is a last-resort net —
    not a substitute for handling expected failure cases explicitly upstream.
    """
    try:
        fn(*args)
        return True
    except Exception:  # noqa: BLE001 — this is the last line of defense before an API response
        logger.exception(
            "webchat engine step '%s' failed for phone=%s", step_name, phone
        )
        return JsonResponse({"ok": False, "error": GENERIC_ERROR}, status=500)


@method_decorator(ensure_csrf_cookie, name="get")
class SessionStartView(View):
    """The widget calls this on load. Sets the CSRF cookie and reports whether this
    browser is already bound to a verified phone number."""

    def get(self, request):
        phone = _bound_phone(request)
        return JsonResponse({"verified": phone is not None})


@method_decorator(
    ratelimit(key="ip", rate="5/h", method="POST", block=True), name="post"
)
class RequestCodeView(View):
    def post(self, request):
        phone = (_json_body(request).get("phone") or "").strip()
        if not PHONE_RE.match(phone):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Enter your number in international format, e.g. +2348012345678.",
                },
                status=400,
            )
        normalized = phone.lstrip("+")
        ok, detail = services.request_phone_code(_session_key(request), normalized)
        if not ok:
            return JsonResponse(
                {"ok": False, "error": "Please wait before requesting another code.", **detail},
                status=429,
            )
        return JsonResponse({"ok": True, **detail})


@method_decorator(
    ratelimit(key="ip", rate="15/m", method="POST", block=True), name="post"
)
class ConfirmCodeView(View):
    def post(self, request):
        body = _json_body(request)
        phone = (body.get("phone") or "").strip().lstrip("+")
        code = (body.get("code") or "").strip()
        if not phone or not code:
            return JsonResponse(
                {"ok": False, "error": "Enter the 6-digit code."}, status=400
            )
        ok, result = services.confirm_phone_code(_session_key(request), phone, code)
        if not ok:
            return JsonResponse(
                {"ok": False, "error": ERROR_MESSAGES.get(result, "Verification failed.")},
                status=400,
            )
        return JsonResponse({"ok": True, "phone": phone})


@method_decorator(
    ratelimit(key="ip", rate="30/m", method="POST", block=True), name="post"
)
class SendMessageView(View):
    def post(self, request):
        phone = _bound_phone(request)
        if not phone:
            return _unverified()

        text = (_json_body(request).get("text") or "").strip()
        if not text:
            return JsonResponse({"ok": False, "error": "Message can't be empty."}, status=400)
        if len(text) > MAX_MESSAGE_LENGTH:
            return JsonResponse({"ok": False, "error": "That message is too long."}, status=400)

        last_id = services.latest_message_id(phone)
        services.log_inbound(phone, text)
        result = _run_engine_step(phone, "handle_incoming_text", handle_incoming_text, phone, text)
        if result is not True:
            return result
        return JsonResponse(
            {"ok": True, "messages": [_serialize(m) for m in services.messages_since(phone, last_id)]}
        )


@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=True), name="post"
)
class ShareLocationView(View):
    def post(self, request):
        phone = _bound_phone(request)
        if not phone:
            return _unverified()

        body = _json_body(request)
        try:
            lat = float(body.get("lat"))
            lng = float(body.get("lng"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid location."}, status=400)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return JsonResponse({"ok": False, "error": "Invalid location."}, status=400)

        last_id = services.latest_message_id(phone)
        services.log_inbound(
            phone, f"[shared location {lat:.4f}, {lng:.4f}]", kind="location"
        )
        result = _run_engine_step(
            phone, "handle_incoming_location", handle_incoming_location, phone, lat, lng
        )
        if result is not True:
            return result
        return JsonResponse(
            {"ok": True, "messages": [_serialize(m) for m in services.messages_since(phone, last_id)]}
        )


@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=True), name="post"
)
class UploadIDView(View):
    def post(self, request):
        phone = _bound_phone(request)
        if not phone:
            return _unverified()

        upload = request.FILES.get("file")
        if not upload:
            return JsonResponse({"ok": False, "error": "No file received."}, status=400)
        if upload.content_type not in ALLOWED_UPLOAD_TYPES:
            return JsonResponse(
                {"ok": False, "error": "Upload a JPEG, PNG, or WEBP photo."}, status=400
            )
        if upload.size > MAX_UPLOAD_BYTES:
            return JsonResponse({"ok": False, "error": "That file is too large (8MB max)."}, status=400)

        last_id = services.latest_message_id(phone)
        services.log_inbound(phone, "[uploaded ID photo]", kind="image")
        try:
            ok, error = handle_incoming_image_upload(phone, upload)
        except Exception:  # noqa: BLE001 — e.g. the storage provider is unreachable
            logger.exception("webchat ID upload failed for phone=%s", phone)
            return JsonResponse({"ok": False, "error": GENERIC_ERROR}, status=500)
        if not ok:
            return JsonResponse({"ok": False, "error": error}, status=400)
        return JsonResponse(
            {"ok": True, "messages": [_serialize(m) for m in services.messages_since(phone, last_id)]}
        )


@method_decorator(
    ratelimit(key="ip", rate="120/m", method="GET", block=True), name="get"
)
class PollMessagesView(View):
    def get(self, request):
        phone = _bound_phone(request)
        if not phone:
            return _unverified()

        since = request.GET.get("since")
        since_id = int(since) if since and since.isdigit() else None
        return JsonResponse(
            {"ok": True, "messages": [_serialize(m) for m in services.messages_since(phone, since_id)]}
        )
