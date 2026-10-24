from __future__ import annotations

import itertools
from datetime import date

from app.planner.config import (
    DEFAULT_CITY_SPEED_KMH,
    DEFAULT_MIN_CONNECTION_MINUTES,
)
from app.planner.geo import travel_minutes
from app.planner.models import (
    Conflict,
    ConflictCode,
    DayPlan,
    ItemKind,
    Itinerary,
    Severity,
)
from app.planner.planning_input import PlanningInput
from app.planner.scheduler import _opening_windows
from app.planner.utils import get_value


def _conflict(
    code: ConflictCode,
    severity: Severity,
    message: str,
    day: date | None = None,
    item_ids: list[str] | None = None,
) -> Conflict:
    return Conflict(
        code=code,
        severity=severity,
        message=message,
        day=day,
        item_ids=item_ids or [],
    )


def _check_day(
    planned_day: DayPlan,
    experiences: dict[str, object],
    speed_kmh: float,
    min_connection: int,
) -> list[Conflict]:
    conflicts: list[Conflict] = []
    items = sorted(planned_day.items, key=lambda item: (item.start, item.end, item.item_id))

    for previous, current in itertools.pairwise(items):
        if current.start < previous.end:
            conflicts.append(
                _conflict(
                    ConflictCode.OVERLAP,
                    Severity.ERROR,
                    f"'{current.title}' overlaps '{previous.title}'.",
                    planned_day.date,
                    [previous.item_id, current.item_id],
                )
            )
        gap = int((current.start - previous.end).total_seconds() // 60)
        if previous.location is not None and current.location is not None:
            required = travel_minutes(previous.location, current.location, speed_kmh)
            if gap < required:
                conflicts.append(
                    _conflict(
                        ConflictCode.INSUFFICIENT_TRAVEL,
                        Severity.ERROR,
                        f"Only {gap} min between '{previous.title}' and '{current.title}'; "
                        f"{required} min of travel is needed.",
                        planned_day.date,
                        [previous.item_id, current.item_id],
                    )
                )
        if (
            previous.kind is ItemKind.TRANSPORT
            and current.kind is ItemKind.TRANSPORT
            and gap < min_connection
        ):
            conflicts.append(
                _conflict(
                    ConflictCode.MIN_CONNECTION,
                    Severity.ERROR,
                    f"Connection is {gap} min; minimum is {min_connection} min.",
                    planned_day.date,
                    [previous.item_id, current.item_id],
                )
            )

    for item in items:
        if item.kind is ItemKind.ACTIVITY:
            option = experiences.get(item.source_id or item.item_id)
            if option is not None:
                windows = _opening_windows(option)
                start_time = item.start.time()
                end_time = item.end.time()
                inside = any(
                    opens <= start_time and end_time <= closes for opens, closes in windows
                )
                if not inside:
                    conflicts.append(
                        _conflict(
                            ConflictCode.OUTSIDE_OPENING_HOURS,
                            Severity.ERROR,
                            f"'{item.title}' is scheduled outside its opening hours.",
                            planned_day.date,
                            [item.item_id],
                        )
                    )
        if item.is_estimate:
            conflicts.append(
                _conflict(
                    ConflictCode.MISSING_DATA,
                    Severity.WARNING,
                    f"'{item.title}' uses an estimated value and is not confirmed.",
                    planned_day.date,
                    [item.item_id],
                )
            )
    return conflicts


def detect_conflicts(itinerary: Itinerary, planning: PlanningInput) -> list[Conflict]:
    preferences = planning.preferences
    speed_kmh = float(
        get_value(preferences, "city_travel_speed_kmh", DEFAULT_CITY_SPEED_KMH)
        or DEFAULT_CITY_SPEED_KMH
    )
    min_connection = int(
        get_value(preferences, "min_connection_minutes", DEFAULT_MIN_CONNECTION_MINUTES)
        or DEFAULT_MIN_CONNECTION_MINUTES
    )
    experiences: dict[str, object] = {
        str(get_value(option, "id")): option for option in planning.experiences
    }

    conflicts: list[Conflict] = []
    for planned_day in itinerary.days:
        conflicts.extend(_check_day(planned_day, experiences, speed_kmh, min_connection))

    for excluded in itinerary.cost.excluded_lines:
        conflicts.append(
            _conflict(
                ConflictCode.CURRENCY_MISMATCH,
                Severity.ERROR,
                f"Item {excluded.item_id} is in {excluded.currency}, not {itinerary.currency}.",
                None,
                [excluded.item_id],
            )
        )

    budget = itinerary.cost.budget
    if budget is not None and itinerary.cost.total > budget:
        over = itinerary.cost.total - budget
        conflicts.append(
            _conflict(
                ConflictCode.BUDGET_EXCEEDED,
                Severity.ERROR,
                f"Total {itinerary.cost.total} {itinerary.currency} exceeds the budget "
                f"{budget} {itinerary.currency} by {over}.",
            )
        )

    trip = planning.trip
    start_date = get_value(trip, "start_date")
    end_date = get_value(trip, "end_date")
    used_lodging = {
        item.source_id
        for planned_day in itinerary.days
        for item in planned_day.items
        if item.kind is ItemKind.LODGING and item.source_id
    }
    for option in planning.lodging:
        if str(get_value(option, "id")) not in used_lodging:
            continue
        check_in = get_value(option, "check_in", None)
        check_out = get_value(option, "check_out", None)
        if check_in is None or check_out is None:
            continue
        if check_in.date() > start_date or check_out.date() < end_date:
            conflicts.append(
                _conflict(
                    ConflictCode.LODGING_NOT_COVERING,
                    Severity.ERROR,
                    f"Lodging '{get_value(option, 'name', '')}' does not cover the full stay.",
                    start_date,
                    [str(get_value(option, "id"))],
                )
            )
            break

    for entry in itinerary.unscheduled:
        conflicts.append(
            _conflict(
                ConflictCode.UNSCHEDULED_ACTIVITY,
                Severity.WARNING,
                f"'{entry.title}' could not be scheduled: {entry.reason}",
                entry.day,
                [entry.source_id],
            )
        )

    unique: dict[tuple[str, str, str], Conflict] = {}
    for conflict in conflicts:
        key = (conflict.code.value, conflict.day.isoformat() if conflict.day else "", ",".join(conflict.item_ids))
        if key not in unique:
            unique[key] = conflict
    return sorted(
        unique.values(),
        key=lambda conflict: (
            conflict.day or date.min,
            conflict.code.value,
            conflict.item_ids,
            conflict.message,
        ),
    )
