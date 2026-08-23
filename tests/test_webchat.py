"""
tests/test_webchat.py — the web channel that replaces WhatsApp as the required
transport. This suite has to prove three separate things:

  1. A browser can't act as a phone number it hasn't proven it owns (OTP flow),
     including under attack (repeated guesses, code reuse, concurrent submission).
  2. Once verified, the *same* conversation engine whatsappbot.views already uses
     runs correctly over plain HTTP instead of a webhook — text, location, ID photo.
  3. Delivery correctly re-routes: a webchat-bound user's replies land in the
     transcript, never in an attempted WhatsApp send, and a stale/abandoned
     session correctly falls back to WhatsApp/email again.
"""

import json
import threading
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from marketplace.models import ArtisanLocation
from notifications.models import NotificationLog
from services.models import ServiceCategory
from verification.models import VerificationDocument
from webchat.models import PhoneVerificationCode, WebChatMessage, WebChatSession

TEST_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def _post(client, url_name, payload):
    return client.post(reverse(f"webchat:{url_name}"), data=json.dumps(payload), content_type="application/json")


@override_settings(RATELIMIT_ENABLE=False, USE_LOCMEM_CACHE=True, CACHES=TEST_CACHE, DEBUG=True)
# DEBUG=True is deliberate here, not a leftover: Django's test runner forces DEBUG
# to False by default regardless of settings.py, and these tests need the
# "debug_code" convenience (webchat/services.py) to read back a code nothing else
# ever exposes — restoring the DEBUG posture is how we simulate the dev-console
# philosophy this was modelled on, not a way to dodge it.
class PhoneVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_rejects_malformed_phone(self):
        res = _post(self.client, "request-code", {"phone": "not-a-phone"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(PhoneVerificationCode.objects.count(), 0)

    def test_issues_a_hashed_code_never_stored_in_plaintext(self):
        res = _post(self.client, "request-code", {"phone": "+2348012345678"})
        self.assertEqual(res.status_code, 200)
        record = PhoneVerificationCode.objects.get()
        self.assertEqual(record.phone_e164, "2348012345678")
        self.assertEqual(len(record.code_hash), 64)  # sha256 hex digest length
        # The model simply has no plaintext-code field to leak in the first place.
        self.assertNotIn("code", [f.name for f in record._meta.get_fields()])

    def test_resend_before_cooldown_is_rejected_with_retry_after(self):
        _post(self.client, "request-code", {"phone": "+2348012345678"})
        res = _post(self.client, "request-code", {"phone": "+2348012345678"})
        self.assertEqual(res.status_code, 429)
        self.assertIn("retry_after_seconds", res.json())
        self.assertEqual(PhoneVerificationCode.objects.count(), 1)

    def test_correct_code_binds_session_to_a_new_user(self):
        issued = _post(self.client, "request-code", {"phone": "+2348012345678"})
        code = issued.json()["debug_code"]
        res = _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": code})
        self.assertEqual(res.status_code, 200)
        user = User.objects.get(phone_e164="2348012345678")
        self.assertEqual(user.role, "customer")
        self.assertEqual(WebChatSession.objects.get().user, user)

    def test_correct_code_reuses_existing_user_if_phone_already_registered(self):
        existing = User.objects.create(phone_e164="2348012345678", role="artisan")
        issued = _post(self.client, "request-code", {"phone": "+2348012345678"})
        code = issued.json()["debug_code"]
        _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": code})
        self.assertEqual(User.objects.filter(phone_e164="2348012345678").count(), 1)
        self.assertEqual(WebChatSession.objects.get().user_id, existing.id)

    def test_wrong_code_is_rejected_and_recorded_as_an_attempt(self):
        _post(self.client, "request-code", {"phone": "+2348012345678"})
        res = _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": "000000"})
        self.assertEqual(res.status_code, 400)
        record = PhoneVerificationCode.objects.get()
        self.assertEqual(record.attempts, 1)
        self.assertFalse(User.objects.filter(phone_e164="2348012345678").exists())

    def test_code_locks_after_max_attempts_even_for_the_correct_code(self):
        issued = _post(self.client, "request-code", {"phone": "+2348012345678"})
        correct_code = issued.json()["debug_code"]
        for _ in range(PhoneVerificationCode.MAX_ATTEMPTS):
            _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": "000000"})

        final = _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": correct_code})
        self.assertEqual(final.status_code, 400)
        self.assertIn("Too many", final.json()["error"])
        self.assertFalse(User.objects.filter(phone_e164="2348012345678").exists())

    def test_code_is_single_use(self):
        issued = _post(self.client, "request-code", {"phone": "+2348012345678"})
        code = issued.json()["debug_code"]
        first = _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": code})
        self.assertEqual(first.status_code, 200)

        second = _post(self.client, "confirm-code", {"phone": "+2348012345678", "code": code})
        self.assertEqual(second.status_code, 400)
        self.assertEqual(User.objects.filter(phone_e164="2348012345678").count(), 1)

    def test_expired_code_is_rejected(self):
        record, code = PhoneVerificationCode.issue("sess-expired", "2348012345678", ttl_seconds=300)
        PhoneVerificationCode.objects.filter(pk=record.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        # confirm-code resolves session_key from the caller's own session cookie,
        # not an arbitrary value, so drive this one through the service directly.
        from webchat import services

        ok, reason = services.confirm_phone_code("sess-expired", "2348012345678", code)
        self.assertFalse(ok)
        self.assertEqual(reason, "expired_or_missing")


@override_settings(RATELIMIT_ENABLE=False, USE_LOCMEM_CACHE=True, CACHES=TEST_CACHE, DEBUG=True)
@patch("notifications.services._send_whatsapp")
class VerifiedChatFlowTests(TestCase):
    """Everything past the OTP gate — proves the shared whatsappbot engine works
    identically whether it's driven by a webhook or by this HTTP surface."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        ServiceCategory.objects.create(name="Plumbing", slug="plumbing")
        issued = _post(self.client, "request-code", {"phone": "+2348099999999"})
        code = issued.json()["debug_code"]
        _post(self.client, "confirm-code", {"phone": "+2348099999999", "code": code})
        self.phone = "2348099999999"

    def _register_as_artisan_up_to_id_photo(self):
        _post(self.client, "message", {"text": "ARTISAN"})
        _post(self.client, "message", {"text": "Plumbing"})
        _post(self.client, "location", {"lat": 6.5244, "lng": 3.3792})

    def test_unverified_session_cannot_send(self, mock_send):
        res = _post(Client(), "message", {"text": "hi"})
        self.assertEqual(res.status_code, 401)

    def test_send_message_reaches_the_shared_bot_engine(self, mock_send):
        res = _post(self.client, "message", {"text": "ARTISAN"})
        self.assertEqual(res.status_code, 200)
        user = User.objects.get(phone_e164=self.phone)
        self.assertEqual(user.role, "artisan")
        mock_send.assert_not_called()  # a webchat user never triggers a WhatsApp attempt

    def test_reply_is_recorded_in_the_transcript_and_returned(self, mock_send):
        res = _post(self.client, "message", {"text": "ARTISAN"})
        messages = res.json()["messages"]
        self.assertTrue(any(m["direction"] == "in" and m["body"] == "ARTISAN" for m in messages))
        self.assertTrue(any(m["direction"] == "out" for m in messages))
        self.assertTrue(WebChatMessage.objects.filter(phone_e164=self.phone, direction="out").exists())
        self.assertTrue(NotificationLog.objects.filter(channel="webchat").exists())

    def test_empty_message_is_rejected(self, mock_send):
        res = _post(self.client, "message", {"text": "   "})
        self.assertEqual(res.status_code, 400)

    def test_overlong_message_is_rejected(self, mock_send):
        res = _post(self.client, "message", {"text": "x" * 1001})
        self.assertEqual(res.status_code, 400)

    def test_poll_only_returns_messages_after_since_id(self, mock_send):
        _post(self.client, "message", {"text": "ARTISAN"})
        first_id = WebChatMessage.objects.filter(phone_e164=self.phone).order_by("id").first().id
        poll = self.client.get(reverse("webchat:messages"), {"since": first_id})
        ids = [m["id"] for m in poll.json()["messages"]]
        self.assertNotIn(first_id, ids)

    def test_poll_with_since_zero_returns_full_history(self, mock_send):
        _post(self.client, "message", {"text": "ARTISAN"})
        poll = self.client.get(reverse("webchat:messages"), {"since": "0"})
        self.assertGreaterEqual(len(poll.json()["messages"]), 2)  # the "in" + at least one "out"

    def test_share_location_reaches_the_bot_engine(self, mock_send):
        _post(self.client, "message", {"text": "ARTISAN"})
        _post(self.client, "message", {"text": "Plumbing"})
        res = _post(self.client, "location", {"lat": 6.5244, "lng": 3.3792})
        self.assertEqual(res.status_code, 200)
        user = User.objects.get(phone_e164=self.phone)
        self.assertTrue(ArtisanLocation.objects.filter(artisan=user).exists())

    def test_invalid_location_is_rejected(self, mock_send):
        res = _post(self.client, "location", {"lat": 999, "lng": 3.3792})
        self.assertEqual(res.status_code, 400)

    def test_upload_id_photo_creates_verification_document(self, mock_send):
        self._register_as_artisan_up_to_id_photo()
        upload = SimpleUploadedFile("id.jpg", b"fake-image-bytes", content_type="image/jpeg")
        with patch("core.storage.upload_file_to_storage", return_value="verification/9/xyz.jpg") as mock_upload:
            res = self.client.post(reverse("webchat:upload-id"), {"file": upload})
        self.assertEqual(res.status_code, 200)
        mock_upload.assert_called_once()
        doc = VerificationDocument.objects.get()
        self.assertEqual(doc.storage_key, "verification/9/xyz.jpg")
        self.assertEqual(doc.level, "L2")
        self.assertFalse(doc.storage_key.startswith("http"))

    def test_upload_rejects_disallowed_content_type(self, mock_send):
        bad = SimpleUploadedFile("id.txt", b"not an image", content_type="text/plain")
        res = self.client.post(reverse("webchat:upload-id"), {"file": bad})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(VerificationDocument.objects.count(), 0)

    def test_upload_outside_expected_state_is_rejected_cleanly(self, mock_send):
        # Never went through ARTISAN -> category -> location, so the state machine
        # isn't expecting a photo — this should be a clean 400, not a silent no-op
        # or a 500.
        upload = SimpleUploadedFile("id.jpg", b"bytes", content_type="image/jpeg")
        res = self.client.post(reverse("webchat:upload-id"), {"file": upload})
        self.assertEqual(res.status_code, 400)

    def test_storage_failure_during_upload_returns_clean_500(self, mock_send):
        self._register_as_artisan_up_to_id_photo()
        upload = SimpleUploadedFile("id.jpg", b"fake-image-bytes", content_type="image/jpeg")
        with patch("core.storage.upload_file_to_storage", side_effect=ConnectionError("storage unreachable")):
            res = self.client.post(reverse("webchat:upload-id"), {"file": upload})
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("Traceback", res.content.decode())
        self.assertEqual(VerificationDocument.objects.count(), 0)

    def test_unexpected_engine_exception_returns_clean_500_but_preserves_the_inbound_message(self, mock_send):
        with patch("webchat.views.handle_incoming_text", side_effect=RuntimeError("boom")):
            res = _post(self.client, "message", {"text": "hello"})
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("Traceback", res.content.decode())
        # The visitor's own message was logged before the engine call — a crash
        # downstream must not also lose what they typed.
        self.assertTrue(
            WebChatMessage.objects.filter(phone_e164=self.phone, direction="in", body="hello").exists()
        )


@override_settings(RATELIMIT_ENABLE=False, USE_LOCMEM_CACHE=True, CACHES=TEST_CACHE)
class NotificationRoutingTests(TestCase):
    """Unit-level proof of the routing decision in notifications.services, isolated
    from the HTTP layer above."""

    def setUp(self):
        cache.clear()

    @patch("notifications.services._send_whatsapp")
    def test_webchat_user_notifications_never_attempt_whatsapp(self, mock_send):
        from notifications.services import send_notification

        user = User.objects.create(phone_e164="2348055555555", role="customer")
        WebChatSession.objects.create(session_key="sess-a", user=user)

        send_notification(user, "test_template", "hello there")

        mock_send.assert_not_called()
        self.assertTrue(WebChatMessage.objects.filter(phone_e164=user.phone_e164, direction="out").exists())
        self.assertTrue(NotificationLog.objects.filter(user=user, channel="webchat").exists())

    @patch("notifications.services._send_whatsapp")
    def test_non_webchat_user_still_tries_whatsapp(self, mock_send):
        from notifications.services import send_notification

        mock_send.return_value = True
        user = User.objects.create(phone_e164="2348066666666", role="customer")

        send_notification(user, "test_template", "hello there")

        mock_send.assert_called_once()
        self.assertFalse(NotificationLog.objects.filter(user=user, channel="webchat").exists())

    @patch("notifications.services._send_whatsapp")
    def test_stale_webchat_session_falls_back_to_whatsapp(self, mock_send):
        from notifications.services import send_notification

        mock_send.return_value = True
        user = User.objects.create(phone_e164="2348077777777", role="customer")
        session = WebChatSession.objects.create(session_key="sess-stale", user=user)
        WebChatSession.objects.filter(pk=session.pk).update(
            last_seen_at=timezone.now() - timedelta(hours=48)
        )

        send_notification(user, "test_template", "hello there")

        mock_send.assert_called_once()

    def test_no_user_never_raises(self):
        from webchat.services import is_webchat_user

        self.assertFalse(is_webchat_user(None))


class OTPConcurrencyTests(TransactionTestCase):
    """Real, threaded concurrency (not just sequential calls) proving the
    select_for_update() row lock in webchat.services.confirm_phone_code actually
    serializes two requests racing to consume the same code — a double-tapped
    Verify button, or two tabs open to the same number, must not both succeed."""

    def setUp(self):
        cache.clear()

    def test_two_simultaneous_confirms_only_one_succeeds(self):
        from django.db import connections

        from webchat import services

        session_key = "race-session"
        phone = "2348088888888"
        _record, code = PhoneVerificationCode.issue(session_key, phone, ttl_seconds=300)

        results = []
        barrier = threading.Barrier(2)

        def attempt():
            try:
                barrier.wait()
                ok, _result = services.confirm_phone_code(session_key, phone, code)
                results.append(ok)
            finally:
                # Each thread opens its own DB connection; Django never closes
                # background-thread connections automatically, and a leaked one
                # blocks the test database from being torn down at the end of the
                # run. Explicit cleanup here, not a workaround for a flaky test.
                connections.close_all()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(User.objects.filter(phone_e164=phone).count(), 1)
