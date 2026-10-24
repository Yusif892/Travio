from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.planner.contracts import (
    ExperienceOptionLike,
    LodgingOptionLike,
    PreferenceLike,
    TransportOptionLike,
    TripRequestLike,
)
from app.planner.models import Itinerary


@dataclass(slots=True)
class PlanningInput:
    trip: TripRequestLike
    transport: tuple[TransportOptionLike, ...] = ()
    lodging: tuple[LodgingOptionLike, ...] = ()
    experiences: tuple[ExperienceOptionLike, ...] = ()
    preferences: PreferenceLike | None = None
    selected_transport_ids: tuple[str, ...] = ()
    selected_lodging_id: str | None = None
    selected_experience_ids: tuple[str, ...] = ()
    previous_plan: Itinerary | None = None
    rebuild_dates: frozenset[date] = frozenset()
    cancelled_item_ids: frozenset[str] = frozenset()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def trip_id(self) -> str | None:
        return getattr(self.trip, "trip_id", None)

    def with_changes(self, **changes: Any) -> PlanningInput:
        data = {
            "trip": self.trip,
            "transport": self.transport,
            "lodging": self.lodging,
            "experiences": self.experiences,
            "preferences": self.preferences,
            "selected_transport_ids": self.selected_transport_ids,
            "selected_lodging_id": self.selected_lodging_id,
            "selected_experience_ids": self.selected_experience_ids,
            "previous_plan": self.previous_plan,
            "rebuild_dates": self.rebuild_dates,
            "cancelled_item_ids": self.cancelled_item_ids,
            "extra": dict(self.extra),
        }
        data.update(changes)
        return PlanningInput(**data)
