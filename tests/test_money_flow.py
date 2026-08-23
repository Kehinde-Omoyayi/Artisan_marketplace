"""
Parts 7, 13, 17 and 20 — the money path.

The threshold rule, the audit trail, the dispute freeze, and the V1 ledger backfill.
No real Paystack call is made anywhere: `release_payout` is patched at the boundary.
"""

from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import ArtisanProfile, User
from bookings.models import Booking, BookingStatusHistory
from core.models import AuditLog, FeeConfig
from disputes.services import open_dispute
from job_requests.models import ServiceRequest
from payments.models import LedgerEntry, Payment, Payout, PayoutLedger
from payments.services import PaymentService
from services.models import ServiceCategory
from support_app.models import SupportCase


class MoneyFlowTestCase(TestCase):
    def setUp(self):
        FeeConfig.objects.create(
            version=1,
            platform_commission_percent=Decimal("10.00"),
            payout_approval_threshold_minor=5000000,  # ₦50,000
            active=True,
        )
        self.customer = User.objects.create(phone_e164="2348030000001")
        self.artisan = User.objects.create(phone_e164="2348030000002", role="artisan")
        ArtisanProfile.objects.create(user=self.artisan)
        self.category = ServiceCategory.objects.create(name="Plumbing", slug="plumbing")
        self.request = ServiceRequest.objects.create(
            customer=self.customer, category=self.category, area_name="Surulere"
        )

    def _booking(self, amount_minor):
        return Booking.objects.create(
            request=self.request,
            customer=self.customer,
            artisan=self.artisan,
            agreed_amount_minor=amount_minor,
        )


class PayoutThresholdTests(MoneyFlowTestCase):
    def test_payout_below_threshold_is_auto_approved(self):
        booking = self._booking(4999999)  # ₦49,999.99
        payout = PaymentService.create_payout(booking, "RCP_test")
        self.assertEqual(payout.status, "approved")

    def test_payout_at_threshold_needs_human_approval(self):
        booking = self._booking(5000000)  # exactly ₦50,000
        payout = PaymentService.create_payout(booking, "RCP_test")
        self.assertEqual(payout.status, "pending_approval")

    def test_payout_above_threshold_needs_human_approval(self):
        booking = self._booking(9000000)
        payout = PaymentService.create_payout(booking, "RCP_test")
        self.assertEqual(payout.status, "pending_approval")

    def test_threshold_falls_back_to_default_when_no_active_feeconfig(self):
        FeeConfig.objects.update(active=False)
        booking = self._booking(100000)
        payout = PaymentService.create_payout(booking, "RCP_test")
        self.assertEqual(payout.status, "approved")


class BookingLifecycleTests(MoneyFlowTestCase):
    def test_status_change_always_writes_history(self):
        from bookings.views import change_booking_status

        booking = self._booking(100000)
        change_booking_status(booking, "payment_confirmed", actor="test")
        self.assertTrue(
            BookingStatusHistory.objects.filter(
                booking=booking, to_status="payment_confirmed"
            ).exists()
        )

    def test_unknown_status_is_rejected(self):
        from bookings.views import change_booking_status

        booking = self._booking(100000)
        with self.assertRaises(ValueError):
            change_booking_status(booking, "totally_made_up")

    def test_complete_booking_creates_payout_and_moves_status_together(self):
        from bookings.views import complete_booking_and_create_payout

        booking = self._booking(200000)
        payout = complete_booking_and_create_payout(booking, "RCP_test", actor="test")

        booking.refresh_from_db()
        self.assertEqual(booking.status, "customer_completed")
        self.assertEqual(payout.booking_id, booking.id)
        self.assertEqual(payout.status, "approved")


class ReleasePayoutTests(MoneyFlowTestCase):
    @patch("payments.services.requests.post")
    def test_release_payout_marks_processing_and_audits(self, mock_post):
        mock_post.return_value.json.return_value = {
            "status": True,
            "data": {"transfer_code": "TRF_xyz789"},
        }
        booking = self._booking(100000)
        payout = PaymentService.create_payout(booking, "RCP_test")

        PaymentService.release_payout(payout)
        payout.refresh_from_db()

        self.assertEqual(payout.status, "processing")
        self.assertEqual(payout.paystack_transfer_code, "TRF_xyz789")
        self.assertTrue(
            AuditLog.objects.filter(
                action="payout_transfer_initiated", target_id=str(payout.id)
            ).exists()
        )

    @patch("payments.services.requests.post")
    def test_release_payout_refuses_pending_approval(self, mock_post):
        booking = self._booking(9000000)
        payout = PaymentService.create_payout(booking, "RCP_test")
        self.assertEqual(payout.status, "pending_approval")
        with self.assertRaises(ValueError):
            PaymentService.release_payout(payout)
        mock_post.assert_not_called()

    @patch("payments.services.PaymentService.release_payout")
    def test_scheduled_task_only_picks_up_approved_payouts(self, mock_release):
        from marketplace.tasks import process_approved_payouts

        approved = PaymentService.create_payout(self._booking(100000), "RCP_a")
        PaymentService.create_payout(self._booking(9000000), "RCP_b")  # pending

        process_approved_payouts()

        self.assertEqual(mock_release.call_count, 1)
        self.assertEqual(mock_release.call_args[0][0].id, approved.id)


class DisputeFreezeTests(MoneyFlowTestCase):
    def test_opening_a_dispute_freezes_an_approved_payout(self):
        booking = self._booking(100000)
        payout = PaymentService.create_payout(booking, "RCP_test")
        self.assertEqual(payout.status, "approved")

        dispute = open_dispute(booking, self.customer, "not_completed", "Never showed")

        payout.refresh_from_db()
        self.assertEqual(payout.status, "pending_approval")
        self.assertTrue(
            AuditLog.objects.filter(
                action="payout_frozen_by_dispute", target_id=str(payout.id)
            ).exists()
        )
        self.assertTrue(SupportCase.objects.filter(dispute=dispute).exists())
        self.assertEqual(SupportCase.objects.get(dispute=dispute).priority, "high")

    def test_dispute_does_not_unfreeze_an_already_paid_payout(self):
        booking = self._booking(100000)
        payout = PaymentService.create_payout(booking, "RCP_test")
        payout.status = "paid"
        payout.save()

        open_dispute(booking, self.customer, "poor_work")

        payout.refresh_from_db()
        self.assertEqual(payout.status, "paid")


class LedgerBackfillTests(MoneyFlowTestCase):
    def test_backfill_is_idempotent(self):
        booking = self._booking(100000)
        PayoutLedger.objects.create(
            booking=booking,
            artisan=self.artisan,
            amount_minor=100000,
            paid_at=timezone.now(),
        )
        PayoutLedger.objects.create(
            booking=booking, artisan=self.artisan, amount_minor=50000, paid_at=None
        )  # never paid — must be skipped

        call_command("backfill_v1_ledger")
        self.assertEqual(LedgerEntry.objects.count(), 1)

        call_command("backfill_v1_ledger")
        self.assertEqual(LedgerEntry.objects.count(), 1)

        entry = LedgerEntry.objects.first()
        self.assertEqual(entry.entry_type, "artisan_earning")
        self.assertEqual(entry.amount_minor, 100000)


class AuditLogTests(MoneyFlowTestCase):
    def test_audit_log_is_append_only_in_admin(self):
        from django.contrib.admin.sites import site

        from core.models import AuditLog as AuditLogModel

        model_admin = site._registry[AuditLogModel]
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
