"""Authentication endpoints.

Deliberately tiny. Clerk owns sign-up, sign-in and password storage through
its own hosted components, so there is no ``/register`` or ``/login`` route
here and no password ever reaches this server. The backend's only job is to
verify the session token Clerk issued and say who the caller is.

The verification itself lives in :mod:`app.deps`; this route just returns the
resolved user.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUser
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=UserOut,
    summary="Return the signed-in user",
)
def me(user: CurrentUser) -> UserOut:
    """Return the local user row for the caller's Clerk session.

    Also the frontend's probe for "is my token still good?" - a 401 here means
    the client should sign the user out rather than retry.
    """
    return UserOut.model_validate(user, from_attributes=True)
