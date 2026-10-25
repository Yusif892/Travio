from __future__ import annotations

import re
import time
from dataclasses import dataclass
from threading import Lock

from app.feedback.models import FeedbackResult

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def validate_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip()
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must be 1-128 characters of [A-Za-z0-9._:-]",
        )
    return key


@dataclass(slots=True)
class _Entry:
    result: FeedbackResult
    expires_at: float


class IdempotencyStore:
    """In-memory replay cache for feedback requests.

    This is process-local. A shared cache (for example Redis or PostgreSQL) is
    required when the API runs with multiple workers.
    """

    def __init__(self, max_entries: int = 256, ttl_seconds: float = 3600.0) -> None:
        self._max_entries = max(int(max_entries), 1)
        self._ttl_seconds = max(float(ttl_seconds), 0.0)
        self._entries: dict[str, _Entry] = {}
        self._lock = Lock()

    def get(self, key: str) -> FeedbackResult | None:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            entry = self._entries.get(key)
            if entry is None:
                return None
            return entry.result.model_copy(deep=True)

    def put(self, key: str, result: FeedbackResult) -> None:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest, None)
            self._entries[key] = _Entry(
                result=result.model_copy(deep=True),
                expires_at=now + self._ttl_seconds,
            )

    def _purge(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


_STORE = IdempotencyStore()


def get_idempotency_store() -> IdempotencyStore:
    return _STORE


def idempotency_cache_key(user: str | None, trip_id: str, key: str) -> str:
    return f"{user or 'anonymous'}:{trip_id}:{key}"
