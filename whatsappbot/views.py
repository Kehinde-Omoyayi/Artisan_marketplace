"""
whatsappbot/views.py — Part 14 (full replacement of the V1 file) + Part 18.3.

What changed from V1 and why:
  * `send_whatsapp_text` is gone. Every outbound message now goes through
    `notifications.services.send_notification`, which logs to NotificationLog and falls
    back to email. The bot no longer talks to Meta's API directly.
  * `get_or_create_user` runs at the very top of `handle_incoming_text`, not at the end:
    V2 needs a User row before the artisan branch starts, and so NotificationLog has
    something to attach to on the very first message.
  * The POST handler verifies X-Hub-Signature-256 before reading a single field.
"""

import hmac
import json
import logging

from django.conf import settings
from django.contrib.gis.geos import Point
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from django.db.models import F

from accounts.models import ArtisanProfile, CustomerProfile, User
from job_requests.models import ServiceRequest
from marketplace.models import ArtisanLocation, Match
from notifications.services import send_notification
from services.models import ArtisanService, ServiceCategory
from verification.models import VerificationDocument

from .models import ConversationState, WhatsAppMessage
from .security import verify_whatsapp_signature

logger = logging.getLogger(__name__)

ACCEPT_WORDS = {"YES", "Y", "ACCEPT"}
DECLINE_WORDS = {"NO", "N", "DECLINE"}
OFFERS_WORDS = {"OFFERS", "LIST"}
USE_SAVED_WORDS = {"YES", "Y"}
NEW_ADDRESS_WORDS = {"NEW", "NO", "N"}


def _get_customer_profile(user):
    try:
        return user.customer_profile
    except CustomerProfile.DoesNotExist:
        return None


def _parse_offer_reply(text):
    """Returns ("accept"|"decline", code_or_None) or None if text isn't a reply
    to a job offer at all."""
    parts = text.strip().upper().split()
    if not parts:
        return None
    word, code = parts[0], (parts[1] if len(parts) > 1 else None)
    if word in ACCEPT_WORDS:
        return ("accept", code)
    if word in DECLINE_WORDS:
        return ("decline", code)
    return None


def _send_open_offers(user):
    pending = Match.objects.filter(
        artisan=user, response_status="pending"
    ).select_related("request__category")
    if not pending.exists():
        send_notification(
            user, "no_pending_offers", "You don't have any pending job offers right now."
        )
        return
    lines = [
        f"{m.offer_code}: {m.request.category.name} in {m.request.area_name}"
        for m in pending
    ]
    send_notification(
        user, "open_offers_list", "Your open offers:\n" + "\n".join(lines)
    )


def try_handle_offer_reply(user, text):
    """
    If `text` looks like a reply to a job offer (YES/NO, optionally with a code)
    from an already-onboarded, currently-idle artisan, process it and return True.
    Returns False so the caller falls through to normal conversation handling for
    everything else (new customers, artisan onboarding, small talk, etc.).
    """
    if user.role != "artisan":
        return False

    stripped = text.strip().upper()
    if stripped in OFFERS_WORDS:
        _send_open_offers(user)
        return True

    parsed = _parse_offer_reply(text)
    if not parsed:
        return False
    action, code = parsed

    pending = Match.objects.filter(artisan=user, response_status="pending")
    if code:
        pending = pending.filter(offer_code__iexact=code)

    count = pending.count()
    if count == 0:
        if code:
            send_notification(
                user,
                "offer_not_found",
                f"I couldn't find an open offer with code {code}. Type OFFERS to "
                f"see your open offers.",
            )
        else:
            send_notification(
                user, "no_pending_offers", "You don't have any pending job offers right now."
            )
        return True

    if count > 1:
        send_notification(
            user,
            "multiple_pending_offers",
            "You have more than one open offer — reply with the code, e.g. "
            "'YES A1B2C3'. Type OFFERS to see them.",
        )
        return True

    match = pending.first()
    from marketplace.services import accept_offer, decline_offer

    if action == "accept":
        booking = accept_offer(match)
        if booking is None:
            send_notification(
                user,
                "offer_too_late",
                "Sorry — that job was just taken by another artisan.",
            )
        else:
            send_notification(
                user,
                "offer_accepted",
                f"You're confirmed for {match.request.category.name} in "
                f"{match.request.area_name}. Booking ref {booking.booking_ref}. "
                f"The customer has been notified.",
            )
    else:
        decline_offer(match)
        send_notification(
            user,
            "offer_declined",
            "No problem — you've declined this job. We'll offer it to the next "
            "artisan in the area.",
        )
    return True


def get_or_create_user(phone_e164):
    user, _ = User.objects.get_or_create(
        phone_e164=phone_e164, defaults={"role": "customer"}
    )
    return user


def get_state(phone_e164):
    state, _ = ConversationState.objects.get_or_create(phone_e164=phone_e164)
    return state


