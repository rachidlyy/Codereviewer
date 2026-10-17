"""Saved-draft endpoints.

``GET /api/saved-code/{problem_id}?language=python``  - the student's draft
``PUT /api/saved-code/{problem_id}``                  - replace that draft

Phase 2's "saved code" is an auto-save, not a revision history: there is one
row per (user, problem, language) and every write replaces it. The unique
constraint on that triple is what actually enforces it, not the application
code below.

``language`` is part of the key because Phase 4's language selector makes two
drafts for one problem a normal thing to have. It is normalised through
``code_runner.resolve_language`` before it is used, so the client can send
``js`` without creating a second row alongside ``javascript``.

Both routes are plain ``def``, so FastAPI runs their blocking queries in a
worker thread - the same pattern the submission routes use.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data import problems as problem_data
from app.db import get_db
from app.deps import CurrentUser
from app.models.saved_code import SavedCode
from app.schemas.saved_code import SavedCodeIn, SavedCodeOut
from app.services.code_runner import UnsupportedLanguage, resolve_language

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/saved-code", tags=["saved code"])


def _require_problem(problem_id: int) -> dict:
    """The problem, or a 404 if it is not in the catalogue.

    Without this, a typo in the URL would quietly create an orphan row that
    nothing could ever read back.

    Returns the problem rather than ``None`` because both routes need it to
    validate the language - a draft for a language this problem does not offer
    is the same class of orphan.
    """
    problem = problem_data.get_problem(problem_id)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No problem with id {problem_id}.",
        )
    return problem


def _canonical(problem: dict, raw: str) -> str:
    """Normalise a requested language, or 400 with a readable reason."""
    try:
        return resolve_language(problem, raw)
    except UnsupportedLanguage as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _find(db: Session, user_id: int, problem_id: int, language: str) -> SavedCode | None:
    return db.scalar(
        select(SavedCode).where(
            SavedCode.user_id == user_id,
            SavedCode.problem_id == problem_id,
            SavedCode.language == language,
        )
    )


def _payload(problem_id: int, language: str, row: SavedCode | None) -> dict:
    if row is None:
        return {"problem_id": problem_id, "language": language, "code": None, "updated_at": None}
    return {
        "problem_id": problem_id,
        "language": row.language,
        "code": row.code,
        "updated_at": row.updated_at,
    }


@router.get(
    "/{problem_id}",
    response_model=SavedCodeOut,
    summary="Your draft for a problem",
)
def get_saved_code(
    problem_id: int,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    language: Annotated[str, Query(description="Canonical language id, e.g. 'python'.")] = "python",
) -> dict:
    problem = _require_problem(problem_id)
    canonical = _canonical(problem, language)
    return _payload(problem_id, canonical, _find(db, user.id, problem_id, canonical))


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
    problem = _require_problem(problem_id)
    language = _canonical(problem, payload.language)

    row = _find(db, user.id, problem_id, language)
    if row is None:
        row = SavedCode(user_id=user.id, problem_id=problem_id, language=language, code=payload.code)
        db.add(row)
    else:
        row.code = payload.code

    try:
        db.commit()
    except IntegrityError:
        # Two tabs saving the same problem and language at once can both miss
        # the SELECT above. The unique constraint is what really prevents a
        # duplicate, so losing this race is expected rather than a bug - take
        # over the winner's row instead of failing the save.
        db.rollback()
        row = _find(db, user.id, problem_id, language)
        if row is None:
            raise
        row.code = payload.code
        db.commit()

    # `updated_at` is a server-side default (and an onupdate), so it only
    # exists after a refresh. Cheap here, and the response quotes it back.
    db.refresh(row)
    return _payload(problem_id, language, row)
