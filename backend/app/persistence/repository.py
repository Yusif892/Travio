"""PostgreSQL repositories for trips and itinerary versions.

* ``PostgresTripStore``      – drop-in for ``InMemoryTripStore`` (create/get/save).
* ``PostgresTripRepository`` – the interface ``app.api.deps`` imports
  (``load_state`` / ``save_itinerary``) for the itinerary and feedback API.

Every query is filtered by owner, so one user can never read or overwrite
another user's trip.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.domain.schemas import TripRecord
from app.persistence import codec
from app.persistence.db import get_pool


class TripNotFoundError(LookupError):
    """The trip does not exist (or is not owned by the caller)."""


class ItineraryConflictError(RuntimeError):
    """A saved itinerary version would be overwritten or rolled back."""


_JSON_COLUMNS = ("trip_request", "messages", "tasks", "transport_options", "lodging_options",
                 "experience_options", "verification", "itinerary", "errors")


def _adapt(params: dict[str, Any]) -> dict[str, Any]:
    adapted = dict(params)
    for name in _JSON_COLUMNS:
        if adapted[name] is not None:  # None stays SQL NULL
            adapted[name] = Jsonb(adapted[name])
    return adapted


def _parse_uuid(value: str | UUID) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


class _PoolMixin:
    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self._pool = pool

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor]:
        """One transaction: commits on success, rolls back on any error."""
        with (self._pool or get_pool()).connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                yield cur


_INSERT = """
insert into trips (trip_id, thread_id, user_id, origin, destination, departure_date, return_date,
                   budget, travelers, trip_request, messages, tasks, transport_options,
                   lodging_options, experience_options, verification, itinerary, errors)
values (%(trip_id)s, %(thread_id)s, %(user_id)s, %(origin)s, %(destination)s, %(departure_date)s,
        %(return_date)s, %(budget)s, %(travelers)s, %(trip_request)s, %(messages)s, %(tasks)s,
        %(transport_options)s, %(lodging_options)s, %(experience_options)s, %(verification)s,
        %(itinerary)s, %(errors)s)
"""

_UPDATE = """
update trips set origin = %(origin)s, destination = %(destination)s,
       departure_date = %(departure_date)s, return_date = %(return_date)s,
       budget = %(budget)s, travelers = %(travelers)s, trip_request = %(trip_request)s,
       messages = %(messages)s, tasks = %(tasks)s, transport_options = %(transport_options)s,
       lodging_options = %(lodging_options)s, experience_options = %(experience_options)s,
       verification = %(verification)s, errors = %(errors)s
 where trip_id = %(trip_id)s and user_id = %(user_id)s
"""


class PostgresTripStore(_PoolMixin):
    """Same interface as ``app.services.store.InMemoryTripStore``."""

    def create(self, record: TripRecord) -> TripRecord:
        with self._cursor() as cur:
            cur.execute(_INSERT, _adapt(codec.record_to_params(record)))
        return record

    def get(self, trip_id: UUID, user_id: str | None = None) -> TripRecord | None:
        with self._cursor() as cur:
            cur.execute("select * from trips where trip_id = %s and user_id = %s",
                        (trip_id, codec.owner_of(user_id)))
            row = cur.fetchone()
        return codec.row_to_record(row) if row else None

    def save(self, record: TripRecord) -> TripRecord:
        """Update an existing trip. The itinerary column is NOT written here: it is owned by
        ``PostgresTripRepository.save_itinerary`` so a stale TripRecord can never roll it back."""
        with self._cursor() as cur:
            cur.execute(_UPDATE, _adapt(codec.record_to_params(record)))
            if cur.rowcount == 0:
                raise TripNotFoundError(str(record.trip_id))
        return record

    def list_trips(self, user_id: str | None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Newest-first trip summaries for one user (trip history)."""
        with self._cursor() as cur:
            cur.execute(
                "select trip_id, thread_id, status, origin, destination, departure_date, return_date, "
                "created_at from trips where user_id = %s order by created_at desc, trip_id "
                "limit %s offset %s",
                (codec.owner_of(user_id), max(1, min(limit, 200)), max(0, offset)),
            )
            return list(cur.fetchall())


class PostgresTripRepository(_PoolMixin):
    """Interface expected by ``app.api.deps.TripRepository``."""

    def load_state(self, trip_id: str) -> dict[str, Any] | None:
        parsed = _parse_uuid(trip_id)
        if parsed is None:
            return None
        with self._cursor() as cur:
            cur.execute("select * from trips where trip_id = %s", (parsed,))
            row = cur.fetchone()
        return codec.state_from_row(row) if row else None

    def save_itinerary(self, trip_id: str, itinerary: Any) -> None:
        """Store an immutable itinerary version and make it the trip's current one.

        * same version + same content  -> no-op (safe to retry)
        * same version + other content -> ItineraryConflictError
        * older than the latest version -> ItineraryConflictError
        """
        parsed = _parse_uuid(trip_id)
        if parsed is None:
            raise TripNotFoundError(str(trip_id))
        if _parse_uuid(getattr(itinerary, "trip_id", "")) != parsed:
            raise ValueError("itinerary.trip_id does not match trip_id")
        content, digest, total, currency = codec.itinerary_digest(itinerary)
        version = int(itinerary.version)

        with self._cursor() as cur:
            cur.execute("select trip_id from trips where trip_id = %s for update", (parsed,))
            if cur.fetchone() is None:
                raise TripNotFoundError(str(trip_id))
            cur.execute("select version, content_hash from itinerary_versions "
                        "where trip_id = %s order by version desc limit 1", (parsed,))
            latest = cur.fetchone()
            cur.execute("select content_hash from itinerary_versions where trip_id = %s and version = %s",
                        (parsed, version))
            same = cur.fetchone()
            if same is not None:
                if same["content_hash"] == digest:
                    return
                raise ItineraryConflictError(f"version {version} already exists with different content")
            if latest is not None and version < latest["version"]:
                raise ItineraryConflictError(f"version {version} is older than latest {latest['version']}")
            cur.execute(
                "insert into itinerary_versions (trip_id, version, content, content_hash, total_cost, currency) "
                "values (%s, %s, %s, %s, %s, %s)",
                (parsed, version, Jsonb(content), digest, total, currency),
            )
            cur.execute("update trips set itinerary = %s where trip_id = %s", (Jsonb(content), parsed))