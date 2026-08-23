"""marketplace/tasks.py — Part 15 Step 3. Background jobs so nothing blocks a webhook."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def run_matching_for_request(request_id):
    from job_requests.models import ServiceRequest
    from notifications.services import send_notification

    from .services import find_and_rank_candidates, save_matches

    try:
        service_request = ServiceRequest.objects.get(id=request_id)
    except ServiceRequest.DoesNotExist:
        logger.warning("run_matching_for_request: no ServiceRequest %s", request_id)
        return

    scored = find_and_rank_candidates(service_request)
    matches = save_matches(service_request, scored)
    logger.info("Matched %s artisans for request %s", len(matches), request_id)

    for match in matches:
        send_notification(
            match.artisan,
            "new_job_match",
            f"New job: {service_request.category.name} near you, timing: "
            f"{service_request.timing}. "
            f"Reply YES {match.offer_code} to accept or NO {match.offer_code} to decline.",
        )


@shared_task
def backfill_match_slot(request_id):
    """
    Part 24 — fired whenever an artisan declines an offer. Tops the active slot
    pool for this request back up (towards MAX_ACTIVE_MATCHES in save_matches) by
    offering the job to the next-best ranked candidate who doesn't already hold a
    slot for it. No-ops once the job is filled/cancelled, or once no more
    unmatched candidates exist within range.
    """
    from job_requests.models import ServiceRequest
    from notifications.services import send_notification

    from .models import Match
    from .services import MAX_ACTIVE_MATCHES, RANKING_VERSION, find_and_rank_candidates

    try:
        service_request = ServiceRequest.objects.get(id=request_id)
    except ServiceRequest.DoesNotExist:
        logger.warning("backfill_match_slot: no ServiceRequest %s", request_id)
        return

    if service_request.status != "open":
        return  # already matched, cancelled, or expired — nothing to backfill

    already_matched_ids = set(
        Match.objects.filter(request=service_request).values_list(
            "artisan_id", flat=True
        )
    )
    active_pending = Match.objects.filter(
        request=service_request, response_status="pending"
    ).count()
    if active_pending >= MAX_ACTIVE_MATCHES:
        return

    scored = find_and_rank_candidates(service_request)
    next_candidate = next(
        ((a, d, s) for (a, d, s) in scored if a.id not in already_matched_ids), None
    )
    if not next_candidate:
        logger.info(
            "backfill_match_slot: no replacement candidate for request %s", request_id
        )
        return

    artisan, distance_km, score = next_candidate
    next_rank = Match.objects.filter(request=service_request).count() + 1

    match = Match.objects.create(
        request=service_request,
        artisan=artisan,
        distance_km=distance_km,
        ranking_score=score,
        ranking_version=RANKING_VERSION,
        rank_position=next_rank,
    )
    send_notification(
        artisan,
        "new_job_match",
        f"New job: {service_request.category.name} near you, timing: "
        f"{service_request.timing}. "
        f"Reply YES {match.offer_code} to accept or NO {match.offer_code} to decline.",
    )
    logger.info(
        "Backfilled request %s slot with artisan %s (rank %s)",
        request_id,
        artisan,
        next_rank,
    )


@shared_task
def process_approved_payouts():
    """
    Scheduled every 5 minutes by Celery Beat (Part 15 Step 5).
    Payouts below the FeeConfig threshold were created already `approved` and go out
    here with no human involvement. Anything at/above the threshold sits at
    `pending_approval` until finance_staff approves it in /admin.
    """
    from payments.models import Payout
    from payments.services import PaymentService

    for payout in Payout.objects.filter(status="approved"):
        try:
            PaymentService.release_payout(payout)
        except Exception:  # noqa: BLE001 — one bad payout must not stop the batch
            logger.exception("release_payout failed for payout %s", payout.id)
