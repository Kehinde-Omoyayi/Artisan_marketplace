"""
pages/views.py — the public-facing site. Deliberately thin: this app owns no
models and no business logic, only presentation. Everything a visitor actually
*does* (start a request, register as an artisan, respond to an offer) happens
through the webchat API the page embeds — see webchat/views.py.
"""

from django.conf import settings
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from services.models import ServiceCategory

# The category list is admin-managed and changes rarely, but is read on every
# hit to the highest-traffic page in the project. A short server-side cache turns
# an unbounded read fan-out at scale into one query per cache window instead of one
# per request — safe here specifically because this page has no per-visitor state
# baked into the cached HTML (the chat widget fetches its own CSRF cookie via
# GET /webchat/session/ on load, not from a template tag), so nothing user-specific
# or security-sensitive is at risk of being served to the wrong visitor.
HOME_CACHE_SECONDS = 300


@method_decorator(cache_page(HOME_CACHE_SECONDS), name="get")
class HomeView(TemplateView):
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = list(
            ServiceCategory.objects.filter(active=True).order_by("name")
        )
        ctx["site_name"] = settings.SITE_NAME
        ctx["webchat_poll_interval_ms"] = settings.WEBCHAT_POLL_INTERVAL_MS
        ctx["webchat_otp_resend_seconds"] = settings.WEBCHAT_OTP_RESEND_COOLDOWN_SECONDS
        return ctx
