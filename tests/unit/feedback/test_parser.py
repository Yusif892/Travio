from __future__ import annotations

from decimal import Decimal

from app.feedback.models import FeedbackAction, FeedbackTarget
from app.feedback.parser import parse_feedback


def test_cheaper_hotel_routes_to_accommodation_only():
    intent = parse_feedback("Make the hotel cheaper")
    assert intent.action is FeedbackAction.CHEAPER
    assert intent.target is FeedbackTarget.ACCOMMODATION
    assert intent.affected_task_ids == ["accommodation"]
    assert intent.percentage == Decimal("0.20")
    assert intent.ambiguous is False


def test_explicit_percentage_is_parsed():
    intent = parse_feedback("cheaper hotel by 30%")
    assert intent.percentage == Decimal("0.30")


def test_ambiguous_feedback_asks_for_clarification():
    intent = parse_feedback("change it")
    assert intent.ambiguous is True
    assert intent.affected_task_ids == []
    assert intent.clarification


def test_cancel_activity_is_detected():
    intent = parse_feedback("cancel the museum visit")
    assert intent.action is FeedbackAction.CANCEL
    assert intent.target is FeedbackTarget.EXPERIENCE
    assert intent.affected_task_ids == ["experience"]


def test_rating_is_normalized_to_five_stars():
    intent = parse_feedback("rate this trip 4 out of 5")
    assert intent.action is FeedbackAction.RATING
    assert intent.rating == 4
    assert intent.affected_task_ids == []
    assert intent.ambiguous is False


def test_ten_point_rating_is_normalized():
    intent = parse_feedback("I rate it 8/10")
    assert intent.action is FeedbackAction.RATING
    assert intent.rating == 4


def test_weather_feedback_targets_experiences():
    intent = parse_feedback("it will rain, swap the outdoor activities")
    assert intent.action is FeedbackAction.WEATHER
    assert intent.target is FeedbackTarget.EXPERIENCE


def test_item_id_and_date_are_extracted():
    intent = parse_feedback("cancel item:e2 on 2026-05-02")
    assert intent.item_id == "e2"
    assert intent.target_date is not None
    assert intent.target_date.isoformat() == "2026-05-02"
