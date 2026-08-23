import logging

from django.db import transaction

from .models import Booking, BookingStatusHistory

logger = logging.getLogger(__name__)


@transaction.atomic
def change_booking_status(booking, new_status, actor=None, note=""):
    """Move a booking to `new_status` and write the mandatory history row."""
    valid = dict(Booking.STATUS_CHOICES)
    if new_status not in valid:
        raise ValueError(f"Unknown booking status: {new_status}")

    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    previous = booking.status
    if previous == new_status:
        return booking

    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])

    BookingStatusHistory.objects.create(
        booking=booking,
        from_status=previous,
        to_status=new_status,
        actor=str(actor or "system"),
        note=note,
    )
    logger.info("Booking %s: %s -> %s by %s", booking.booking_ref, previous, new_status, actor)
    return booking


def complete_booking_and_create_payout(booking, artisan_recipient_code, actor=None):
    from payments.services import PaymentService

    change_booking_status(booking, "customer_completed", actor=actor)
    return PaymentService.create_payout(booking, artisan_recipient_code)
