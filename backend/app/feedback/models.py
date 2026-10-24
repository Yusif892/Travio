from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from app.planner.models import Itinerary
from pydantic import BaseModel, Field


class FeedbackAction(str, Enum):
    CHEAPER = "cheaper"
    UPGRADE = "upgrade"
    CANCEL = "cancel"
    ADD = "add"
    MOVE = "move"
    PACE = "pace"
    RATING = "rating"
    WEATHER = "weather"
    GENERIC = "generic"


class FeedbackTarget(str, Enum):
    TRANSPORT = "transport"
    ACCOMMODATION = "accommodation"
    EXPERIENCE = "experience"
    ITINERARY = "itinerary"
    UNKNOWN = "unknown"


TARGET_TASKS: dict[FeedbackTarget, tuple[str, ...]] = {
    FeedbackTarget.TRANSPORT: ("transport",),
    FeedbackTarget.ACCOMMODATION: ("accommodation",),
    FeedbackTarget.EXPERIENCE: ("experience",),
    FeedbackTarget.ITINERARY: ("transport", "accommodation", "experience"),
    FeedbackTarget.UNKNOWN: (),
}


def tasks_for_target(target: FeedbackTarget) -> list[str]:
    return list(TARGET_TASKS.get(target, ()))


class FeedbackIntent(BaseModel):
    action: FeedbackAction = FeedbackAction.GENERIC
    target: FeedbackTarget = FeedbackTarget.UNKNOWN
    affected_task_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    ambiguous: bool = False
    clarification: str | None = None
    percentage: Decimal | None = None
    rating: int | None = None
    target_date: date | None = None
    item_id: str | None = None
    raw_text: str = ""


class ReplanResult(BaseModel):
    itinerary: Itinerary | None = None
    affected_task_ids: list[str] = Field(default_factory=list)
    changed_days: list[date] = Field(default_factory=list)
    unchanged_days: list[date] = Field(default_factory=list)
    reverified_item_ids: list[str] = Field(default_factory=list)
    verification_failures: list[str] = Field(default_factory=list)
    approval_required: bool = True
    needs_clarification: bool = False
    clarification: str | None = None
    notes: list[str] = Field(default_factory=list)


class FeedbackResult(ReplanResult):
    intent: FeedbackIntent
