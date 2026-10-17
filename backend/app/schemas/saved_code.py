"""Pydantic models for the saved-draft endpoints.

Mirrors ``app.models.saved_code``. A draft is one row per (user, problem,
language) and each write replaces it - there is no revision history here.

``language`` is part of the draft's identity, not a label on it: a Python draft
and a JavaScript draft for the same problem are separate pieces of work. Phase
4's language selector is what made that necessary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

#: Upper bound on a draft, in characters. Generous for anything a student would
#: type, but it stops a runaway client from writing an unbounded blob into the
#: database.
MAX_DRAFT_CHARS = 100_000


class SavedCodeIn(BaseModel):
    """Body of ``PUT /api/saved-code/{problem_id}``.

    ``language`` defaults to Python so the endpoint stays backward compatible
    with a client that does not send it. It is normalised through
    ``code_runner.resolve_language`` before it reaches the database, which is
    what makes ``js`` and ``node`` land on the same row as ``javascript``
    rather than creating three.
    """

    code: str = Field(default="", max_length=MAX_DRAFT_CHARS)
    language: str = "python"


class SavedCodeOut(BaseModel):
    """Shape returned by both saved-draft endpoints.

    ``code`` and ``updated_at`` are optional because "nothing saved yet" is a
    normal state rather than an error - it is where every problem starts. The
    alternative, answering 404, would force the workspace to treat the ordinary
    case as a failure and swallow it, which is exactly the kind of thing that
    hides a real bug later.
    """

    problem_id: int
    language: str | None = None
    code: str | None = None
    updated_at: datetime | None = None
