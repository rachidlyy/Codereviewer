"""AI review endpoint.

``POST /api/reviews`` turns a submission plus its execution results into a
structured, educational review.

Following plan section 11 the route only validates and delegates - every
piece of LLM logic lives in :mod:`app.services.ai_reviewer`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.data import problems as problem_data
from app.schemas.submission import ReviewRequest, ReviewResponse
from app.services.ai_reviewer import ReviewUnavailable, review_submission, validate_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

#: Copy shown when the configured model cannot be reached (plan section 16).
#: The student stays on the coding page and can simply try again.
UNAVAILABLE_MESSAGE = "AI Review temporarily unavailable. Please try again."


@router.post("", response_model=ReviewResponse, summary="Review a submission")
async def create_review(request: ReviewRequest) -> ReviewResponse:
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
        return validate_review(payload)
    except Exception as exc:  # noqa: BLE001 - defensive: never 500 on bad model output
        logger.exception("Review payload failed validation")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_MESSAGE,
        ) from exc
