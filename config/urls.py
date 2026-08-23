from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(request):
    """Liveness probe for Railway / uptime monitoring."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("whatsapp/", include("whatsappbot.urls")),
    path("webchat/", include("webchat.urls")),
    path("payments/", include("payments.urls")),
    path("api/", include("core.urls")),
]

# The interactive test console is dev/staging only, and — when it's on — keeps
# owning "/" exactly as it did before (see devconsole/views.py's own docstring:
# two independent layers of protection, URL registration + staff login). When it's
# off, which is the default and what production actually runs, the real public
# site (the marketing page plus the webchat-embedded chat box that now replaces
# the old WhatsApp-only flow) is what visitors land on at "/". Both branches are
# static, load-time facts — see the same reasoning already in
# tests/test_devconsole_auth.py's module docstring — so `pages` picks up its own
# equivalent skip in tests/test_pages.py rather than something re-checked per
# request.
if getattr(settings, "ENABLE_DEV_CONSOLE", False):
    from devconsole.views import home as _dev_home

    urlpatterns += [
        path("", _dev_home, name="dev-home"),
        path("dev/", include("devconsole.urls")),
    ]
else:
    urlpatterns += [path("", include("pages.urls"))]

admin.site.site_header = "Nigeria Artisan Marketplace — Operations"
admin.site.site_title = "Artisan Marketplace Admin"
admin.site.index_title = "V2 Growth Build"
