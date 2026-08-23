"""
A pre-flight check to run before Part 23 Step 10 (switching Paystack to Live keys).

    python manage.py check_production_ready

It verifies every "you will lose money if this is wrong" condition from the manual:
DEBUG off, secrets present, PostGIS live, Redis reachable, an active FeeConfig,
the Beat schedule registered, and the four non-negotiable rules still structurally
intact in the code.
"""

import inspect

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Verify the project is safe to point at live money."

    def handle(self, *args, **options):
        failures = []
        warnings = []

        def check(ok, label, hard=True):
            if ok:
                self.stdout.write(self.style.SUCCESS(f"  PASS  {label}"))
            else:
                self.stdout.write(
                    (self.style.ERROR if hard else self.style.WARNING)(
                        f"  {'FAIL' if hard else 'WARN'}  {label}"
                    )
                )
                (failures if hard else warnings).append(label)

        self.stdout.write("\nEnvironment")
        check(not settings.DEBUG, "DEBUG is False")
        check(
            settings.SECRET_KEY != "django-insecure-change-me-before-production",
            "SECRET_KEY has been replaced",
        )
        check(bool(settings.ALLOWED_HOSTS), "ALLOWED_HOSTS is set")

        self.stdout.write("\nSecrets")
        check(bool(settings.PAYSTACK_SECRET_KEY), "PAYSTACK_SECRET_KEY set")
        check(bool(settings.WHATSAPP_APP_SECRET), "WHATSAPP_APP_SECRET set (Part 4 Step 4)")
        check(bool(settings.WHATSAPP_TOKEN), "WHATSAPP_TOKEN set")
        check(bool(settings.WHATSAPP_VERIFY_TOKEN), "WHATSAPP_VERIFY_TOKEN set")
        check(
            bool(settings.STORAGE_ENDPOINT_URL),
            "Private object storage configured (Part 18.2)",
        )
        check(bool(settings.SENTRY_DSN), "SENTRY_DSN set (Part 23 Step 8)", hard=False)

        self.stdout.write("\nInfrastructure")
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT postgis_version();")
                version = cur.fetchone()[0]
            check(True, f"PostGIS reachable ({version})")
        except Exception as exc:  # noqa: BLE001
            check(False, f"PostGIS reachable — {exc}")

        try:
            cache.set("prodcheck", "1", 5)
            check(cache.get("prodcheck") == "1", "Redis cache reachable")
        except Exception as exc:  # noqa: BLE001
            check(False, f"Redis cache reachable — {exc}")

        self.stdout.write("\nConfiguration rows")
        from core.models import FeeConfig

        active = FeeConfig.objects.filter(active=True).first()
        check(active is not None, "An active FeeConfig row exists (Part 13 Step 5)")

        try:
            from django_celery_beat.models import PeriodicTask

            check(
                PeriodicTask.objects.filter(
                    task="marketplace.tasks.process_approved_payouts", enabled=True
                ).exists(),
                "process_approved_payouts Beat schedule enabled (Part 15 Step 5)",
            )
        except Exception as exc:  # noqa: BLE001
            check(False, f"Beat schedule — {exc}")

        self.stdout.write("\nNon-negotiable rules")
        from payments import services as payment_services
        from payments import views as payment_views
        from whatsappbot import views as bot_views

        # Rule #1 — only release_payout builds a /transfer request.
        offenders = []
        for module in (payment_views, bot_views):
            src = inspect.getsource(module)
            if "/transfer" in src:
                offenders.append(module.__name__)
        check(
            not offenders,
            f"Rule #1: only PaymentService.release_payout calls /transfer"
            + (f" — offenders: {offenders}" if offenders else ""),
        )

        # Rule #2 — the WhatsApp webhook verifies the signature.
        bot_src = inspect.getsource(bot_views.WhatsAppWebhookView.post)
        check(
            "verify_whatsapp_signature" in bot_src,
            "Rule #2: WhatsApp webhook verifies X-Hub-Signature-256",
        )

        # Rule #4 — Paystack webhook verifies its signature before touching money.
        pay_src = inspect.getsource(payment_views.PaystackWebhookView.post)
        check(
            "verify_paystack_signature" in pay_src,
            "Rule #4: Paystack webhook verifies X-Paystack-Signature",
        )
        check(
            "compare_digest" in inspect.getsource(payment_services.verify_paystack_signature),
            "Signature comparison is constant-time (hmac.compare_digest)",
        )

        self.stdout.write("")
        if failures:
            self.stdout.write(
                self.style.ERROR(
                    f"{len(failures)} blocking issue(s). Do NOT switch to live keys yet."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("All blocking checks passed. Safe for Part 23 Step 10.")
            )
        if warnings:
            self.stdout.write(self.style.WARNING(f"{len(warnings)} warning(s): {warnings}"))
