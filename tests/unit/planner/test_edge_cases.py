from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from app.planner.models import ConflictCode, ItemKind
from app.planner.service import Planner

from tests.factories import (
    D1,
    D2,
    D4,
    make_experience,
    make_lodging,
    make_planning,
    make_transport,
    make_trip,
)


def test_empty_activity_list_still_builds_days():
    plan = Planner().plan(make_planning(experiences=()))

    assert len(plan.days) == 4
    assert plan.unscheduled == []
    assert any(
        item.kind is ItemKind.TRANSPORT for day in plan.days for item in day.items
    )
    assert all(
        item.kind is not ItemKind.ACTIVITY for day in plan.days for item in day.items
    )


def test_single_day_trip_has_one_day_and_no_lodging_night():
    trip = make_trip(start_date=D1, end_date=D1)
    transport = (
        make_transport(
            "t-single",
            depart=datetime.combine(D1, time(8, 0)),
            arrive=datetime.combine(D1, time(11, 0)),
        ),
    )
    lodging = (
        make_lodging(
            "l-single",
            check_in=datetime.combine(D1, time(15, 0)),
            check_out=datetime.combine(D1, time(18, 0)),
        ),
    )

    plan = Planner().plan(
        make_planning(trip=trip, transport=transport, lodging=lodging)
    )

    assert len(plan.days) == 1
    assert plan.days[0].date == D1
    assert not any(item.kind is ItemKind.LODGING for item in plan.days[0].items)
    assert plan.cost.currency == "EUR"


def test_trip_without_budget_is_allowed():
    trip = make_trip(budget=None)
    plan = Planner().plan(make_planning(trip=trip))

    assert plan.cost.budget is None
    assert plan.cost.within_budget is True
    assert not any(
        conflict.code is ConflictCode.BUDGET_EXCEEDED for conflict in plan.conflicts
    )


def test_activity_in_another_currency_is_excluded_and_reported():
    experience = make_experience("e-usd", "USD museum", currency="USD")
    plan = Planner().plan(make_planning(experiences=(experience,)))

    assert any(line.item_id == "e-usd" for line in plan.cost.excluded_lines)
    assert any(
        conflict.code is ConflictCode.CURRENCY_MISMATCH for conflict in plan.conflicts
    )
    assert plan.cost.total == sum(line.amount for line in plan.cost.lines)


def test_overnight_transport_does_not_overlap_next_day_activities():
    transport = (
        make_transport(
            "t-night",
            depart=datetime.combine(D1, time(22, 0)),
            arrive=datetime.combine(D2, time(6, 0)),
            price=Decimal("200.00"),
        ),
        make_transport(
            "t-ret",
            depart=datetime.combine(D4, time(18, 0)),
            arrive=datetime.combine(D4, time(21, 0)),
            price=Decimal("180.00"),
        ),
    )
    plan = Planner().plan(make_planning(transport=transport))

    night = next(
        item for day in plan.days for item in day.items if item.item_id == "t-night"
    )
    assert night.start.date() == D1
    assert night.end.date() == D2
    second_day = plan.days[1]
    assert all(
        not (item.kind is ItemKind.ACTIVITY and item.start < night.end)
        for item in second_day.items
    )


def test_dst_transition_dates_schedule_without_negative_durations():
    trip = make_trip(start_date=date(2026, 3, 29), end_date=date(2026, 3, 30))
    transport = (
        make_transport(
            "t-out",
            depart=datetime(2026, 3, 29, 8, 0),
            arrive=datetime(2026, 3, 29, 11, 0),
        ),
        make_transport(
            "t-ret",
            depart=datetime(2026, 3, 30, 18, 0),
            arrive=datetime(2026, 3, 30, 21, 0),
        ),
    )
    lodging = (
        make_lodging(
            check_in=datetime(2026, 3, 29, 15, 0),
            check_out=datetime(2026, 3, 30, 11, 0),
        ),
    )

    plan = Planner().plan(
        make_planning(trip=trip, transport=transport, lodging=lodging)
    )

    assert len(plan.days) == 2
    for day in plan.days:
        for item in day.items:
            assert item.end >= item.start
