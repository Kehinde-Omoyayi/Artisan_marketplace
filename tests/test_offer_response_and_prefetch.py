"""
Part 24 — closing two gaps the V2 manual left open:

  1. Artisans could be offered a job ("Reply YES to accept") but nothing ever
     read their reply. accept_offer / decline_offer / backfill_match_slot plus
     the WhatsApp-side try_handle_offer_reply() close that loop.
  2. Returning customers were re-asked for area + GPS pin on every request even
     though CustomerProfile existed to store it. The awaiting_saved_address_choice
     state plus the write-back in the awaiting_timing branch close that gap.
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.test import TestCase

from accounts.models import ArtisanProfile, CustomerProfile, User
from bookings.models import Booking
from job_requests.models import ServiceRequest
from marketplace.models import ArtisanLocation, Match
from marketplace.services import accept_offer, decline_offer, save_matches
from marketplace.tasks import backfill_match_slot
from services.models import ArtisanService, ServiceCategory
from whatsappbot.models import ConversationState
from whatsappbot.views import handle_incoming_location, handle_incoming_text

YABA = Point(3.3792, 6.5244, srid=4326)


def make_artisan(phone, category, lng, lat, *, rating="4.5", jobs=20, level="L2"):
    user = User.objects.create(phone_e164=phone, role="artisan")
    ArtisanProfile.objects.create(
        user=user, rating_avg=Decimal(rating), completed_jobs=jobs, verification_level=level
    )
    ArtisanService.objects.create(artisan=user, service=category, active=True)
    ArtisanLocation.objects.create(artisan=user, point=Point(lng, lat, srid=4326))
    return user


def make_match(request, artisan, rank=1):
    return Match.objects.create(
        request=request,
        artisan=artisan,
        distance_km=Decimal("1.0"),
        ranking_score=Decimal("50"),
        ranking_version="v1",
        rank_position=rank,
    )


class AcceptOfferTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Cleaning", slug="cleaning")
        self.customer = User.objects.create(phone_e164="2348000000000")
        self.request = ServiceRequest.objects.create(
            customer=self.customer, category=self.category, area_name="Yaba",
            location=YABA, timing="Today",
        )
        self.artisan_a = make_artisan("2348000000001", self.category, 3.3792, 6.5254)
        self.artisan_b = make_artisan("2348000000002", self.category, 3.3792, 6.5264)
        self.match_a = make_match(self.request, self.artisan_a, rank=1)
        self.match_b = make_match(self.request, self.artisan_b, rank=2)

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_accept_creates_booking_and_expires_other_matches(self, mock_send):
        booking = accept_offer(self.match_a)

        self.assertIsNotNone(booking)
        self.assertEqual(booking.artisan, self.artisan_a)
        self.assertEqual(booking.customer, self.customer)
        self.assertEqual(booking.status, "accepted")
        self.assertEqual(Booking.objects.count(), 1)

        self.match_a.refresh_from_db()
        self.match_b.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.match_a.response_status, "accepted")
        self.assertEqual(self.match_b.response_status, "expired")
        self.assertEqual(self.request.status, "matched")

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_second_artisan_accepting_a_filled_job_gets_none_back(self, mock_send):
        accept_offer(self.match_a)  # artisan A wins the job first

        result = accept_offer(self.match_b)  # artisan B tries a moment later

        self.assertIsNone(result)
        self.match_b.refresh_from_db()
        self.assertEqual(self.match_b.response_status, "expired")
        self.assertEqual(Booking.objects.count(), 1)  # still just the one booking


class DeclineAndBackfillTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Cleaning", slug="cleaning")
        self.customer = User.objects.create(phone_e164="2348000000000")
        self.request = ServiceRequest.objects.create(
            customer=self.customer, category=self.category, area_name="Yaba",
            location=YABA, timing="Today",
        )
        self.artisan_a = make_artisan("2348000000001", self.category, 3.3792, 6.5254)
        self.artisan_b = make_artisan("2348000000002", self.category, 3.3792, 6.5264)
        self.match_a = make_match(self.request, self.artisan_a, rank=1)

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_decline_marks_match_and_queues_backfill(self, mock_send):
        with patch("marketplace.tasks.backfill_match_slot.delay") as mock_backfill:
            decline_offer(self.match_a)

        self.match_a.refresh_from_db()
        self.assertEqual(self.match_a.response_status, "declined")
        mock_backfill.assert_called_once_with(str(self.request.id))

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_backfill_offers_the_job_to_the_next_unmatched_candidate(self, mock_send):
        decline_offer(self.match_a)  # frees artisan A's slot, artisan B never had one

        backfill_match_slot(str(self.request.id))

        new_match = Match.objects.exclude(pk=self.match_a.pk).get()
        self.assertEqual(new_match.artisan, self.artisan_b)
        self.assertEqual(new_match.response_status, "pending")
        self.assertEqual(new_match.rank_position, 2)

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_backfill_does_nothing_once_request_already_filled(self, mock_send):
        self.request.status = "matched"
        self.request.save(update_fields=["status"])

        backfill_match_slot(str(self.request.id))

        self.assertEqual(Match.objects.count(), 1)  # no new match was created

    @patch("notifications.services._send_whatsapp", return_value=None)
    def test_backfill_is_a_noop_when_no_replacement_candidate_exists(self, mock_send):
        # Only artisan A exists in range for this category; nobody left to backfill with.
        self.artisan_b.artisan_profile.delete()
        self.artisan_b.delete()

        decline_offer(self.match_a)
        backfill_match_slot(str(self.request.id))

        self.assertEqual(Match.objects.count(), 1)


@patch("notifications.services._send_whatsapp", return_value=None)
class WhatsAppOfferReplyTests(TestCase):
    """Same tests as above, but through the actual WhatsApp text handler —
    proves an artisan's real "YES"/"NO" message is no longer swallowed by the
    customer 'start a new request' branch."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Cleaning", slug="cleaning")
        self.customer = User.objects.create(phone_e164="2348000000000")
        self.request = ServiceRequest.objects.create(
            customer=self.customer, category=self.category, area_name="Yaba",
            location=YABA, timing="Today",
        )

    def test_yes_with_code_accepts_and_does_not_start_a_customer_flow(self, mock_send):
        artisan = make_artisan("2348011111111", self.category, 3.3792, 6.5254)
        match = make_match(self.request, artisan)
        ConversationState.objects.create(phone_e164=artisan.phone_e164, state="start")

        handle_incoming_text(artisan.phone_e164, f"YES {match.offer_code}")

        match.refresh_from_db()
        self.assertEqual(match.response_status, "accepted")
        self.assertEqual(Booking.objects.count(), 1)
        # Crucially: the artisan was NOT pulled into the customer category-selection flow.
        state = ConversationState.objects.get(phone_e164=artisan.phone_e164)
        self.assertEqual(state.state, "start")

    def test_no_with_code_declines_and_triggers_backfill(self, mock_send):
        artisan = make_artisan("2348022222222", self.category, 3.3792, 6.5254)
        match = make_match(self.request, artisan)
        ConversationState.objects.create(phone_e164=artisan.phone_e164, state="start")

        with patch("marketplace.tasks.backfill_match_slot.delay") as mock_backfill:
            handle_incoming_text(artisan.phone_e164, f"NO {match.offer_code}")

        match.refresh_from_db()
        self.assertEqual(match.response_status, "declined")
        mock_backfill.assert_called_once_with(str(self.request.id))

    def test_bare_yes_with_two_open_offers_asks_for_a_code(self, mock_send):
        artisan = make_artisan("2348033333333", self.category, 3.3792, 6.5254)
        other_request = ServiceRequest.objects.create(
            customer=self.customer, category=self.category, area_name="Ikeja",
            location=YABA, timing="Today",
        )
        make_match(self.request, artisan, rank=1)
        make_match(other_request, artisan, rank=1)
        ConversationState.objects.create(phone_e164=artisan.phone_e164, state="start")

        handle_incoming_text(artisan.phone_e164, "YES")

        # Neither offer should have been silently accepted.
        self.assertEqual(Booking.objects.count(), 0)
        self.assertTrue(
            Match.objects.filter(response_status="pending").count() == 2
        )

    def test_unknown_code_does_not_crash_or_advance_state(self, mock_send):
        artisan = make_artisan("2348044444444", self.category, 3.3792, 6.5254)
        ConversationState.objects.create(phone_e164=artisan.phone_e164, state="start")

        handle_incoming_text(artisan.phone_e164, "YES ZZZZZZ")

        self.assertEqual(Booking.objects.count(), 0)


