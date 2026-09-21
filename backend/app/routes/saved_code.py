"""Saved-draft endpoints.

``GET /api/saved-code/{problem_id}``  - the student's draft for one problem
``PUT /api/saved-code/{problem_id}``  - replace that draft

Phase 2's "saved code" is an auto-save, not a revision history: there is one
row per (user, problem) and every write replaces it. The unique constraint on
that pair is what actually enforces it, not the application code below.

Both routes are plain ``def``, so FastAPI runs their blocking queries in a
worker thread - the same pattern the submission routes use.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data import problems as problem_data
from app.db import get_db
from app.deps import CurrentUser
from app.models.saved_code import SavedCode
from app.schemas.saved_code import SavedCodeIn, SavedCodeOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/saved-code", tags=["saved code"])


def _require_problem(problem_id: int) -> None:
    """Reject a draft for a problem that is not in the catalogue.

    Without this, a typo in the URL would quietly create an orphan row that
    nothing could ever read back.
    """
    if not problem_data.problem_exists(problem_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No problem with id {problem_id}.",
        )


def _find(db: Session, user_id: int, problem_id: int) -> SavedCode | None:
    return db.scalar(
        select(SavedCode).where(
            SavedCode.user_id == user_id,
            SavedCode.problem_id == problem_id,
        )
    )


def _payload(problem_id: int, row: SavedCode | None) -> dict:
    if row is None:
        return {"problem_id": problem_id, "code": None, "updated_at": None}
    return {"problem_id": problem_id, "code": row.code, "updated_at": row.updated_at}


@router.get(
    "/{problem_id}",
    response_model=SavedCodeOut,
    summary="Your draft for a problem",
)
def get_saved_code(
    problem_id: int,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _require_problem(problem_id)
    return _payload(problem_id, _find(db, user.id, problem_id))


@router.put(
    "/{problem_id}",
    response_model=SavedCodeOut,
    summary="Save your draft",
)
def put_saved_code(
    problem_id: int,
    payload: SavedCodeIn,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _require_problem(problem_id)

    row = _find(db, user.id, problem_id)
    if row is None:
        row = SavedCode(user_id=user.id, problem_id=problem_id, code=payload.code)
        db.add(row)
    else:
        row.code = payload.code

    try:
        db.commit()
    except IntegrityError:
        # Two tabs saving the same problem at once can both miss the SELECT
        # above. The unique constraint is what really prevents a duplicate, so
        # losing this race is expected rather than a bug - take over the
        # winner's row instead of failing the save.
        db.rollback()
        row = _find(db, user.id, problem_id)
        if row is None:
            raise
        row.code = payload.code
        db.commit()

    # `updated_at` is a server-side default (and an onupdate), so it only
    # exists after a refresh. Cheap here, and the response quotes it back.
    db.refresh(row)
    return _payload(problem_id, row)
