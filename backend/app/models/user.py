"""User accounts.

Clerk owns identity: it stores the password, runs sign-in, and issues the
session token. This table is a *local mirror* of a Clerk user, and it exists
so the rest of the schema has a stable integer to point at instead of
repeating Clerk's string id on every row.

Rows are provisioned lazily - on the first authenticated request, from the
``sub`` claim. See :func:`app.deps.current_user`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:  # imported for annotations only - avoids a circular import
    from app.models.saved_code import SavedCode
    from app.models.submission import Submission


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Clerk's user id - a string like ``user_2abc...``, never an integer.
    #: Unique because one Clerk user must map to exactly one local row.
    clerk_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    #: Nullable on purpose. A Clerk session token carries ``sub`` and a few
    #: standard claims, but *not* the email address unless the application
    #: has a custom JWT template adding it. Treating this as required would
    #: make the very first sign-in fail. It can be backfilled later.
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(120))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    submissions: Mapped[list[Submission]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    saved_code: Mapped[list[SavedCode]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} clerk_user_id={self.clerk_user_id!r}>"
