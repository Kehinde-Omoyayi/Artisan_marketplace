"""
core/views.ReadinessView's docstring claims it's staff-only because of the global
DRF DEFAULT_PERMISSION_CLASSES, but it sets no permission_classes of its own — so
that claim is only true as long as the global default stays IsAdminUser. This test
exists to catch it if that ever silently drifts, since the endpoint reports whether
Paystack is in "live" mode and the live payout approval threshold: not something
that should be reachable by anyone with the URL.
"""

from django.contrib.auth.models import User as StaffUser
from django.test import TestCase

from core.models import FeeConfig


class ReadinessEndpointAuthTests(TestCase):
    def setUp(self):
        FeeConfig.objects.create(
            version=1,
            platform_commission_percent="10.00",
            active=True,
            payout_approval_threshold_minor=5_000_000,
        )

    def test_anonymous_request_is_rejected(self):
        response = self.client.get("/api/readiness/")
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn(b"payout_approval_threshold_minor", response.content)

    def test_non_staff_login_is_rejected(self):
        user = StaffUser.objects.create_user(
            username="artisan_customer", password="not-staff-pw", is_staff=False
        )
        self.client.force_login(user)
        response = self.client.get("/api/readiness/")
        self.assertIn(response.status_code, (401, 403))

    def test_staff_login_can_read_it(self):
        user = StaffUser.objects.create_user(
            username="ops", password="a-real-staff-pw", is_staff=True
        )
        self.client.force_login(user)
        response = self.client.get("/api/readiness/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["checks"]["fee_config"]["ok"])
