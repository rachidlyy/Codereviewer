"""Pydantic models for the public API contract.

These mirror plan section 15 (API contract) and section 12 (AI output
format). Field names are snake_case on the wire because the frontend's
TypeScript types already use that convention.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["passed", "partial", "failed", "error", "timeout"]
ReviewSource = Literal["gemini", "heuristic"]


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


class ErrorResponse(BaseModel):
    detail: str
    context: dict[str, Any] | None = None