@patch("notifications.services._send_whatsapp", return_value=None)
class SavedAddressPrefetchTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Plumbing", slug="plumbing")
        self.phone = "2348055555555"

    def _run_full_first_request(self):
        with patch("marketplace.tasks.run_matching_for_request.delay"):
            handle_incoming_text(self.phone, "hi")
            handle_incoming_text(self.phone, "Plumbing")
            handle_incoming_text(self.phone, "Yaba")
            handle_incoming_location(self.phone, 6.5244, 3.3792)
            handle_incoming_text(self.phone, "Today")

    def test_first_request_has_no_saved_profile_and_asks_for_area(self, mock_send):
        self._run_full_first_request()

        state = ConversationState.objects.get(phone_e164=self.phone)
        self.assertEqual(state.state, "start")
        profile = CustomerProfile.objects.get(user__phone_e164=self.phone)
        self.assertEqual(profile.default_area, "Yaba")
        self.assertIsNotNone(profile.saved_location)
        self.assertEqual(profile.total_requests, 1)

    def test_second_request_offers_saved_address_instead_of_asking_again(self, mock_send):
        self._run_full_first_request()

        with patch("marketplace.tasks.run_matching_for_request.delay"):
            handle_incoming_text(self.phone, "hi")
            handle_incoming_text(self.phone, "Plumbing")
            state = ConversationState.objects.get(phone_e164=self.phone)
            self.assertEqual(state.state, "awaiting_saved_address_choice")

            handle_incoming_text(self.phone, "YES")
            state.refresh_from_db()
            # Skipped straight past area + GPS pin to the timing question.
            self.assertEqual(state.state, "awaiting_timing")
            self.assertEqual(state.data["area_name"], "Yaba")

            handle_incoming_text(self.phone, "Flexible")

        self.assertEqual(ServiceRequest.objects.count(), 2)
        second_request = ServiceRequest.objects.latest("created_at")
        self.assertEqual(second_request.area_name, "Yaba")
        self.assertIsNotNone(second_request.location)

        profile = CustomerProfile.objects.get(user__phone_e164=self.phone)
        self.assertEqual(profile.total_requests, 2)

    def test_second_request_can_still_choose_a_new_address(self, mock_send):
        self._run_full_first_request()

        with patch("marketplace.tasks.run_matching_for_request.delay"):
            handle_incoming_text(self.phone, "hi")
            handle_incoming_text(self.phone, "Plumbing")
            handle_incoming_text(self.phone, "NEW")

            state = ConversationState.objects.get(phone_e164=self.phone)
            self.assertEqual(state.state, "awaiting_area")

            handle_incoming_text(self.phone, "Ikeja")
            handle_incoming_location(self.phone, 6.6018, 3.3515)
            handle_incoming_text(self.phone, "Today")

        second_request = ServiceRequest.objects.latest("created_at")
        self.assertEqual(second_request.area_name, "Ikeja")

        # The saved profile now reflects the newest address, not the first one.
        profile = CustomerProfile.objects.get(user__phone_e164=self.phone)
        self.assertEqual(profile.default_area, "Ikeja")
