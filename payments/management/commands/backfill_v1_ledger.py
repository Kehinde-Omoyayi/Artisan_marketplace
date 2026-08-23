"""
Part 20 — data migration from V1's manual payout ledger into `ledger_entries`.

The manual has you paste this into `python manage.py shell`. That is fine once, but a
management command is re-runnable, testable, and auditable. Identical logic: it skips
anything already migrated by checking the reference, so it is safe to run repeatedly.

    python manage.py backfill_v1_ledger            # apply
    python manage.py backfill_v1_ledger --dry-run  # count only, write nothing

`PayoutLedger` is NOT deleted afterwards — it stays as the original historical record.
`LedgerEntry` is the forward-looking source of truth.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from payments.models import LedgerEntry, PayoutLedger


class Command(BaseCommand):
    help = "Backfill historical PayoutLedger rows into LedgerEntry (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=False)

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        migrated = 0
        skipped = 0

        for old_payout in PayoutLedger.objects.exclude(paid_at__isnull=True):
            reference = f"V1-BACKFILL-{old_payout.id}"
            if LedgerEntry.objects.filter(reference=reference).exists():
                skipped += 1
                continue
            if not dry_run:
                LedgerEntry.objects.create(
                    booking=old_payout.booking,
                    entry_type="artisan_earning",
                    amount_minor=old_payout.amount_minor,
                    reference=reference,
                )
            migrated += 1

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — would migrate {migrated} rows, {skipped} already present."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Migrated {migrated} historical payout rows into ledger_entries "
                    f"({skipped} already present)."
                )
            )
