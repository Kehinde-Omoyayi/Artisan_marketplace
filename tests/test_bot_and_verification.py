"""
Parts 6, 11, 12 and 14 — the WhatsApp conversation machine, notifications and
the verification level ladder.
"""

from unittest.mock import patch

from django.contrib.auth.models import Group, User as StaffUser
from django.core.management import call_command
from django.test import TestCase

from accounts.models import ArtisanProfile, User
from job_requests.models import ServiceRequest
from marketplace.models import ArtisanLocation
from notifications.models import NotificationLog
from services.models import ArtisanService, ServiceCategory
from verification.models import VerificationDocument
from whatsappbot.models import ConversationState
from whatsappbot.views import (
    handle_incoming_image,
    handle_incoming_location,
    handle_incoming_text,
)

PHONE = "2348044444444"


@patch("notifications.services._send_whatsapp", return_value=None)
class CustomerFlowTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Plumbing", slug="plumbing")

    def test_full_customer_journey_creates_a_located_request(self, mock_send):
        with patch("marketplace.tasks.run_matching_for_request.delay") as mock_task:
            handle_incoming_text(PHONE, "hi")
            self.assertEqual(ConversationState.objects.get(phone_e164=PHONE).state, "awaiting_category")

            handle_incoming_text(PHONE, "Plumbing")
            self.assertEqual(ConversationState.objects.get(phone_e164=PHONE).state, "awaiting_area")

            handle_incoming_text(PHONE, "Yaba")
            self.assertEqual(ConversationState.objects.get(phone_e164=PHONE).state, "awaiting_location")

            handle_incoming_location(PHONE, 6.5244, 3.3792)
            self.assertEqual(ConversationState.objects.get(phone_e164=PHONE).state, "awaiting_timing")

            handle_incoming_text(PHONE, "Today")

        request = ServiceRequest.objects.get()
        self.assertEqual(request.area_name, "Yaba")
        self.assertEqual(request.timing, "Today")
        self.assertIsNotNone(request.location)
        # Point is (x=lng, y=lat) — this is the ordering bug the manual warns about.
        self.assertAlmostEqual(request.location.x, 3.3792, places=4)
        self.assertAlmostEqual(request.location.y, 6.5244, places=4)

        mock_task.assert_called_once_with(str(request.id))
        self.assertEqual(ConversationState.objects.get(phone_e164=PHONE).state, "start")

    def test_unknown_category_does_not_advance_state(self, mock_send):
        handle_incoming_text(PHONE, "hi")
        handle_incoming_text(PHONE, "Rocket Science")
        self.assertEqual(
            ConversationState.objects.get(phone_e164=PHONE).state, "awaiting_category"
        )

    def test_user_row_exists_from_the_very_first_message(self, mock_send):
        handle_incoming_text(PHONE, "hi")
        self.assertTrue(User.objects.filter(phone_e164=PHONE).exists())


@patch("notifications.services._send_whatsapp", return_value=None)
class ArtisanOnboardingTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Electrical", slug="electrical")

    def test_artisan_registers_with_location_and_id(self, mock_send):
        handle_incoming_text(PHONE, "ARTISAN")
        user = User.objects.get(phone_e164=PHONE)
        self.assertEqual(user.role, "artisan")
        self.assertTrue(ArtisanProfile.objects.filter(user=user).exists())
        self.assertEqual(user.artisan_profile.verification_level, "L0")

        handle_incoming_text(PHONE, "Electrical")
        handle_incoming_location(PHONE, 6.5244, 3.3792)

        self.assertTrue(ArtisanService.objects.filter(artisan=user).exists())
        self.assertTrue(ArtisanLocation.objects.filter(artisan=user).exists())
        self.assertEqual(
            ConversationState.objects.get(phone_e164=PHONE).state,
            "artisan_awaiting_id_photo",
        )

        with patch(
            "core.storage.download_whatsapp_media_to_storage",
            return_value="verification/1/abc.jpg",
        ):
            handle_incoming_image(PHONE, "MEDIA_ID_1")

        doc = VerificationDocument.objects.get()
        self.assertEqual(doc.level, "L2")
        self.assertEqual(doc.status, "pending")
        self.assertEqual(doc.storage_key, "verification/1/abc.jpg")
        # storage_key is a bucket path, never a public URL.
        self.assertFalse(doc.storage_key.startswith("http"))

    def test_image_outside_the_id_state_is_ignored(self, mock_send):
        handle_incoming_text(PHONE, "hi")
        with patch("core.storage.download_whatsapp_media_to_storage") as mock_dl:
            handle_incoming_image(PHONE, "MEDIA_ID_2")
        mock_dl.assert_not_called()
        self.assertEqual(VerificationDocument.objects.count(), 0)


