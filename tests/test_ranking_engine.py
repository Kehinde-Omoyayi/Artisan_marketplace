"""
Part 16 — the ranking engine, tested against real PostGIS.

These tests prove the properties the manual claims the formula has, so that anyone
tuning the weights later finds out immediately if they broke one.
"""

from decimal import Decimal

from django.contrib.gis.geos import Point
from django.test import TestCase

from accounts.models import ArtisanProfile, User
from job_requests.models import ServiceRequest
from marketplace.models import ArtisanLocation, Match
from marketplace.services import (
    MAX_ACTIVE_MATCHES,
    MAX_RADIUS_KM,
    find_and_rank_candidates,
    save_matches,
)
from services.models import ArtisanService, ServiceCategory

# Yaba, Lagos
YABA = Point(3.3792, 6.5244, srid=4326)


def make_artisan(phone, category, lng, lat, *, rating="5.0", jobs=50, level="L2"):
    user = User.objects.create(phone_e164=phone, role="artisan")
    ArtisanProfile.objects.create(
        user=user,
        rating_avg=Decimal(rating),
        completed_jobs=jobs,
        verification_level=level,
    )
    ArtisanService.objects.create(artisan=user, service=category, active=True)
    ArtisanLocation.objects.create(artisan=user, point=Point(lng, lat, srid=4326))
    return user


class RankingEngineTests(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Cleaning", slug="cleaning")
        self.customer = User.objects.create(phone_e164="2348000000000")
        self.request = ServiceRequest.objects.create(
            customer=self.customer,
            category=self.category,
            area_name="Yaba",
            location=YABA,
            timing="Today",
        )

    def test_request_without_location_returns_no_candidates(self):
        self.request.location = None
        self.request.save()
        self.assertEqual(find_and_rank_candidates(self.request), [])

    def test_artisan_outside_max_radius_is_excluded(self):
        # ~0.9 km away — inside.
        make_artisan("2348000000001", self.category, 3.3792, 6.5324)
        # Ibadan, ~120 km away — well outside MAX_RADIUS_KM.
        make_artisan("2348000000002", self.category, 3.9470, 7.3775)

        results = find_and_rank_candidates(self.request)
        self.assertEqual(len(results), 1)
        self.assertLess(float(results[0][1]), MAX_RADIUS_KM)

    def test_artisan_who_does_not_offer_the_service_is_excluded(self):
        other = ServiceCategory.objects.create(name="Tiling", slug="tiling")
        make_artisan("2348000000003", other, 3.3792, 6.5254)
        self.assertEqual(find_and_rank_candidates(self.request), [])

    def test_high_risk_category_requires_l2_verification(self):
        electrical = ServiceCategory.objects.create(name="Electrical", slug="electrical")
        request = ServiceRequest.objects.create(
            customer=self.customer,
            category=electrical,
            area_name="Yaba",
            location=YABA,
        )
        make_artisan("2348000000004", electrical, 3.3792, 6.5254, level="L1")
        self.assertEqual(find_and_rank_candidates(request), [])

        make_artisan("2348000000005", electrical, 3.3792, 6.5254, level="L2")
        self.assertEqual(len(find_and_rank_candidates(request)), 1)

    def test_closer_artisan_outranks_identical_farther_artisan(self):
        make_artisan("2348000000006", self.category, 3.3792, 6.5254)  # very close
        make_artisan("2348000000007", self.category, 3.3792, 6.6100)  # ~9.5 km

        results = find_and_rank_candidates(self.request)
        self.assertEqual(len(results), 2)
        self.assertLess(results[0][1], results[1][1])  # nearest first
        self.assertGreater(results[0][2], results[1][2])  # and higher score

    def test_rating_is_damped_by_sample_size(self):
        """A 5.0 from 1 job must not outrank a 4.6 from 80 jobs at equal distance."""
        make_artisan(
            "2348000000008", self.category, 3.3792, 6.5254, rating="5.0", jobs=1
        )
        make_artisan(
            "2348000000009", self.category, 3.3792, 6.5254, rating="4.6", jobs=80
        )
        results = find_and_rank_candidates(self.request)
        winner = results[0][0]
        self.assertEqual(winner.phone_e164, "2348000000009")

    def test_verification_level_is_a_soft_boost(self):
        make_artisan("2348000000010", self.category, 3.3792, 6.5254, level="L0")
        make_artisan("2348000000011", self.category, 3.3792, 6.5254, level="L4")
        results = find_and_rank_candidates(self.request)
        self.assertEqual(results[0][0].phone_e164, "2348000000011")
        # L0 is still present — verification is a boost, not a filter, off high-risk.
        self.assertEqual(len(results), 2)

    def test_suspended_artisan_never_matches(self):
        artisan = make_artisan("2348000000012", self.category, 3.3792, 6.5254)
        artisan.status = "suspended"
        artisan.save()
        self.assertEqual(find_and_rank_candidates(self.request), [])

    def test_exposure_penalty_demotes_a_recently_matched_artisan(self):
        busy = make_artisan("2348000000013", self.category, 3.3792, 6.5254)
        fresh = make_artisan("2348000000014", self.category, 3.3792, 6.5254)

        # Give `busy` three recent offers on other requests.
        for i in range(3):
            other_request = ServiceRequest.objects.create(
                customer=self.customer,
                category=self.category,
                area_name="Yaba",
                location=YABA,
            )
            Match.objects.create(
                request=other_request,
                artisan=busy,
                distance_km=Decimal("1.0"),
                ranking_score=Decimal("50"),
                ranking_version="v1",
                rank_position=1,
            )

        results = find_and_rank_candidates(self.request)
        self.assertEqual(results[0][0].phone_e164, fresh.phone_e164)

    def test_save_matches_writes_ranked_rows_and_is_idempotent(self):
        make_artisan("2348000000015", self.category, 3.3792, 6.5254)
        make_artisan("2348000000016", self.category, 3.3792, 6.5354)

        scored = find_and_rank_candidates(self.request)
        matches = save_matches(self.request, scored)

        self.assertEqual(len(matches), 2)
        self.assertEqual([m.rank_position for m in matches], [1, 2])
        self.assertTrue(all(m.ranking_version == "v1" for m in matches))

        # Re-running replaces rather than duplicating (unique_together would fail).
        save_matches(self.request, find_and_rank_candidates(self.request))
        self.assertEqual(Match.objects.filter(request=self.request).count(), 2)

    def test_save_matches_caps_at_top_n(self):
        for i in range(15):
            make_artisan(f"23480000001{i:02d}", self.category, 3.3792, 6.5254 + i * 0.001)
        scored = find_and_rank_candidates(self.request)
        matches = save_matches(self.request, scored, top_n=10)
        self.assertEqual(len(matches), 10)

    def test_save_matches_default_cap_is_max_active_matches(self):
        # Proves the *policy* default (currently 40), not just that an explicit
        # top_n argument is honored. Uses more candidates than the cap so a
        # regression back to a lower default would actually be caught.
        for i in range(MAX_ACTIVE_MATCHES + 5):
            make_artisan(f"2348000002{i:03d}", self.category, 3.3792, 6.5254 + i * 0.0005)
        scored = find_and_rank_candidates(self.request)
        matches = save_matches(self.request, scored)  # no top_n override
        self.assertEqual(len(matches), MAX_ACTIVE_MATCHES)
