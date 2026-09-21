"""ORM models.

Importing this package is what registers every table on ``Base.metadata``.
That is why the imports below are re-exported rather than left to the caller:
Alembic's ``env.py`` does a single ``import app.models`` and expects the full
schema to be present afterwards. A model that is never imported is invisible
to autogenerate, and the resulting migration silently omits its table.
"""

from __future__ import annotations

from app.models.review import ReviewRecord
from app.models.saved_code import SavedCode
from app.models.submission import Submission
from app.models.user import User

__all__ = ["ReviewRecord", "SavedCode", "Submission", "User"]
