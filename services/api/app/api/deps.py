from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Query, Request
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.security.roles import ROLE_ADMIN, attach_effective_role


def get_request_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not isinstance(user, User):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(
    user: User = Depends(get_request_user), db: Session = Depends(get_db)
) -> User:
    eff = attach_effective_role(db, user)
    if eff != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# PostgreSQL integer columns hold at most this; a larger value bound to one is
# a database error, so every identifier and number a route reads is bounded
# here and refused as a validation error instead.
DB_INT_MAX = 2**31 - 1
DbId = Annotated[int, Path(ge=1, le=DB_INT_MAX)]
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
OptionalDbId = Annotated[int | None, Query(ge=1, le=DB_INT_MAX)]
