"""
core/views.py — an operational readiness endpoint for staff.

Staff-only (DRF default permission is IsAdminUser). It answers the question you will
actually ask at 2am: is the database reachable, is Redis reachable, is there an active
FeeConfig, and is the project configured for live money movement?
"""

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FeeConfig


class ReadinessView(APIView):
    def get(self, request):
        checks = {}

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT postgis_version();")
                checks["postgis"] = {"ok": True, "version": cursor.fetchone()[0]}
        except Exception as exc:  # noqa: BLE001
            checks["postgis"] = {"ok": False, "error": str(exc)}

        try:
            cache.set("readiness-probe", "1", 10)
            checks["redis"] = {"ok": cache.get("readiness-probe") == "1"}
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = {"ok": False, "error": str(exc)}

        active_fee = FeeConfig.objects.filter(active=True).first()
        checks["fee_config"] = {
            "ok": active_fee is not None,
            "version": active_fee.version if active_fee else None,
            "payout_approval_threshold_minor": (
                active_fee.payout_approval_threshold_minor if active_fee else None
            ),
        }

        checks["secrets"] = {
            "whatsapp_app_secret_set": bool(settings.WHATSAPP_APP_SECRET),
            "paystack_secret_set": bool(settings.PAYSTACK_SECRET_KEY),
            "storage_configured": bool(settings.STORAGE_ENDPOINT_URL),
            "paystack_environment": settings.PAYSTACK_ENVIRONMENT,
        }
        checks["debug"] = settings.DEBUG

        all_ok = all(
            c.get("ok", True) for c in checks.values() if isinstance(c, dict)
        )
        return Response({"ready": all_ok, "checks": checks})
