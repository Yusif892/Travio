from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from app.planner.conflicts import detect_conflicts
from app.planner.costs import compute_costs
from app.planner.models import (
    ConflictCode,
    DayPlan,
    GeoPoint,
    ItemKind,
    Itinerary,
    ScheduledItem,
    UnscheduledActivity,
)
from app.planner.utils import get_value

from tests.factories import D1, D2, make_lodging, make_planning, make_preferences


def _item(
    item_id: str,
    kind: ItemKind,
    start: datetime,
    end: datetime,
    *,
    location: GeoPoint | None = None,
    amount: str = "0.00",
    source_id: str | None = None,
) -> ScheduledItem:
    return ScheduledItem(
        item_id=item_id,
        source_id=source_id or item_id,
        kind=kind,
        title=item_id,
        start=start,
        end=end,
        location=location,
        unit_price=Decimal(amount),
        quantity=1,
        amount=Decimal(amount),
        currency="EUR",
        category=kind.value,
    )


def _itinerary(items: list[ScheduledItem], planning=None) -> Itinerary:
    planning = planning or make_planning()
    day = DayPlan(date=D1, items=items)
    cost = compute_costs(planning.trip, [day], "EUR")
    return Itinerary(trip_id="trip-1", currency="EUR", days=[day], cost=cost)


def _connection_conflicts(gap_minutes: int):
    start = datetime.combine(D1, time(10, 0))
    second_start = datetime.combine(D1, time(11, 0)) + timedelta(minutes=gap_minutes)
    first = _item("t1", ItemKind.TRANSPORT, start, datetime.combine(D1, time(11, 0)))
    second = _item("t2", ItemKind.TRANSPORT, second_start, second_start + timedelta(minutes=60))
    planning = make_planning(preferences=make_preferences(min_connection_minutes=45))
    return detect_conflicts(_itinerary([first, second], planning), planning)


def test_minimum_connection_boundary():
    failed = _connection_conflicts(44)
    passed = _connection_conflicts(45)
    passed_again = _connection_conflicts(46)

    assert any(conflict.code is ConflictCode.MIN_CONNECTION for conflict in failed)
    assert not any(conflict.code is ConflictCode.MIN_CONNECTION for conflict in passed)
    assert not any(conflict.code is ConflictCode.MIN_CONNECTION for conflict in passed_again)


def test_overlapping_items_are_reported():
    point = GeoPoint(lat=41.9, lng=12.5)
    first = _item(
        "e1",
        ItemKind.ACTIVITY,
        datetime.combine(D1, time(9, 0)),
        datetime.combine(D1, time(11, 0)),
        location=point,
    )
    second = _item(
        "e2",
        ItemKind.ACTIVITY,
        datetime.combine(D1, time(10, 0)),
        datetime.combine(D1, time(12, 0)),
        location=point,
    )
    conflicts = detect_conflicts(_itinerary([first, second]), make_planning())
    assert any(conflict.code is ConflictCode.OVERLAP for conflict in conflicts)


def test_activity_outside_opening_hours_is_reported():
    item = _item(
        "e1",
        ItemKind.ACTIVITY,
        datetime.combine(D1, time(20, 0)),
        datetime.combine(D1, time(22, 0)),
        location=GeoPoint(lat=41.9, lng=12.5),
    )
    conflicts = detect_conflicts(_itinerary([item]), make_planning())
    assert any(
        conflict.code is ConflictCode.OUTSIDE_OPENING_HOURS for conflict in conflicts
    )


def test_budget_overrun_is_reported():
    trip = make_planning().trip
    trip.budget = Decimal("10.00")
    item = _item("t1", ItemKind.TRANSPORT, datetime.combine(D1, time(9, 0)), datetime.combine(D1, time(10, 0)), amount="100.00")
    planning = make_planning(trip=trip)
    conflicts = detect_conflicts(_itinerary([item], planning), planning)
    assert any(conflict.code is ConflictCode.BUDGET_EXCEEDED for conflict in conflicts)


def test_lodging_must_cover_the_whole_stay():
    lodging = make_lodging(check_out=datetime.combine(D2, time(11, 0)))
    planning = make_planning(lodging=(lodging,))
    item = _item(
        "l1",
        ItemKind.LODGING,
        datetime.combine(D1, time(15, 0)),
        datetime.combine(D1, time(15, 30)),
    )
    conflicts = detect_conflicts(_itinerary([item], planning), planning)
    assert any(conflict.code is ConflictCode.LODGING_NOT_COVERING for conflict in conflicts)


def test_unscheduled_activity_is_reported_not_hidden():
    planning = make_planning()
    day = DayPlan(date=D1)
    cost = compute_costs(planning.trip, [day], "EUR")
    itinerary = Itinerary(
        trip_id="trip-1",
        currency="EUR",
        days=[day],
        cost=cost,
        unscheduled=[
            UnscheduledActivity(
                source_id="e9",
                title="Sky diving",
                reason="No feasible slot",
                day=D1,
            )
        ],
    )
    conflicts = detect_conflicts(itinerary, planning)
    assert any(
        conflict.code is ConflictCode.UNSCHEDULED_ACTIVITY for conflict in conflicts
    )
    assert get_value(conflicts[0], "severity") is not None
