"""Progress endpoint.

``GET /api/progress`` is the home dashboard in a single request: overall counts
plus one row per problem in the **whole** catalogue. Sending unattempted
problems too is deliberate - it is what lets the dashboard answer "what should
I do next?", which a summary of the past alone cannot.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.data import problems as problem_data
from app.data import test_cases as test_case_data
from app.db import get_db
from app.deps import CurrentUser
from app.models.review import ReviewRecord
from app.models.submission import Submission
from app.schemas.submission import ProgressResponse

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get(
    "",
    response_model=ProgressResponse,
    summary="Your progress across the catalogue",
)
def get_progress(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    # Two aggregate queries for the whole history, rather than one query per
    # problem. The catalogue is only five problems today, but a dashboard's
    # query count should not scale with the size of the thing it summarises.
    aggregates = db.execute(
        select(
            Submission.problem_id,
            func.count(Submission.id).label("attempts"),
            func.max(Submission.passed).label("best_passed"),
            func.max(Submission.created_at).label("last_attempt_at"),
            # `sum(case(...))` rather than Postgres' `bool_or` so this stays
            # portable if the database ever changes.
            func.sum(case((Submission.status == "passed", 1), else_=0)).label(
                "passing_runs"
            ),
        )
        .where(Submission.user_id == user.id)
        .group_by(Submission.problem_id)
    ).all()

    by_problem = {row.problem_id: row for row in aggregates}

    # Best review score per problem. A separate query because it joins through
    # submissions; folding it into the aggregate above would need a second
    # join and a DISTINCT, and would count runs twice.
    best_scores = dict(
        db.execute(
            select(Submission.problem_id, func.max(ReviewRecord.overall_score))
            .join(ReviewRecord, ReviewRecord.submission_id == Submission.id)
            .where(Submission.user_id == user.id)
            .group_by(Submission.problem_id)
        ).all()
    )

    problems = []
    for problem in problem_data.list_problems():
        problem_id = problem["id"]
        row = by_problem.get(problem_id)
        problems.append(
            {
                "problem_id": problem_id,
                "title": problem["title"],
                "difficulty": problem["difficulty"],
                "attempted": row is not None,
                # A problem counts as solved once *any* run passed everything,
                # so a later failed attempt does not un-solve it.
                "solved": bool(row is not None and row.passing_runs),
                "attempts": row.attempts if row is not None else 0,
                "total_tests": len(test_case_data.get_test_cases(problem_id)),
                "best_passed": row.best_passed if row is not None else 0,
                "best_score": best_scores.get(problem_id),
                "last_attempt_at": row.last_attempt_at if row is not None else None,
            }
        )

    # Mean score across every review, not the mean of the per-problem bests -
    # the latter would over-weight a problem the student reviewed once.
    average_score = db.scalar(
        select(func.avg(ReviewRecord.overall_score))
        .join(Submission, Submission.id == ReviewRecord.submission_id)
        .where(Submission.user_id == user.id)
    )

    return {
        "total_problems": len(problems),
        "attempted_problems": sum(1 for problem in problems if problem["attempted"]),
        "solved_problems": sum(1 for problem in problems if problem["solved"]),
        "total_submissions": sum(row.attempts for row in aggregates),
        "average_score": average_score,
        "problems": problems,
    }
