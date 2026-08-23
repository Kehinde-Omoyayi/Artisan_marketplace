"""
tests/test_pages.py — the public marketing site. `pages` is only registered at "/"
when ENABLE_DEV_CONSOLE is off (see config/urls.py); this suite skips itself under
the opposite process configuration, exactly mirroring how
tests/test_devconsole_auth.py skips itself when the console is off. Both are
load-time URLconf facts fixed for the life of the process, not something to
re-check per request — see config/urls.py's comment for the full reasoning.

Run once with ENABLE_DEV_CONSOLE unset/False (the default, and what production
actually runs) to exercise this file for real; the devconsole suite covers the
other branch.
"""

from django.conf import settings
from django.core.cache import cache
from django.test import Client, TestCase

from services.models import ServiceCategory


class HomePageTests(TestCase):
    def setUp(self):
        if getattr(settings, "ENABLE_DEV_CONSOLE", False):
            self.skipTest(
                "ENABLE_DEV_CONSOLE is on for this process — '/' serves the dev "
                "console instead (see config/urls.py). Rerun with it off to "
                "exercise the public site."
            )
        cache.clear()  # the home view is cache_page()'d — isolate each test's assertions
        self.client = Client()

    def test_home_page_loads(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "chat-widget")

    def test_home_page_lists_active_categories_only(self):
        ServiceCategory.objects.create(name="Visible Plastering", slug="visible-plastering", active=True)
        ServiceCategory.objects.create(name="Hidden Category", slug="hidden-category", active=False)
        res = self.client.get("/")
        self.assertContains(res, "Visible Plastering")
        self.assertNotContains(res, "Hidden Category")

    def test_home_page_includes_chat_widget_assets(self):
        res = self.client.get("/")
        # Whitenoise's ManifestStaticFilesStorage renames files with a content
        # hash for cache-busting (e.g. chat.2a8ffc568554.js) — check for the
        # stable directory/stem, not an exact filename that's supposed to change.
        self.assertRegex(res.content.decode(), r"/static/webchat/chat\.[0-9a-f]+\.js")
        self.assertRegex(res.content.decode(), r"/static/webchat/chat\.[0-9a-f]+\.css")

    def test_chat_open_buttons_are_present_for_both_customer_and_artisan_intent(self):
        res = self.client.get("/")
        self.assertContains(res, 'data-chat-intent="customer"')
        self.assertContains(res, 'data-chat-intent="artisan"')
