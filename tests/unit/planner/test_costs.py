from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from app.planner.models import ConflictCode, ItemKind
from app.planner.service import Planner

from tests.factories import (
    D1,
    D4,
    make_experience,
    make_planning,
    make_transport,
    make_trip,
)


def test_exact_total_and_category_breakdown():
    plan = Planner().plan(make_planning())

    assert plan.cost.total == Decimal("1220.00")
    assert plan.cost.by_category["transport"] == Decimal("760.00")
    assert plan.cost.by_category["lodging"] == Decimal("360.00")
    assert plan.cost.by_category["museum"] == Decimal("100.00")
    assert plan.cost.total == sum(line.amount for line in plan.cost.lines)
    assert plan.cost.within_budget is True
    assert all(isinstance(line.amount, Decimal) for line in plan.cost.lines)


def test_missing_price_is_labelled_as_estimate():
    experience = make_experience("e1", "Unknown price", price=None)
    plan = Planner().plan(make_planning(experiences=(experience,)))

    line = next(line for line in plan.cost.lines if line.item_id == "e1")
    assert line.is_estimate is True
    assert plan.cost.estimated_amount == Decimal("50.00")
    assert any(
        conflict.code is ConflictCode.MISSING_DATA for conflict in plan.conflicts
    )


def test_currency_mismatch_is_excluded_and_reported():
    transport = (
        make_transport(
            "t-usd",
            datetime.combine(D1, time(8, 0)),
            datetime.combine(D1, time(11, 0)),
            Decimal("100.00"),
            currency="USD",
        ),
        make_transport(
            "t-ret",
            datetime.combine(D4, time(18, 0)),
            datetime.combine(D4, time(21, 0)),
            Decimal("180.00"),
        ),
    )
    plan = Planner().plan(make_planning(transport=transport))

    assert plan.cost.excluded_lines
    assert plan.cost.excluded_lines[0].item_id == "t-usd"
    assert plan.cost.total == sum(line.amount for line in plan.cost.lines)
    assert any(
        conflict.code is ConflictCode.CURRENCY_MISMATCH for conflict in plan.conflicts
    )


def test_budget_overrun_is_reported():
    trip = make_trip(budget=Decimal("100.00"))
    plan = Planner().plan(make_planning(trip=trip))

    assert plan.cost.within_budget is False
    assert plan.cost.total > Decimal("100.00")
    assert any(
        conflict.code is ConflictCode.BUDGET_EXCEEDED for conflict in plan.conflicts
    )


def test_nightly_price_is_used_when_total_is_missing():
    lodging = make_planning().lodging[0]
    lodging.total_price = None
    plan = Planner().plan(make_planning(lodging=(lodging,)))

    assert plan.cost.by_category["lodging"] == Decimal("360.00")
    assert all(
        item.kind is not ItemKind.LODGING or not item.is_estimate
        for day in plan.days
        for item in day.items
    )