def handle_incoming_text(phone_e164, text):
    text = text.strip()
    state = get_state(phone_e164)
    user = get_or_create_user(phone_e164)

    # An idle, already-onboarded artisan can reply to a job offer at any time —
    # check this before anything else, or "YES" gets swallowed by the customer
    # "start a new request" branch below.
    if state.state == "start" and try_handle_offer_reply(user, text):
        return

    if state.state == "start" and text.upper() == "ARTISAN":
        user.role = "artisan"
        user.save()
        ArtisanProfile.objects.get_or_create(user=user)
        categories = ServiceCategory.objects.filter(active=True)
        names = ", ".join(c.name for c in categories)
        send_notification(
            user,
            "artisan_onboarding_category",
            f"Welcome! Which service do you offer? Reply with one of: {names}",
        )
        state.state = "artisan_awaiting_category"
        state.save()
        return

    if state.state == "artisan_awaiting_category":
        category = ServiceCategory.objects.filter(active=True, name__iexact=text).first()
        if not category:
            send_notification(
                user,
                "artisan_onboarding_retry",
                "I don't recognize that service. Please type the exact name again.",
            )
            return
        state.data["artisan_category_id"] = str(category.id)
        state.state = "artisan_awaiting_location"
        state.save()
        send_notification(
            user,
            "artisan_onboarding_location",
            "Please share your location: tap the paperclip/attachment icon, choose "
            "Location, then Send Your Current Location.",
        )
        return

    if state.state == "start":
        categories = ServiceCategory.objects.filter(active=True)
        names = ", ".join(c.name for c in categories)
        send_notification(
            user, "customer_start", f"What do you need? Reply with one of: {names}"
        )
        state.state = "awaiting_category"
        state.save()
        return

    if state.state == "awaiting_category":
        category = ServiceCategory.objects.filter(active=True, name__iexact=text).first()
        if not category:
            send_notification(
                user,
                "customer_retry_category",
                "I don't recognize that service. Please type the exact name again.",
            )
            return
        state.data["category_id"] = str(category.id)

        # Part 24 — returning customer with a saved address: offer to reuse it
        # instead of re-asking for area + GPS pin every single time.
        profile = _get_customer_profile(user)
        if profile and profile.default_area and profile.saved_location:
            state.state = "awaiting_saved_address_choice"
            state.save()
            send_notification(
                user,
                "customer_saved_address_prompt",
                f"Use your saved address ({profile.default_area})? Reply YES to "
                f"use it, or NEW to share a different location this time.",
            )
            return

        state.state = "awaiting_area"
        state.save()
        send_notification(user, "customer_ask_area", "What area are you in?")
        return

    if state.state == "awaiting_saved_address_choice":
        profile = _get_customer_profile(user)
        choice = text.strip().upper()
        if profile and choice in USE_SAVED_WORDS:
            state.data["area_name"] = profile.default_area
            state.data["location"] = {
                "lat": profile.saved_location.y,
                "lng": profile.saved_location.x,
            }
            state.state = "awaiting_timing"
            state.save()
            send_notification(
                user,
                "customer_ask_timing",
                "When do you need this? Reply Today, This week, or Flexible.",
            )
            return
        if choice in NEW_ADDRESS_WORDS:
            state.state = "awaiting_area"
            state.save()
            send_notification(user, "customer_ask_area", "What area are you in?")
            return
        send_notification(
            user,
            "customer_saved_address_retry",
            "Please reply YES to use your saved address, or NEW to enter a "
            "different one.",
        )
        return

    if state.state == "awaiting_area":
        state.data["area_name"] = text
        state.state = "awaiting_location"
        state.save()
        send_notification(
            user,
            "customer_ask_location",
            "Please also share your location pin so we can find artisans near you: tap "
            "the paperclip icon, choose Location, then Send Your Current Location.",
        )
        return

    if state.state == "awaiting_timing":
        category = ServiceCategory.objects.get(id=state.data["category_id"])
        loc = state.data.get("location")
        point = Point(loc["lng"], loc["lat"], srid=4326) if loc else None
        area_name = state.data.get("area_name", "")
        new_request = ServiceRequest.objects.create(
            customer=user,
            category=category,
            area_name=area_name,
            location=point,
            timing=text,
        )

        # Part 24 — remember this address so the next request can skip straight
        # to "use your saved address?" instead of asking from scratch.
        if point:
            CustomerProfile.objects.update_or_create(
                user=user,
                defaults={"default_area": area_name, "saved_location": point},
            )
            CustomerProfile.objects.filter(user=user).update(
                total_requests=F("total_requests") + 1
            )

        from marketplace.tasks import run_matching_for_request

        run_matching_for_request.delay(str(new_request.id))
        send_notification(
            user,
            "request_confirmed",
            f"Got it. Looking for a {category.name} artisan near you. "
            f"We'll notify you shortly.",
        )
        state.state = "start"
        state.data = {}
        state.save()
        return

    send_notification(
        user,
        "fallback_restart",
        "Type anything to start a new request, or type ARTISAN to register as a "
        "service provider.",
    )
    state.state = "start"
    state.save()


