"""Persisted code submissions.

Every call to ``POST /api/submissions/run`` writes one row here, which is what
makes submission history possible. Before Phase 2 the run endpoint was
stateless - it computed a result and threw it away.

``tests`` and ``error`` are stored as JSONB rather than as child tables. They
are always read back as a whole, never queried field-by-field, so normalising
them would add two tables and a join for no benefit.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:  # imported for annotations only - avoids a circular import
    from app.models.review import ReviewRecord
    from app.models.user import User


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Not nullable: sign-in is mandatory, so every submission has an owner.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    #: Deliberately NOT a foreign key. The problem catalogue lives in Python
    #: (``app.data.problems``), not in a table, so there is nothing to point
    #: at. Moving problems into the database was considered and rejected for
    #: this pass - see the Phase 2 notes in project memory.
    problem_id: Mapped[int] = mapped_column(Integer, index=True)

    language: Mapped[str] = mapped_column(String(32), default="python")
    code: Mapped[str] = mapped_column(Text)

    #: One of ``passed`` / ``partial`` / ``failed`` / ``error`` / ``timeout``,
    #: mirroring ``RunStatus`` in ``app.schemas.submission``.
    status: Mapped[str] = mapped_column(String(16))
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    execution_time: Mapped[float] = mapped_column(Float, default=0.0)

    #: The per-test-case results, as produced by ``code_runner``.
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    #: The friendly error object, when the run failed outright.
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(back_populates="submissions")
    #: At most one review per submission (``uselist=False``).
    review: Mapped[ReviewRecord | None] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Submission id={self.id} problem_id={self.problem_id} "
            f"{self.passed}/{self.total} {self.status}>"
        )
