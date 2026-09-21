"""Pydantic models for the public API contract.

These mirror plan section 15 (API contract) and section 12 (AI output
format). Field names are snake_case on the wire because the frontend's
TypeScript types already use that convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["passed", "partial", "failed", "error", "timeout"]
#: ``gemini`` is the primary reviewer, ``groq`` the fallback used when Gemini
#: exhausts its retries, and ``heuristic`` the offline rule-based reviewer.
ReviewSource = Literal["gemini", "groq", "heuristic"]


# --- Problems -------------------------------------------------------------


class ExampleOut(BaseModel):
    input: str
    output: str


class ProblemSummary(BaseModel):
    """Shape returned by ``GET /api/problems``."""

    id: int
    title: str
    difficulty: str
    category: str
    description: str
    examples: list[ExampleOut]
    tags: list[str]


class ProblemDetail(ProblemSummary):
    """Shape returned by ``GET /api/problems/{problem_id}``.

    Adds the starter code the editor should be seeded with, plus the name
    of the function that will be called during testing.
    """

    starter: str
    entrypoint: str


# --- Submissions ----------------------------------------------------------


class RunRequest(BaseModel):
    problem_id: int
    language: str = "python"
    code: str = Field(min_length=0)


class TestCaseResult(BaseModel):
    index: int
    name: str
    passed: bool
    error_type: str | None = None
    message: str | None = None
    actual: str | None = None
    expected: str | None = None


class RunError(BaseModel):
    type: str
    title: str
    message: str
    line: int | None = None
    detail: str | None = None


class RunResponse(BaseModel):
    status: RunStatus
    passed: int
    total: int
    execution_time: float
    tests: list[TestCaseResult]
    error: RunError | None = None

    #: Phase 2: the id of the ``submissions`` row this run was saved as, so the
    #: review request can be attached to the exact run it describes. ``None``
    #: means persistence itself failed - the run result is still valid, and a
    #: student must never lose a run because the history write went wrong.
    submission_id: int | None = None


# --- Reviews --------------------------------------------------------------


class TestResultSummary(BaseModel):
    """The subset of a run result the reviewer needs."""

    passed: int = 0
    total: int = 0
    execution_time: float = 0.0
    status: RunStatus | None = None
    failed_tests: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    problem_id: int
    code: str
    test_result: TestResultSummary = Field(default_factory=TestResultSummary)

    #: Which run this review describes. Optional so the endpoint still works
    #: standalone (from /docs, say); when present the review is persisted and
    #: therefore shows up in the student's history.
    submission_id: int | None = None


class ReviewIssue(BaseModel):
    type: str
    title: str
    explanation: str


class ReviewComplexity(BaseModel):
    current_time: str = "—"
    current_space: str = "—"
    suggested_time: str = "—"
    suggested_space: str = "—"


class ReviewResponse(BaseModel):
    """Structured review - see plan section 12.

    ``improved_approach`` is an additive extension so the UI can offer the
    "View Improved Approach" button without the student being shown a full
    solution up front.
    """

    overall_score: float
    correctness_score: float
    readability_score: float
    efficiency_score: float
    summary: str
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    complexity: ReviewComplexity = Field(default_factory=ReviewComplexity)
    hint: str = ""
    improved_approach: str = ""

    #: Which reviewer produced this result. ``heuristic`` means the LLM was
    #: not configured, so the feedback is rule-based.
    source: ReviewSource = "heuristic"


class HealthResponse(BaseModel):
    status: str
    llm_configured: bool
    llm_model: str | None = None
    problems: int

    # --- Phase 2 ---------------------------------------------------------
    # Sign-in is mandatory, so the database is now load-bearing rather than
    # optional. These fields make a misconfigured DATABASE_URL or a stopped
    # Postgres service visible from the health probe instead of surfacing as
    # a confusing 500 on the first authenticated request.
    database_configured: bool = False
    database_ok: bool = False
    #: The driver's error text when the ping fails. Only populated on failure.
    database_error: str | None = None
    #: True when a Clerk secret key is present.
    auth_configured: bool = False


class ErrorResponse(BaseModel):
    detail: str
    context: dict[str, Any] | None = None


# --- History and progress -------------------------------------------------
#
# These read back what ``POST /api/submissions/run`` and ``POST /api/reviews``
# persist. They sit at the end of the module because ``SubmissionDetail``
# embeds ``ReviewResponse``, which is defined above.


class SubmissionSummary(BaseModel):
    """One row of ``GET /api/submissions``.

    Flat on purpose: the history list shows a problem title and a score, and
    carrying the title here saves the client from holding the whole catalogue
    just to render a list.
    """

    id: int
    problem_id: int
    problem_title: str
    problem_difficulty: str
    status: RunStatus
    passed: int
    total: int
    execution_time: float
    created_at: datetime

    #: From the attached review, when one exists. ``None`` means the student
    #: ran the code but never asked for a review - which is a normal state,
    #: not an error.
    overall_score: float | None = None
    review_source: ReviewSource | None = None


class SubmissionDetail(SubmissionSummary):
    """``GET /api/submissions/{id}`` - enough to replay the run in full."""

    language: str
    code: str
    tests: list[TestCaseResult] = Field(default_factory=list)
    error: RunError | None = None
    review: ReviewResponse | None = None


class ProblemProgress(BaseModel):
    """One problem's row on the dashboard - attempted or not.

    Unattempted problems are included deliberately: they are what the home
    page offers as "next", so omitting them would leave the dashboard with
    nothing to say to a new student.
    """

    problem_id: int
    title: str
    difficulty: str
    attempted: bool = False
    #: True once any single run passed every test case.
    solved: bool = False
    attempts: int = 0
    #: How many test cases the problem has, from the catalogue.
    total_tests: int = 0
    #: Best single run, so a partial attempt still shows real progress.
    best_passed: int = 0
    best_score: float | None = None
    last_attempt_at: datetime | None = None


class ProgressResponse(BaseModel):
    """``GET /api/progress`` - the whole home dashboard in one request."""

    total_problems: int
    attempted_problems: int
    solved_problems: int
    total_submissions: int
    #: Mean of every review the student has, or ``None`` before their first.
    average_score: float | None = None
    problems: list[ProblemProgress] = Field(default_factory=list)