def handle_incoming_location(phone_e164, latitude, longitude):
    state = get_state(phone_e164)
    user = get_or_create_user(phone_e164)
    # Point takes (x=lng, y=lat), NOT (lat, lng).
    point = Point(longitude, latitude, srid=4326)

    if state.state == "awaiting_location":
        state.data["location"] = {"lat": latitude, "lng": longitude}
        state.state = "awaiting_timing"
        state.save()
        send_notification(
            user,
            "customer_ask_timing",
            "When do you need this? Reply Today, This week, or Flexible.",
        )
        return

    if state.state == "artisan_awaiting_location":
        category = ServiceCategory.objects.get(id=state.data["artisan_category_id"])
        ArtisanService.objects.get_or_create(artisan=user, service=category)
        ArtisanLocation.objects.update_or_create(
            artisan=user, defaults={"point": point}
        )
        send_notification(
            user,
            "artisan_onboarding_id",
            f"You're registered as a {category.name} artisan. Now send a clear photo "
            f"of your government-issued ID to begin verification.",
        )
        state.state = "artisan_awaiting_id_photo"
        state.save()
        return

    send_notification(
        user,
        "unexpected_location",
        "I wasn't expecting a location right now. Type anything to start over.",
    )
    state.state = "start"
    state.save()


def _finish_id_capture(user, state, storage_key):
    """The part of ID capture that's identical no matter which transport delivered
    the photo: record the VerificationDocument, notify, reset conversation state."""
    VerificationDocument.objects.create(
        artisan=user, level="L2", storage_key=storage_key
    )
    send_notification(
        user,
        "id_received",
        "Got your ID. A staff member will review it shortly — you'll be notified once "
        "you're approved to receive job requests.",
    )
    state.state = "start"
    state.save()


def handle_incoming_image(phone_e164, media_id):
    """WhatsApp transport: `media_id` is Meta's reference, not the file itself —
    fetch it from their API into our own storage, then hand off to the shared
    completion step."""
    state = get_state(phone_e164)
    user = get_or_create_user(phone_e164)
    if state.state != "artisan_awaiting_id_photo":
        return

    from core.storage import download_whatsapp_media_to_storage

    storage_key = download_whatsapp_media_to_storage(
        media_id, folder=f"verification/{user.id}"
    )
    _finish_id_capture(user, state, storage_key)


def handle_incoming_image_upload(phone_e164, uploaded_file):
    """Web transport: the browser already handed us the file bytes directly, so
    there's no Meta media_id round-trip. Returns (ok, error_message_or_None) instead
    of the fire-and-forget style `handle_incoming_image` uses, since an HTTP caller
    needs to tell the visitor something went wrong."""
    state = get_state(phone_e164)
    user = get_or_create_user(phone_e164)
    if state.state != "artisan_awaiting_id_photo":
        return False, "We're not expecting an ID photo right now."

    from core.storage import upload_file_to_storage

    storage_key = upload_file_to_storage(uploaded_file, folder=f"verification/{user.id}")
    _finish_id_capture(user, state, storage_key)
    return True, None


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(
    ratelimit(key="ip", rate="60/m", method="POST", block=True), name="post"
)
class WhatsAppWebhookView(View):
    def get(self, request):
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token") or ""
        challenge = request.GET.get("hub.challenge")
        token_matches = hmac.compare_digest(token, settings.WHATSAPP_VERIFY_TOKEN)
        if mode == "subscribe" and token_matches:
            return HttpResponse(challenge)
        return HttpResponse("Verification failed", status=403)

    def post(self, request):
        # Non-negotiable rule #2 — check this BEFORE reading a single field out of the body.
        if not verify_whatsapp_signature(request):
            return JsonResponse({"status": "invalid signature"}, status=401)

        body = json.loads(request.body.decode("utf-8"))
        try:
            entry = body["entry"][0]
            change = entry["changes"][0]["value"]
            messages = change.get("messages")
            if not messages:
                return JsonResponse({"status": "ignored"})

            message = messages[0]
            phone_e164 = message["from"]
            message_type = message.get("type")

            WhatsAppMessage.objects.create(
                phone_e164=phone_e164, direction="in", payload=message
            )

            if message_type == "text":
                handle_incoming_text(phone_e164, message["text"]["body"])
            elif message_type == "location":
                loc = message["location"]
                handle_incoming_location(phone_e164, loc["latitude"], loc["longitude"])
            elif message_type == "image":
                handle_incoming_image(phone_e164, message["image"]["id"])
            # any other message type (audio, video, sticker, etc.) is silently ignored —
            # deliberate, not every message type needs a response.

            WhatsAppMessage.objects.create(
                phone_e164=phone_e164, direction="out", payload={"reply_sent": True}
            )
        except (KeyError, IndexError):
            pass

        return JsonResponse({"status": "ok"})
