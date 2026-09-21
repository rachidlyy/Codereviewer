"""Persisted AI reviews.

A review is attached to the submission it describes, and there is at most one
per submission. That is enforced structurally by ``submission_id`` being
unique, rather than by application code - the review endpoint is idempotent
for a given submission, so a retry should replace rather than duplicate.

The scored fields mirror ``ReviewResponse`` in ``app.schemas.submission``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:  # imported for annotations only - avoids a circular import
    from app.models.submission import Submission


class ReviewRecord(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Unique, not merely indexed: one review per submission.
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), unique=True, index=True
    )

    overall_score: Mapped[float] = mapped_column(Float)
    correctness_score: Mapped[float] = mapped_column(Float, default=0.0)
    readability_score: Mapped[float] = mapped_column(Float, default=0.0)
    efficiency_score: Mapped[float] = mapped_column(Float, default=0.0)

    summary: Mapped[str] = mapped_column(Text, default="")

    #: ``list[ReviewIssue]`` - read as a whole, so JSONB rather than a table.
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    suggestions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    #: ``ReviewComplexity`` - four short strings.
    complexity: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    hint: Mapped[str] = mapped_column(Text, default="")
    improved_approach: Mapped[str] = mapped_column(Text, default="")

    #: Which reviewer produced this: ``gemini``, ``groq`` or ``heuristic``.
    #: Worth persisting - it is how a student's history can show that a
    #: review came from the offline rule-based fallback.
    source: Mapped[str] = mapped_column(String(16), default="heuristic")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    submission: Mapped[Submission] = relationship(back_populates="review")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ReviewRecord id={self.id} submission_id={self.submission_id} "
            f"score={self.overall_score} source={self.source}>"
        )
