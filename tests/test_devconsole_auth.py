"""
Confirms devconsole has a real second layer of protection now, not just the
ENABLE_DEV_CONSOLE flag checked twice. These tests only run meaningfully when
ENABLE_DEV_CONSOLE=True in the environment the test suite runs under (the flag
gates whether the URLs are registered at all, decided once at process start —
that half of the protection is a straightforward code-inspection fact, not
something worth re-testing dynamically here). What's worth locking in with a
real test is the part that's easy to silently regress: that even while the
console is on, an anonymous or non-staff visitor can't use it.
"""

from django.conf import settings
from django.contrib.auth.models import User as StaffUser
from django.test import TestCase


class DevConsoleAuthTests(TestCase):
    def setUp(self):
        if not getattr(settings, "ENABLE_DEV_CONSOLE", False):
            self.skipTest("ENABLE_DEV_CONSOLE is off in this environment")

    def test_anonymous_cannot_move_money(self):
        response = self.client.post("/dev/money-flow/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_reset_state(self):
        response = self.client.post("/dev/reset/")
        self.assertEqual(response.status_code, 403)

    def test_non_staff_login_cannot_use_it(self):
        user = StaffUser.objects.create_user(
            username="not_staff", password="pw", is_staff=False
        )
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 403)

    def test_staff_login_can_use_it(self):
        user = StaffUser.objects.create_user(
            username="ops", password="pw", is_staff=True
        )
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
