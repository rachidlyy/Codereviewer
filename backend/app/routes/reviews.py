"""AI review endpoint.

``POST /api/reviews`` turns a submission plus its execution results into a
structured, educational review, and records it against the run it describes.

Following plan section 11 the route only validates and delegates - every piece
of LLM logic lives in :mod:`app.services.ai_reviewer`.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import problems as problem_data
from app.db import get_db
from app.deps import CurrentUser
from app.models.review import ReviewRecord
from app.models.submission import Submission
from app.schemas.submission import ReviewRequest, ReviewResponse
from app.services.ai_reviewer import ReviewUnavailable, review_submission, validate_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

#: Copy shown when the configured model cannot be reached (plan section 16).
#: The student stays on the coding page and can simply try again.
UNAVAILABLE_MESSAGE = "AI Review temporarily unavailable. Please try again."


def _persist_review(
    db: Session,
    submission_id: int,
    user_id: int,
    review: ReviewResponse,
) -> None:
    """Attach ``review`` to the run it describes, replacing any earlier one.

    ``reviews.submission_id`` is unique, so this is an upsert: asking for a
    second opinion on the same run must replace the old verdict rather than
    accumulate duplicates against it.
    """
    owned = db.scalar(
        select(Submission).where(
            Submission.id == submission_id,
            Submission.user_id == user_id,
        )
    )
    if owned is None:
        # The id came from a run response we issued ourselves, so a miss means
        # a bug or a race rather than anything the student did. Skipping keeps
        # their review - which is the actual deliverable - and logs the
        # anomaly for whoever is reading the server log.
        logger.warning(
            "Not persisting review: submission %s is not owned by user %s",
            submission_id,
            user_id,
        )
        return

    record = db.scalar(
        select(ReviewRecord).where(ReviewRecord.submission_id == submission_id)
    )
    if record is None:
        record = ReviewRecord(submission_id=submission_id)
        db.add(record)

    record.overall_score = review.overall_score
    record.correctness_score = review.correctness_score
    record.readability_score = review.readability_score
    record.efficiency_score = review.efficiency_score
    record.summary = review.summary
    # Stored as JSONB, so the nested models have to be plain dicts/lists.
    record.issues = [issue.model_dump() for issue in review.issues]
    record.suggestions = list(review.suggestions)
    record.complexity = review.complexity.model_dump()
    record.hint = review.hint
    record.improved_approach = review.improved_approach
    record.source = review.source

    db.commit()


@router.post("", response_model=ReviewResponse, summary="Review a submission")
async def create_review(
    request: ReviewRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ReviewResponse:
    """Review a run, and record the review when it belongs to a saved run.

    This is the one route that is ``async def``, because ``review_submission``
    awaits a multi-second network call to the provider and must not hold a
    worker thread while it does. The two database statements around it are a
    primary-key lookup and a small insert against a local Postgres - far too
    short to be worth pushing to a thread, and doing so would mean handing the
    ORM session across threads for no measurable gain.

    ``CurrentUser`` depends on ``get_db`` as well. FastAPI caches a dependency
    within a request, so both resolve to the *same* session - which is what
    makes ``user`` and ``db`` agree here.
    """
    problem = problem_data.get_problem(request.problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No problem with id {request.problem_id}.",
        )

    test_result = request.test_result.model_dump()

    try:
        payload = await review_submission(problem, request.code, test_result)
    except ReviewUnavailable as exc:
        # Log the real reason for the developer, but never leak provider
        # detail to the student.
        logger.warning("AI review unavailable: %s", exc)
        detail = UNAVAILABLE_MESSAGE
        if exc.retry_after:
            # A rate limit rather than a blip: telling the student how long to
            # wait beats sending them straight back to the same button, where
            # they would burn more of the quota and fail again.
            detail = f"{UNAVAILABLE_MESSAGE} Retry in about {exc.retry_after:.0f}s."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc

    try:
        review = validate_review(payload)
    except Exception as exc:  # noqa: BLE001 - defensive: never 500 on bad model output
        logger.exception("Review payload failed validation")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_MESSAGE,
        ) from exc

    # Recording the review is a side effect, and the review is the deliverable.
    # A write failure therefore must not take the feedback away from the
    # student - log it and return what the model produced.
    if request.submission_id is not None:
        try:
            _persist_review(db, request.submission_id, user.id, review)
        except Exception:  # noqa: BLE001 - the review outranks the record
            db.rollback()
            logger.exception(
                "Could not persist review for submission %s", request.submission_id
            )

    return review
