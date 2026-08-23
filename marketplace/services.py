"""
marketplace/services.py — Part 16, THE RANKING ENGINE.

PostGIS candidate search plus a transparent, hand-written, versioned scoring formula.
No model, no embedding, no LLM (Part 19: V2 has zero AI, deliberately).

This is the ONE place ranking weights live. Change them here, not in three views.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from accounts.models import ArtisanProfile
from services.models import ArtisanService

from .models import ArtisanLocation, Match

RANKING_VERSION = "v1"
MAX_RADIUS_KM = 15
# How many artisans can hold an open offer for one request at once. Used both
# for the initial broadcast (save_matches) and for topping the pool back up
# after a decline (marketplace.tasks.backfill_match_slot). Change it here only
# — not as a separate literal in either caller.
MAX_ACTIVE_MATCHES = 40
MIN_JOBS_FOR_FULL_RATING_WEIGHT = 10
EXPOSURE_WINDOW_HOURS = 24
# Tune this to the slugs that actually exist in your ServiceCategory table.
HIGH_RISK_CATEGORY_SLUGS = ("in-home-repair", "electrical", "plumbing")
VERIFICATION_BONUS = {
    "L0": Decimal("0"),
    "L1": Decimal("5"),
    "L2": Decimal("15"),
    "L3": Decimal("22"),
    "L4": Decimal("30"),
}


def find_and_rank_candidates(service_request):
    """
    Returns a list of (artisan, distance_km, score) tuples, highest score first.
    Every factor below is explained inline.

    Performance note: this runs a fixed, small number of queries regardless of how
    many candidates are in radius — 1 for the geospatial candidate search, plus 3
    bulk lookups (service offerings, exposure counts, profile join via
    select_related) instead of doing any of those per-candidate in a Python loop.
    At MAX_RADIUS_KM=15 in a dense metro area this can easily be several hundred
    candidates for a popular category; the difference is O(1) queries vs. O(n), not
    a micro-optimization.
    """
    if not service_request.location:
        return []

    candidates = list(
        ArtisanLocation.objects.filter(
            point__distance_lte=(service_request.location, D(km=MAX_RADIUS_KM))
        )
        .annotate(distance=Distance("point", service_request.location))
        .select_related("artisan", "artisan__artisan_profile")
    )
    if not candidates:
        return []

    artisan_ids = [loc.artisan_id for loc in candidates]

    # Bulk lookup #1: who among these candidates actually offers this service?
    # One query for the whole batch instead of one `.exists()` per candidate.
    offering_artisan_ids = set(
        ArtisanService.objects.filter(
            artisan_id__in=artisan_ids, service=service_request.category, active=True
        ).values_list("artisan_id", flat=True)
    )

    # Bulk lookup #2: how many offers has each candidate already received in the
    # exposure window? One aggregate query instead of one `.count()` per candidate.
    window_start = timezone.now() - timedelta(hours=EXPOSURE_WINDOW_HOURS)
    recent_offer_counts = dict(
        Match.objects.filter(artisan_id__in=artisan_ids, created_at__gte=window_start)
        .values("artisan_id")
        .annotate(c=Count("id"))
        .values_list("artisan_id", "c")
    )

    scored = []
    for loc in candidates:
        artisan = loc.artisan

        if artisan.id not in offering_artisan_ids:
            continue

        # `select_related("artisan__artisan_profile")` above already fetched this
        # in the same query as `candidates` — no extra round trip here.
        try:
            profile = artisan.artisan_profile
        except ArtisanProfile.DoesNotExist:
            continue

        if service_request.category.slug in HIGH_RISK_CATEGORY_SLUGS and (
            profile.verification_level in ("L0", "L1")
        ):
            continue

        if not profile.is_active or artisan.status == "suspended":
            continue

        distance_km = Decimal(str(round(loc.distance.km, 2)))
        exposure_count = recent_offer_counts.get(artisan.id, 0)
        score = _score_candidate(profile, distance_km, exposure_count)
        scored.append((artisan, distance_km, score))

    scored.sort(key=lambda row: row[2], reverse=True)
    return scored


def _score_candidate(profile, distance_km, exposure_count):
    # Rating: damped by sample size, so a 5.0 from 1 job doesn't outrank a 4.6 from 80.
    sample_weight = min(
        Decimal(profile.completed_jobs) / MIN_JOBS_FOR_FULL_RATING_WEIGHT,
        Decimal("1.0"),
    )
    rating_component = (profile.rating_avg / Decimal("5.0")) * sample_weight * Decimal("40")

    # Verification: soft boost, not a hard filter, except where hard filter #2 applied.
    verification_bonus = VERIFICATION_BONUS.get(profile.verification_level, Decimal("0"))

    # Distance: decay, not a wall — a slightly farther artisan can still win on
    # rating/verification.
    distance_decay = max(Decimal("0"), Decimal("30") - (distance_km * Decimal("2")))

    # Exposure balancing: an artisan who already received several offers in the last day
    # gets a small penalty, so the same 3-4 top artisans don't receive every request.
    exposure_penalty = Decimal(exposure_count) * Decimal("5")

    return rating_component + verification_bonus + distance_decay - exposure_penalty


def save_matches(service_request, scored_candidates, top_n=MAX_ACTIVE_MATCHES):
    Match.objects.filter(request=service_request).delete()
    matches = []
    for position, (artisan, distance_km, score) in enumerate(
        scored_candidates[:top_n], start=1
    ):
        matches.append(
            Match(
                request=service_request,
                artisan=artisan,
                distance_km=distance_km,
                ranking_score=score,
                ranking_version=RANKING_VERSION,
                rank_position=position,
            )
        )
    Match.objects.bulk_create(matches)
    return matches


def accept_offer(match):
    """
    Part 24 — an artisan replied YES to an open offer.

    Locks the ServiceRequest row so two artisans accepting within milliseconds of
    each other can't both win the job. Returns the created Booking, or None if the
    request was already filled/cancelled before this accept was processed (the
    artisan should be told the job is no longer available).
    """
    from bookings.models import Booking
    from bookings.views import change_booking_status
    from job_requests.models import ServiceRequest
    from notifications.services import send_notification

    with transaction.atomic():
        service_request = ServiceRequest.objects.select_for_update().get(
            pk=match.request_id
        )
        if service_request.status != "open":
            match.response_status = "expired"
            match.responded_at = timezone.now()
            match.save(update_fields=["response_status", "responded_at"])
            return None

        match.response_status = "accepted"
        match.responded_at = timezone.now()
        match.save(update_fields=["response_status", "responded_at"])

        service_request.status = "matched"
        service_request.save(update_fields=["status"])

        booking = Booking.objects.create(
            request=service_request,
            customer=service_request.customer,
            artisan=match.artisan,
        )
        # change_booking_status re-fetches and saves its own copy of the row —
        # use what it returns, not the pre-update `booking` reference, or the
        # caller sees a stale in-memory status of "pending".
        booking = change_booking_status(
            booking, "accepted", actor=f"artisan:{match.artisan.phone_e164}"
        )

        # Every other artisan who was still holding one of the active slots for
        # this request loses it now that the job is filled.
        stale_matches = list(
            Match.objects.filter(
                request=service_request, response_status="pending"
            ).exclude(pk=match.pk)
        )
        Match.objects.filter(pk__in=[m.pk for m in stale_matches]).update(
            response_status="expired", responded_at=timezone.now()
        )

    for stale in stale_matches:
        send_notification(
            stale.artisan,
            "offer_filled_elsewhere",
            f"The {service_request.category.name} job in {service_request.area_name} "
            f"has been taken by another artisan. Thanks for your quick response.",
        )

    send_notification(
        service_request.customer,
        "artisan_confirmed",
        f"Good news! {match.artisan.full_name or match.artisan.phone_e164} has "
        f"accepted your {service_request.category.name} request and will be in "
        f"touch shortly.",
    )
    return booking


def decline_offer(match):
    """
    Part 24 — an artisan replied NO to an open offer. Frees their slot and queues a
    background job to backfill it with the next-best candidate who doesn't already
    have an offer for this request, so the active pool stays topped up (towards
    MAX_ACTIVE_MATCHES) instead of just shrinking every time someone declines.
    """
    match.response_status = "declined"
    match.responded_at = timezone.now()
    match.save(update_fields=["response_status", "responded_at"])

    from .tasks import backfill_match_slot

    backfill_match_slot.delay(str(match.request_id))
    return match
