"""Problem catalogue endpoints.

``GET /api/problems``       - list every problem
``GET /api/problems/{id}``  - one problem, including its per-language starter code
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.data import problems as problem_data
from app.schemas.submission import ProblemDetail, ProblemSummary

router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("", response_model=list[ProblemSummary], summary="List all problems")
def list_problems() -> list[dict]:
    return [problem_data.to_public(problem) for problem in problem_data.list_problems()]


@router.get("/{problem_id}", response_model=ProblemDetail, summary="Get one problem")
def get_problem(problem_id: int) -> dict:
    problem = problem_data.get_problem(problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No problem with id {problem_id}.",
        )
    # The detail view additionally exposes the per-language specs: the starter
    # code the editor is seeded with, and the signature the runner calls.
    return problem_data.to_public(problem, include_languages=True)
