from __future__ import annotations

from typing import Any, Protocol

from app.planner.models import Itinerary


class TripRepository(Protocol):
    def load_state(self, trip_id: str) -> Any: ...

    def save_itinerary(self, trip_id: str, itinerary: Itinerary) -> None: ...


def get_trip_repository() -> TripRepository:
    from app.persistence.repository import PostgresTripRepository

    return PostgresTripRepository()


def get_verifier() -> Any:
    try:
        from app.verification.service import verify_items
    except (ImportError, AttributeError):
        return None
    return verify_items
