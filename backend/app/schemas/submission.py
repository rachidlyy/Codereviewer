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


class LanguageSpec(BaseModel):
    """How one problem is attempted in one language.

    ``entrypoint`` is the function the harness calls, ``params``/``returns``
    are the declared signature (shown in the UI, and read by the driver
    generator for the compiled languages), and ``starter`` seeds the editor.
    """

    entrypoint: str
    params: list[str] = Field(default_factory=list)
    returns: str = ""
    starter: str = ""


class ProblemDetail(ProblemSummary):
    """Shape returned by ``GET /api/problems/{problem_id}``.

    Adds the per-language specs the coding workspace needs. It is a map
    rather than a flat ``starter``/``entrypoint`` pair because a problem can
    be attempted in more than one language, and a client asking for a problem
    should learn what is available without a second request.

    Test cases and expected values are deliberately absent - the client is
    told what to solve, never how it is checked.
    """

    languages: dict[str, LanguageSpec]


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
    #: ``repr`` of what the student's code returned, and of what was expected.
    #: Strings rather than values so a huge or unserialisable return cannot
    #: break the response - and so the UI renders one shape for every case.
    actual: str | None = None
    expected: str | None = None
    #: Wall-clock seconds this case took, including process startup. The total
    #: on ``RunResponse`` is the sum; this is what makes "which case is slow?"
    #: answerable.
    elapsed: float = 0.0
    #: Seconds spent inside the student's own code, excluding interpreter
    #: startup. On Windows startup costs ~0.9s - about a thousand times what a
    #: typical solution does - so ``elapsed`` alone is a measure of overhead,
    #: not of the algorithm. This is the number the complexity analysis
    #: compares across input sizes.
    compute: float = 0.0
    #: Anything the student printed. Captured per case so output lands next to
    #: the test that produced it rather than in one undifferentiated blob.
    stdout: str | None = None
    #: True when the output was cut short. The harness stops buffering at 4000
    #: characters rather than accumulating a runaway print loop in memory, so
    #: a truncated answer means "you printed a lot", not "something broke".
    stdout_truncated: bool = False

    # --- Phase 3 ---------------------------------------------------------
    #: Structured twins of ``actual``/``expected``, sent as real JSON so the UI
    #: can say *which index* differs instead of printing two blobs of text.
    #: ``None`` when the value is too large or not JSON-representable, in which
    #: case the UI falls back to the reprs above - which are always present.
    actual_value: Any | None = None
    expected_value: Any | None = None
    #: How the case's child process ended. A clean exit sets ``exit_code`` and
    #: leaves ``signal`` null; a killed child does the reverse.
    exit_code: int | None = None
    signal: int | None = None
    #: True when the kernel's OOM killer ended this case, taken from the
    #: container's own cgroup counter. ``None`` means the backend cannot
    #: report it at all - the host runner has no cgroup - which is deliberately
    #: distinct from ``False``, meaning "we looked and it did not happen".
    oom_killed: bool | None = None


class SandboxInfo(BaseModel):
    """What the execution sandbox did, as opposed to what the code did.

    Only the container backend can fill this in, so it is ``None`` for the
    host runner. It exists so an out-of-memory failure can be explained with
    numbers - "your program reached the 512 MB ceiling" - rather than a bare
    SIGKILL that tells the student nothing actionable.
    """

    #: The container's memory ceiling, in bytes.
    memory_limit_bytes: int | None = None
    #: The container's high-water mark across the whole submission, in bytes.
    #: A per-submission figure rather than a per-case one: cgroup v2's
    #: ``memory.peak`` is monotonic and cannot be reset without root.
    memory_peak_bytes: int | None = None
    #: True when the OOM killer fired at least once during the submission.
    oom_killed: bool = False


class RunError(BaseModel):
    #: ``syntax`` | ``compile`` | ``runtime`` | ``timeout``. ``compile`` is
    #: unused until the Java and C++ harnesses land, but the vocabulary is
    #: declared here so the frontend has one place to switch on.
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

    #: Phase 3: submission-level sandbox facts. ``None`` for the host backend,
    #: which has no container and therefore no memory ceiling to report.
    sandbox: SandboxInfo | None = None


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

    # --- Phase 2, execution sandbox --------------------------------------
    # Student code runs in a container unless RUNNER_BACKEND says otherwise.
    # These fields exist so the two silent-downgrade scenarios are visible
    # from one request: Docker is down (runs will fail), or the backend has
    # been switched to the unsandboxed host runner (runs will succeed, but
    # student code is no longer isolated).
    #: "docker" or "subprocess".
    runner_backend: str = "docker"
    #: The container image a run will use. Only meaningful for the docker backend.
    runner_image: str | None = None
    #: True when the Docker daemon answered. Always False for the subprocess backend.
    docker_ok: bool = False
    #: The daemon's error text when the probe fails. Only populated on failure.
    docker_error: str | None = None


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
