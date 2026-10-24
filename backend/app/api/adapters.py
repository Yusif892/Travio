from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.planner.planning_input import PlanningInput
from app.planner.utils import get_value


def _options(state: Any, name: str) -> tuple[Any, ...]:
    value = get_value(state, name, None) or ()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        return tuple(value)
    return ()


def planning_input_from_state(state: Any) -> PlanningInput:
    trip = get_value(state, "trip_request", None)
    if trip is None:
        raise ValueError("Trip state has no trip_request")
    return PlanningInput(
        trip=trip,
        transport=_options(state, "transport_options"),
        lodging=_options(state, "lodging_options"),
        experiences=_options(state, "experience_options"),
        preferences=get_value(state, "preferences", None),
        selected_transport_ids=tuple(get_value(state, "selected_transport_ids", ()) or ()),
        selected_lodging_id=get_value(state, "selected_lodging_id", None),
        selected_experience_ids=tuple(get_value(state, "selected_experience_ids", ()) or ()),
        previous_plan=get_value(state, "itinerary", None),
    )
