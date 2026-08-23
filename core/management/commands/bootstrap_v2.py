"""
One command that does every "go to /admin and click this" step in the V2 manual:

  * Part 13 Step 5 — create the active FeeConfig row (nothing in Part 17 works without it)
  * Part 15 Step 5 — register the 5-minute `process_approved_payouts` Celery Beat schedule
  * Part 11 Step 4 — build the three RBAC staff groups
  * seeds the default service categories if the table is empty

Safe to re-run: everything is get_or_create / update_or_create.

    python manage.py bootstrap_v2
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from core.models import FeeConfig
from services.models import ServiceCategory

DEFAULT_CATEGORIES = [
    "Plumbing",
    "Electrical",
    "Carpentry",
    "Painting",
    "AC Repair",
    "Generator Repair",
    "Tiling",
    "Cleaning",
]


class Command(BaseCommand):
    help = "Create the FeeConfig, Celery Beat schedule, RBAC groups and seed categories."

    def add_arguments(self, parser):
        parser.add_argument("--commission", default="10.00")
        parser.add_argument("--threshold-minor", type=int, default=5000000)
        parser.add_argument("--skip-categories", action="store_true", default=False)

    def handle(self, *args, **options):
        # --- Part 13 Step 5 -------------------------------------------------------
        fee, created = FeeConfig.objects.get_or_create(
            version=1,
            defaults={
                "platform_commission_percent": options["commission"],
                "payout_approval_threshold_minor": options["threshold_minor"],
                "active": True,
            },
        )
        if not created and not FeeConfig.objects.filter(active=True).exists():
            fee.active = True
            fee.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"FeeConfig v{fee.version}: {fee.platform_commission_percent}% "
                f"commission, approval threshold {fee.payout_approval_threshold_minor} "
                f"kobo (₦{fee.payout_approval_threshold_minor / 100:,.2f})"
            )
        )

        # --- Part 15 Step 5 -------------------------------------------------------
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=5, period=IntervalSchedule.MINUTES
        )
        PeriodicTask.objects.update_or_create(
            name="process-approved-payouts",
            defaults={
                "task": "marketplace.tasks.process_approved_payouts",
                "interval": interval,
                "enabled": True,
            },
        )
        self.stdout.write(
            self.style.SUCCESS("Celery Beat: process-approved-payouts every 5 minutes")
        )

        # --- Part 11 Step 4 -------------------------------------------------------
        call_command("setup_staff_roles")

        # --- Service categories ---------------------------------------------------
        if not options["skip_categories"] and not ServiceCategory.objects.exists():
            for name in DEFAULT_CATEGORIES:
                ServiceCategory.objects.get_or_create(
                    name=name, defaults={"slug": slugify(name), "active": True}
                )
            self.stdout.write(
                self.style.SUCCESS(f"Seeded {len(DEFAULT_CATEGORIES)} service categories")
            )
        else:
            self.stdout.write("Service categories already present — left alone.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("V2 bootstrap complete."))
