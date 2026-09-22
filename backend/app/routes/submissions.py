"""Submission endpoints: run code, then read back what was run.

``POST /api/submissions/run``  - execute code and record the result
``GET  /api/submissions``      - the student's history, newest first
``GET  /api/submissions/{id}`` - one recorded run, with its review

Every route here is declared with plain ``def`` rather than ``async def``.
``run_submission`` spawns subprocesses and the ORM calls block, so as
``async def`` these handlers would run both on the event loop. FastAPI runs
``def`` handlers in a worker thread, which is what we want.

Phase 2 made these routes authenticated. Sign-in is mandatory and
``submissions.user_id`` is NOT NULL, so an anonymous run has nowhere to be
recorded - and a run that cannot be recorded is a run the student loses.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.data import problems as problem_data
from app.db import get_db
from app.deps import CurrentUser
from app.models.review import ReviewRecord
from app.models.submission import Submission
from app.schemas.submission import (
    RunRequest,
    RunResponse,
    SubmissionDetail,
    SubmissionSummary,
)
from app.services.code_runner import UnsupportedLanguage, resolve_language, run_submission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


def _problem_meta(problem_id: int) -> tuple[str, str]:
    """Title and difficulty for a stored ``problem_id``.

    The catalogue is Python data rather than a table (see
    ``app.models.submission``), so it can change underneath a stored row. A run
    whose problem has since left the catalogue still belongs in the student's
    history - it simply cannot be named. Falling back keeps the list readable
    instead of failing the whole request over one stale row.
    """
    problem = problem_data.get_problem(problem_id)
    if problem is None:
        return f"Problem {problem_id}", "Unknown"
    return problem["title"], problem["difficulty"]


def _review_payload(record: ReviewRecord | None) -> dict | None:
    """Reshape a stored review into the API's ``ReviewResponse``.

    Pydantic fills any gap from the model's own defaults, so a review written
    by an older version of the schema still serialises.
    """
    if record is None:
        return None
    return {
        "overall_score": record.overall_score,
        "correctness_score": record.correctness_score,
        "readability_score": record.readability_score,
        "efficiency_score": record.efficiency_score,
        "summary": record.summary,
        "issues": record.issues,
        "suggestions": record.suggestions,
        "complexity": record.complexity,
        "hint": record.hint,
        "improved_approach": record.improved_approach,
        "source": record.source,
    }


def _to_summary(row: Submission) -> dict:
    """Project a stored submission onto ``SubmissionSummary``."""
    title, difficulty = _problem_meta(row.problem_id)
    review = row.review
    return {
        "id": row.id,
        "problem_id": row.problem_id,
        "problem_title": title,
        "problem_difficulty": difficulty,
        "status": row.status,
        "passed": row.passed,
        "total": row.total,
        "execution_time": row.execution_time,
        "created_at": row.created_at,
        "overall_score": review.overall_score if review else None,
        "review_source": review.source if review else None,
    }


@router.post("/run", response_model=RunResponse, summary="Run code against test cases")
def run_code(
    request: RunRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    problem = problem_data.get_problem(request.problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No problem with id {request.problem_id}.",
        )

    # Validation lives with the runner, which is the only thing that knows
    # what it can execute; the route just translates the refusal into HTTP.
    # Two distinct refusals are possible: a language the runner cannot run at
    # all, and one it can run but this problem does not offer.
    try:
        language = resolve_language(problem, request.language)
    except UnsupportedLanguage as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    result = run_submission(problem, request.code, language)

    # Persist, but never at the cost of the run itself. Execution is the whole
    # point of this endpoint and history is only a record *of* it, so a failed
    # write must not turn a successful run into a 500 the student can do
    # nothing about. The failure is logged loudly and ``submission_id`` comes
    # back None, which the review endpoint already tolerates.
    submission_id: int | None = None
    try:
        record = Submission(
            user_id=user.id,
            problem_id=problem["id"],
            language=language,
            code=request.code,
            status=result["status"],
            passed=result["passed"],
            total=result["total"],
            execution_time=result["execution_time"],
            tests=result["tests"],
            error=result["error"],
        )
        db.add(record)
        db.commit()
        # `created_at` is a server-side default, so it only exists after a
        # refresh. Cheap here, and it keeps the object safe to serialise.
        db.refresh(record)
        submission_id = record.id
    except Exception:  # noqa: BLE001 - the run result outranks the record
        db.rollback()
        logger.exception(
            "Could not persist submission for user %s on problem %s",
            user.id,
            request.problem_id,
        )

    return {**result, "submission_id": submission_id}


@router.get("", response_model=list[SubmissionSummary], summary="List your submissions")
def list_submissions(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    problem_id: Annotated[int | None, Query(description="Only this problem")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    """The student's own runs, newest first.

    Scoped to ``user.id`` inside the query rather than filtered afterwards, so
    another student's rows are never loaded in the first place.
    """
    statement = (
        select(Submission)
        # `selectinload` rather than a lazy load: `_to_summary` reads
        # `row.review`, and doing that per row would be one query per
        # submission.
        .options(selectinload(Submission.review))
        .where(Submission.user_id == user.id)
        # `created_at` is `now()`, which two runs inside one transaction can
        # share. `id` breaks the tie, so the order is never ambiguous.
        .order_by(Submission.created_at.desc(), Submission.id.desc())
        .limit(limit)
    )
    if problem_id is not None:
        statement = statement.where(Submission.problem_id == problem_id)

    return [_to_summary(row) for row in db.scalars(statement).all()]


@router.get(
    "/{submission_id}",
    response_model=SubmissionDetail,
    summary="Get one submission",
)
def get_submission(
    submission_id: int,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    row = db.scalar(
        select(Submission)
        .options(selectinload(Submission.review))
        .where(Submission.id == submission_id, Submission.user_id == user.id)
    )
    if row is None:
        # 404 rather than 403 when the id belongs to someone else: whether
        # another student's submission exists is not this student's business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No submission with id {submission_id}.",
        )

    return {
        **_to_summary(row),
        "language": row.language,
        "code": row.code,
        "tests": row.tests,
        "error": row.error,
        "review": _review_payload(row.review),
    }