class VerificationLadderTests(TestCase):
    def setUp(self):
        self.artisan = User.objects.create(phone_e164="2348055555555", role="artisan")
        self.profile = ArtisanProfile.objects.create(user=self.artisan)
        self.staff = StaffUser.objects.create_user(
            "reviewer", "r@example.com", "pw", is_staff=True
        )

    def _approve(self, doc):
        from verification.admin import approve_documents

        class FakeRequest:
            user = self.staff

        approve_documents(None, FakeRequest(), VerificationDocument.objects.filter(pk=doc.pk))

    def test_approving_l2_raises_level_and_audits(self):
        from core.models import AuditLog

        doc = VerificationDocument.objects.create(
            artisan=self.artisan, level="L2", storage_key="k"
        )
        self._approve(doc)

        doc.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(doc.status, "approved")
        self.assertEqual(doc.reviewed_by, self.staff)
        self.assertIsNotNone(doc.reviewed_at)
        self.assertEqual(self.profile.verification_level, "L2")
        self.assertTrue(
            AuditLog.objects.filter(action="verification_approved").exists()
        )

    def test_level_never_goes_backwards(self):
        self.profile.verification_level = "L4"
        self.profile.save()

        doc = VerificationDocument.objects.create(
            artisan=self.artisan, level="L2", storage_key="k"
        )
        self._approve(doc)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_level, "L4")


class NotificationFallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            phone_e164="2348066666666", email="artisan@example.com"
        )

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_whatsapp_success_is_logged(self, mock_send):
        from notifications.services import send_notification

        self.assertTrue(send_notification(self.user, "tpl", "hello"))
        log = NotificationLog.objects.get()
        self.assertEqual(log.channel, "whatsapp")
        self.assertEqual(log.status, "sent")

    @patch("notifications.services.send_mail", return_value=1)
    @patch("notifications.services._send_whatsapp", side_effect=RuntimeError("Meta down"))
    def test_whatsapp_failure_falls_back_to_email(self, mock_wa, mock_mail):
        from notifications.services import send_notification

        self.assertTrue(send_notification(self.user, "tpl", "hello"))
        self.assertEqual(NotificationLog.objects.count(), 2)
        self.assertTrue(
            NotificationLog.objects.filter(channel="whatsapp", status="failed").exists()
        )
        self.assertTrue(
            NotificationLog.objects.filter(channel="email", status="sent").exists()
        )

    @patch("notifications.services._send_whatsapp", side_effect=RuntimeError("Meta down"))
    def test_no_email_on_file_returns_false(self, mock_wa):
        from notifications.services import send_notification

        user = User.objects.create(phone_e164="2348077777777")
        self.assertFalse(send_notification(user, "tpl", "hello"))


class RBACTests(TestCase):
    def test_staff_roles_are_least_privilege(self):
        call_command("setup_staff_roles")

        finance = Group.objects.get(name="finance_staff")
        verification = Group.objects.get(name="verification_staff")
        support = Group.objects.get(name="support_staff")

        def app_labels(group):
            return set(
                group.permissions.values_list("content_type__app_label", flat=True)
            )

        # A finance person must never be able to approve an identity document.
        self.assertNotIn("verification", app_labels(finance))
        # A verification reviewer must never be able to approve a payout.
        self.assertNotIn("payments", app_labels(verification))
        # Support handles disputes and cases, not money.
        self.assertNotIn("payments", app_labels(support))
        self.assertIn("disputes", app_labels(support))

        # Nobody in a staff group can delete financial records.
        for group in (finance, verification, support):
            codenames = set(group.permissions.values_list("codename", flat=True))
            self.assertFalse(
                {c for c in codenames if c.startswith("delete_")},
                f"{group.name} has delete permissions",
            )
