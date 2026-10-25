from __future__ import annotations

from app.planner.conflicts import detect_conflicts
from app.planner.costs import compute_costs
from app.planner.explanations import ExplanationService
from app.planner.models import Itinerary
from app.planner.planning_input import PlanningInput
from app.planner.scheduler import build_schedule
from app.planner.utils import get_value


class Planner:
    def __init__(self, explainer: ExplanationService | None = None) -> None:
        self._explainer = explainer or ExplanationService()

    def plan(self, planning: PlanningInput, trip_id: str | None = None) -> Itinerary:
        schedule = build_schedule(planning)
        trip = planning.trip
        currency = str(get_value(trip, "currency", ""))
        cost = compute_costs(trip, schedule.days, currency, schedule.unscheduled)
        version = 1
        if planning.previous_plan is not None:
            version = planning.previous_plan.version + 1
        itinerary = Itinerary(
            trip_id=trip_id or planning.trip_id or str(get_value(trip, "id", "")),
            version=version,
            currency=currency,
            days=schedule.days,
            cost=cost,
            unscheduled=schedule.unscheduled,
            notes=schedule.notes,
        )
        itinerary.conflicts = detect_conflicts(itinerary, planning)
        return self._explainer.annotate(itinerary, planning.preferences)
