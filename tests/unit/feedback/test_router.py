from __future__ import annotations

from app.feedback.models import FeedbackAction, FeedbackIntent, FeedbackTarget
from app.feedback.router import route_feedback


def test_only_affected_task_is_routed():
    intent = FeedbackIntent(
        action=FeedbackAction.CHEAPER,
        target=FeedbackTarget.ACCOMMODATION,
        affected_task_ids=["accommodation"],
    )
    assert route_feedback(intent) == ["accommodation"]


def test_ambiguous_intent_routes_nothing():
    intent = FeedbackIntent(
        action=FeedbackAction.GENERIC,
        target=FeedbackTarget.UNKNOWN,
        ambiguous=True,
    )
    assert route_feedback(intent) == []


def test_available_tasks_filter_is_applied():
    intent = FeedbackIntent(
        action=FeedbackAction.CHEAPER,
        target=FeedbackTarget.ITINERARY,
        affected_task_ids=["transport", "accommodation", "experience"],
    )
    assert route_feedback(intent, available_tasks=["experience"]) == ["experience"]
