"""Auth-related API contract.

Kept separate from ``schemas/submission.py`` because these shapes describe
identity rather than the problem/run/review workflow. The frontend mirror
lives in ``frontend/src/types/index.ts`` and must be kept in step.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UserOut(BaseModel):
    """Shape returned by ``GET /api/auth/me``.

    ``email`` and ``display_name`` are optional because a Clerk session token
    carries the ``sub`` claim but not the profile fields unless the Clerk
    application defines a custom JWT template that adds them. The UI must
    therefore treat a missing display name as normal and fall back to
    something generic.
    """

    id: int
    clerk_user_id: str
    email: str | None = None
    display_name: str | None = None
    created_at: datetime
