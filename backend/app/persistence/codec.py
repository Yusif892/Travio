"""Pure conversion helpers between application objects and database rows.

No database driver is imported here, so everything in this module can be unit
tested without PostgreSQL.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domain.schemas import PlanningTask, TripRecord, TripRequest, WorkflowError

# Trips created without a user id are stored under this owner. They are only
# reachable by callers that also present no user id (matches the current API,
# where authentication is optional).
ANONYMOUS_USER = "anonymous"

# TripRequest has no currency yet; the planner requires one.
DEFAULT_CURRENCY = "USD"
DEFAULT_PACE = "balanced"

# Option fields that the planner needs as real datetimes after a JSON round trip.
DATETIME_KEYS = frozenset({"depart_at", "arrive_at", "check_in", "check_out", "fetched_at"})


def owner_of(user_id: str | None) -> str:
    return (user_id or "").strip() or ANONYMOUS_USER


def record_to_params(record: TripRecord) -> dict[str, Any]:
    """Flatten a TripRecord into column values (JSON columns hold plain Python)."""
    request = record.trip_request
    return {
        "trip_id": record.trip_id,
        "thread_id": record.thread_id,
        "user_id": owner_of(record.user_id),
        "origin": request.origin,
        "destination": request.destination,
        "departure_date": request.departure_date,
        "return_date": request.return_date,
        "budget": request.budget,
        "travelers": request.travelers,
        "trip_request": request.model_dump(mode="json"),
        "messages": list(record.messages),
        "tasks": [task.model_dump(mode="json") for task in record.tasks],
        "transport_options": list(record.transport_options),
        "lodging_options": list(record.lodging_options),
        "experience_options": list(record.experience_options),
        "verification": record.verification,
        "itinerary": record.itinerary,
        "errors": [error.model_dump(mode="json") for error in record.errors],
    }


def row_to_record(row: Mapping[str, Any]) -> TripRecord:
    """Rebuild a TripRecord from a ``trips`` row (approval/bookings live in their own tables)."""
    owner = row["user_id"]
    return TripRecord(
        trip_id=row["trip_id"],
        thread_id=row["thread_id"],
        user_id=None if owner == ANONYMOUS_USER else owner,
        trip_request=TripRequest.model_validate(row["trip_request"]),
        messages=list(row["messages"]),
        tasks=[PlanningTask.model_validate(task) for task in row["tasks"]],
        transport_options=list(row["transport_options"]),
        lodging_options=list(row["lodging_options"]),
        experience_options=list(row["experience_options"]),
        verification=row["verification"],
        itinerary=row["itinerary"],
        errors=[WorkflowError.model_validate(error) for error in row["errors"]],
    )


def decode_option(option: Mapping[str, Any]) -> dict[str, Any]:
    """Turn ISO strings in known datetime fields back into naive-UTC datetimes."""
    decoded = dict(option)
    for key in DATETIME_KEYS:
        value = decoded.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            decoded[key] = parsed
    return decoded


def state_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build the state mapping consumed by the itinerary/feedback API.

    ``trip_request`` gains the field names the planner expects
    (``start_date``/``end_date``/``currency``/``pace``/``trip_id``).
    """
    from app.planner.models import Itinerary  # local import keeps codec light

    request = dict(row["trip_request"])
    trip = {
        **request,
        "trip_id": str(row["trip_id"]),
        "start_date": row["departure_date"],
        "end_date": row["return_date"],
        "budget": row["budget"],
        "travelers": row["travelers"],
        "currency": request.get("currency") or DEFAULT_CURRENCY,
        "pace": request.get("pace") or DEFAULT_PACE,
    }
    owner = None if row["user_id"] == ANONYMOUS_USER else row["user_id"]
    itinerary = row["itinerary"]
    return {
        "trip_id": str(row["trip_id"]),
        "owner_id": owner,
        "user_id": owner,
        "trip_request": trip,
        "messages": list(row["messages"]),
        "transport_options": [decode_option(o) for o in row["transport_options"]],
        "lodging_options": [decode_option(o) for o in row["lodging_options"]],
        "experience_options": [decode_option(o) for o in row["experience_options"]],
        "verification": row["verification"],
        "itinerary": Itinerary.model_validate(itinerary) if itinerary else None,
        "preferences": None,  # filled once the preferences repository exists
        "errors": list(row["errors"]),
    }


def itinerary_digest(itinerary: Any) -> tuple[dict[str, Any], str, Decimal | None, str | None]:
    """Return (json content, sha256 hex, total cost, 3-letter currency)."""
    content = itinerary.model_dump(mode="json")
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    cost = getattr(itinerary, "cost", None)
    total = getattr(cost, "total", None)
    currency = (getattr(itinerary, "currency", "") or "").strip().upper()
    return content, digest, total, currency if len(currency) == 3 else None