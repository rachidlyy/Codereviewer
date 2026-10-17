"""The student's working draft for a problem.

Phase 2's "saved code" is an auto-save: one row per (user, problem, language),
replaced as the student edits or runs. It is what lets them close the tab and
come back to their work, and it is deliberately *not* a revision history - the
``UniqueConstraint`` below is what enforces "one draft per problem per
language".

``language`` is part of the key rather than a detail on the row because a
Python draft and a JavaScript draft for the same problem are different pieces
of work, not two versions of one. Without it, switching the language selector
would load the other language's code into the editor.

Submission history is a separate concern and lives in ``app.models.submission``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:  # imported for annotations only - avoids a circular import
    from app.models.user import User


class SavedCode(Base):
    __tablename__ = "saved_code"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "problem_id", "language", name="uq_saved_code_user_problem_language"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    #: Not a foreign key - the problem catalogue is Python data, not a table.
    #: See ``app.models.submission`` for the same note.
    problem_id: Mapped[int] = mapped_column(Integer, index=True)

    #: The canonical language id, not the alias the client may have sent -
    #: ``code_runner.resolve_language`` is what normalises it. A short column
    #: rather than an enum: the language list is still growing, and an enum
    #: would make each new runner a migration.
    language: Mapped[str] = mapped_column(String(20), server_default="python")

    code: Mapped[str] = mapped_column(Text, default="")

    #: Set on every upsert, so the UI can show "saved a moment ago".
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="saved_code")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SavedCode user_id={self.user_id} problem_id={self.problem_id} "
            f"language={self.language!r}>"
        )
