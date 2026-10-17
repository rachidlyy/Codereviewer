"""Authentication dependencies.

Clerk issues the session tokens. This module is the only place that verifies
them, and the only place that resolves a Clerk identity to a local ``User``
row. Routes depend on :data:`CurrentUser` and never touch Clerk directly.

Both dependencies are declared with ``def``, not ``async def``, on purpose.
``authenticate_request`` is synchronous and does network I/O (a JWKS fetch,
cached after the first call), and the session lookup is a blocking database
query. Declared as ``async def`` they would run on the event loop and stall
every concurrent request; declared as ``def``, FastAPI runs them in a worker
thread - the same pattern the existing submission routes already use.
"""

from __future__ import annotations

import logging
from typing import Annotated

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}
_REJECTED = "Could not validate your session. Please sign in again."


def clerk_session(request: Request) -> str:
    """Verify the bearer session token and return Clerk's user id.

    The user id is the token's ``sub`` claim - a string like ``user_2abc...``,
    never an integer.
    """
    if not config.auth_configured():
        # Deliberately 503 rather than 401. A 401 would send the student
        # hunting for a problem with their token when the real cause is a
        # missing server key, which no amount of signing in again will fix.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication is not configured on the server. "
                "Set CLERK_SECRET_KEY in backend/.env."
            ),
        )

    try:
        state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=config.CLERK_SECRET_KEY,
                authorized_parties=config.CLERK_AUTHORIZED_PARTIES,
            ),
        )
    except Exception:
        # A provider-side failure must not reach the student as a 500 with a
        # stack trace. Log the detail server-side and answer with a plain 401
        # so nothing about the key or the provider leaks into the response.
        logger.exception("Clerk token verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_REJECTED,
            headers=_UNAUTHORIZED_HEADERS,
        ) from None

    if not state.is_signed_in:
        # Clerk's own message is precise but written for developers - e.g.
        # "Please make sure that the __session cookie or the HTTP
        # authorization header contain a Clerk-generated session JWT".
        # Log that server-side for diagnosis, but answer with student-facing
        # copy, matching the friendly error text the run endpoint already
        # produces.
        logger.info("Rejected session token: %s", state.message)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_REJECTED,
            headers=_UNAUTHORIZED_HEADERS,
        )

    subject = (state.payload or {}).get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session token is missing a subject claim.",
            headers=_UNAUTHORIZED_HEADERS,
        )
    return subject


def current_user(
    clerk_user_id: Annotated[str, Depends(clerk_session)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the local ``User`` row for a verified Clerk identity.

    The row is provisioned on first sight rather than by a Clerk
    ``user.created`` webhook, because a webhook needs a publicly reachable
    URL and a localhost dev server does not have one.

    Tradeoff, accepted knowingly: a user deleted in Clerk leaves their local
    row behind. Nothing in this pass reads Clerk's user list, so that row is
    simply never reached again.
    """
    user = db.scalar(select(User).where(User.clerk_user_id == clerk_user_id))
    if user is not None:
        return user

    user = User(clerk_user_id=clerk_user_id)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent first requests can both miss the SELECT above. The
        # unique constraint on clerk_user_id is what actually prevents a
        # duplicate row, so losing this race is expected rather than a bug -
        # re-read the winner's row instead of failing the request.
        db.rollback()
        existing = db.scalar(select(User).where(User.clerk_user_id == clerk_user_id))
        if existing is None:
            raise
        return existing

    # Refresh so server-side defaults (``created_at``) are populated before
    # the route serialises this object.
    db.refresh(user)
    logger.info("Provisioned local user for Clerk id %s", clerk_user_id)
    return user


#: Convenience alias so routes read as ``user: CurrentUser``.
CurrentUser = Annotated[User, Depends(current_user)]
