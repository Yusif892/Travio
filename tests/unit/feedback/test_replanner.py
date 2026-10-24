from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from app.feedback.models import FeedbackAction, FeedbackIntent, FeedbackTarget
from app.feedback.replanner import Replanner
from app.planner.models import ItemKind
from app.planner.service import Planner

from tests.factories import (
    D1,
    D2,
    D3,
    D4,
    make_experience,
    make_lodging,
    make_planning,
    make_preferences,
    make_transport,
)


class RecordingVerifier:
    def __init__(self, fail_all: bool = False) -> None:
        self.fail_all = fail_all
        self.ids: list[str] = []

    def __call__(self, items):
        outcomes = {}
        for item in items:
            self.ids.append(item.item_id)
            passed = not self.fail_all
            outcomes[item.item_id] = {
                "passed": passed,
                "reason": None if passed else "not available",
            }
        return outcomes


def _multi_day_planning():
    experiences = tuple(
        make_experience(
            f"e{index}",
            f"Activity {index}",
            41.89 + index * 0.001,
            12.49,
            duration_minutes=60,
        )
        for index in range(1, 7)
    )
    planning = make_planning(
        experiences=experiences,
        preferences=make_preferences(max_activities_per_day=1),
    )
    return planning, Planner().plan(planning)


def _cancel_intent(item_id: str) -> FeedbackIntent:
    return FeedbackIntent(
        action=FeedbackAction.CANCEL,
        target=FeedbackTarget.EXPERIENCE,
        affected_task_ids=["experience"],
        item_id=item_id,
        raw_text=f"cancel item:{item_id}",
    )


def test_cancellation_replaces_only_the_affected_day():
    planning, plan = _multi_day_planning()
    target = next(
        item for item in plan.day(D2).items if item.kind is ItemKind.ACTIVITY
    )
    verifier = RecordingVerifier()

    result = Replanner(verifier=verifier).replan(
        itinerary=plan, planning=planning, intent=_cancel_intent(target.source_id)
    )

    assert result.itinerary is not None
    assert result.changed_days == [D2]
    assert result.unchanged_days == [D1, D3, D4]
    assert result.itinerary.day(D1).model_dump() == plan.day(D1).model_dump()
    assert result.itinerary.day(D3).model_dump() == plan.day(D3).model_dump()
    assert result.itinerary.day(D4).model_dump() == plan.day(D4).model_dump()
    assert result.itinerary.version == plan.version + 1
    assert result.approval_required is True
    assert verifier.ids == result.reverified_item_ids
    assert len(verifier.ids) == 1
    assert verifier.ids[0] != target.item_id


def test_rejected_replacement_is_not_applied():
    planning, plan = _multi_day_planning()
    target = next(
        item for item in plan.day(D2).items if item.kind is ItemKind.ACTIVITY
    )
    verifier = RecordingVerifier(fail_all=True)

    result = Replanner(verifier=verifier).replan(
        itinerary=plan, planning=planning, intent=_cancel_intent(target.source_id)
    )

    assert result.itinerary is not None
    assert result.changed_days == [D2]
    assert result.itinerary.day(D2).activity_count() == 0
    assert result.verification_failures
    assert result.itinerary.day(D1).model_dump() == plan.day(D1).model_dump()
    assert any(
        entry.source_id == target.source_id for entry in result.itinerary.unscheduled
    )


def test_cheaper_lodging_changes_only_lodging_and_reverifies_it():
    l1 = make_lodging("l1", "Hotel Roma", total_price=Decimal("360.00"))
    l2 = make_lodging(
        "l2",
        "Budget Inn",
        total_price=Decimal("240.00"),
        nightly_price=Decimal("80.00"),
    )
    planning = make_planning(
        lodging=(l1, l2),
        selected_lodging_id="l1",
    )
    plan = Planner().plan(planning)
    assert plan.cost.by_category["lodging"] == Decimal("360.00")
    verifier = RecordingVerifier()
    intent = FeedbackIntent(
        action=FeedbackAction.CHEAPER,
        target=FeedbackTarget.ACCOMMODATION,
        affected_task_ids=["accommodation"],
        percentage=Decimal("0.20"),
        raw_text="make the hotel cheaper",
    )

    result = Replanner(verifier=verifier).replan(
        itinerary=plan, planning=planning, intent=intent
    )

    assert result.itinerary is not None
    assert result.changed_days == [D1, D4]
    assert result.unchanged_days == [D2, D3]
    assert result.itinerary.day(D2).model_dump() == plan.day(D2).model_dump()
    assert result.itinerary.day(D3).model_dump() == plan.day(D3).model_dump()
    assert result.itinerary.cost.by_category["lodging"] == Decimal("240.00")
    assert result.approval_required is True
    assert set(verifier.ids) == {"checkin:l2", "checkout:l2"}
    assert set(result.reverified_item_ids) == set(verifier.ids)


def test_ambiguous_feedback_does_not_replan():
    planning, plan = _multi_day_planning()
    verifier = RecordingVerifier()
    intent = FeedbackIntent(
        action=FeedbackAction.GENERIC,
        target=FeedbackTarget.UNKNOWN,
        ambiguous=True,
        clarification="Which part should change?",
    )

    result = Replanner(verifier=verifier).replan(
        itinerary=plan, planning=planning, intent=intent
    )

    assert result.changed_days == []
    assert result.unchanged_days == [D1, D2, D3, D4]
    assert result.needs_clarification is True
    assert result.clarification == "Which part should change?"
    assert result.itinerary is plan
    assert verifier.ids == []


def test_rating_does_not_change_the_plan():
    planning, plan = _multi_day_planning()
    intent = FeedbackIntent(
        action=FeedbackAction.RATING,
        target=FeedbackTarget.ITINERARY,
        rating=4,
    )
    result = Replanner().replan(itinerary=plan, planning=planning, intent=intent)

    assert result.changed_days == []
    assert result.approval_required is False
    assert result.itinerary is plan
    assert any("Rating 4" in note for note in result.notes)
def test_cheaper_transport_compares_total_cost():
    expensive = make_transport(
        "t-exp",
        datetime.combine(D1, time(8, 0)),
        datetime.combine(D1, time(11, 0)),
        Decimal("200.00"),
    )
    slightly_cheaper = make_transport(
        "t-mid",
        datetime.combine(D1, time(9, 0)),
        datetime.combine(D1, time(12, 0)),
        Decimal("250.00"),
    )
    cheap = make_transport(
        "t-cheap",
        datetime.combine(D1, time(7, 0)),
        datetime.combine(D1, time(10, 0)),
        Decimal("100.00"),
    )
    planning = make_planning(
        transport=(expensive, slightly_cheaper, cheap),
        selected_transport_ids=("t-exp",),
    )
    plan = Planner().plan(planning)
    assert plan.cost.by_category["transport"] == Decimal("400.00")
    verifier = RecordingVerifier()
    intent = FeedbackIntent(
        action=FeedbackAction.CHEAPER,
        target=FeedbackTarget.TRANSPORT,
        affected_task_ids=["transport"],
        percentage=Decimal("0.20"),
        raw_text="cheaper flight",
    )

    result = Replanner(verifier=verifier).replan(
        itinerary=plan, planning=planning, intent=intent
    )

    assert result.itinerary is not None
    assert result.changed_days == [D1]
    assert result.itinerary.cost.by_category["transport"] == Decimal("200.00")
    assert any(item.source_id == "t-cheap" for item in result.itinerary.day(D1).items)
    assert verifier.ids == ["t-cheap"]
