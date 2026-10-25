from uuid import UUID

from app.domain.schemas import TripRecord


class InMemoryTripStore:
    """A replaceable repository used until the persistence owner adds PostgreSQL."""
    def __init__(self) -> None:
        self._records: dict[UUID, TripRecord] = {}

    def create(self, record: TripRecord) -> TripRecord:
        self._records[record.trip_id] = record
        return record

    def get(self, trip_id: UUID, user_id: str | None = None) -> TripRecord | None:
        record = self._records.get(trip_id)
        if record and record.user_id and user_id and record.user_id != user_id:
            return None
        return record

    def save(self, record: TripRecord) -> TripRecord:
        self._records[record.trip_id] = record
        return record


trip_store = InMemoryTripStore()
