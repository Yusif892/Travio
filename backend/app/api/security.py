from __future__ import annotations

import os
import secrets
from typing import Any

from app.planner.utils import get_value
from fastapi import Header, HTTPException

API_KEY_ENV = "TRAVIO_API_KEY"
REQUIRE_AUTH_ENV = "TRAVIO_REQUIRE_AUTH"
MAX_USER_ID_LENGTH = 128


def _require_auth() -> bool:
    return os.getenv(REQUIRE_AUTH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> str | None:
    """Authenticate the caller and return the optional user id.

    When TRAVIO_API_KEY is configured, every request must present it as
    ``X-API-Key`` or ``Authorization: Bearer <key>``. When
    TRAVIO_REQUIRE_AUTH is enabled, authentication and ``X-User-Id`` are mandatory.
    """

    expected = os.getenv(API_KEY_ENV, "").strip()
    require = _require_auth()
    provided = (x_api_key or "").strip() or _bearer_token(authorization)
    if expected:
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    elif require:
        raise HTTPException(status_code=401, detail="Authentication is not configured")

    user = (x_user_id or "").strip() or None
    if user is not None and len(user) > MAX_USER_ID_LENGTH:
        raise HTTPException(status_code=400, detail="X-User-Id is too long")
    if require and user is None:
        raise HTTPException(status_code=401, detail="X-User-Id is required")
    return user


def enforce_owner(state: Any, user: str | None) -> None:
    """Hide trips that belong to a different user."""

    owner = get_value(state, "owner_id", None) or get_value(state, "user_id", None)
    if owner is None:
        return
    if user is None or not secrets.compare_digest(str(owner), user):
        raise HTTPException(status_code=404, detail="Trip not found")
