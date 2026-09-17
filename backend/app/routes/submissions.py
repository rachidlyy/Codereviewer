"""Code execution endpoint.

``POST /api/submissions/run`` executes the submitted code against the
problem's predefined test cases and returns a structured result.

The route stays thin: it validates the request and delegates all execution
concerns to :mod:`app.services.code_runner`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.data import problems as problem_data
from app.schemas.submission import RunRequest, RunResponse
from app.services.code_runner import SUPPORTED_LANGUAGES, run_submission

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.post("/run", response_model=RunResponse, summary="Run code against test cases")
def run_code(request: RunRequest) -> dict:
    problem = problem_data.get_problem(request.problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No problem with id {request.problem_id}.",
        )

    language = (request.language or "python").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported language '{request.language}'. "
                "This MVP supports Python only."
            ),
        )

    # `run_submission` is synchronous and spawns subprocesses. Declaring this
    # route with `def` (not `async def`) lets FastAPI run it in a worker
    # thread so the event loop is never blocked.
    return run_submission(problem, request.code)
