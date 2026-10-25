from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.feedback.models import (
    FeedbackAction,
    FeedbackIntent,
    FeedbackTarget,
    tasks_for_target,
)

TARGET_PATTERNS: tuple[tuple[FeedbackTarget, re.Pattern[str]], ...] = (
    (
        FeedbackTarget.ACCOMMODATION,
        re.compile(r"\b(hotel|hotels|lodging|accommodation|room|resort|hostel|stay)\b"),
    ),
    (
        FeedbackTarget.TRANSPORT,
        re.compile(r"\b(flight|flights|train|transport|transfer|airline|airfare|bus|car)\b"),
    ),
    (
        FeedbackTarget.EXPERIENCE,
        re.compile(
            r"\b(activity|activities|restaurant|museum|tour|attraction|experience|"
            r"excursion|sightseeing|visit)\b"
        ),
    ),
)

ACTION_PATTERNS: tuple[tuple[FeedbackAction, re.Pattern[str]], ...] = (
    (
        FeedbackAction.CHEAPER,
        re.compile(
            r"\b(cheaper|cheap|less expensive|lower (?:the )?(?:price|cost|budget)|"
            r"reduce (?:the )?(?:price|cost|budget)|cut (?:the )?(?:price|cost|budget)|"
            r"save money)\b"
        ),
    ),
    (
        FeedbackAction.UPGRADE,
        re.compile(r"\b(upgrade|nicer|better|premium|luxury|comfortable)\b"),
    ),
    (
        FeedbackAction.CANCEL,
        re.compile(r"\b(cancel|remove|drop|skip|delete|don't want|do not want)\b"),
    ),
    (
        FeedbackAction.WEATHER,
        re.compile(r"\b(rain|raining|weather|snow|storm|heat|hot|cold)\b"),
    ),
    (
        FeedbackAction.ADD,
        re.compile(r"\b(add|include|another|more activities)\b"),
    ),
    (
        FeedbackAction.MOVE,
        re.compile(r"\b(move|reschedul\w*|shift|swap|change (?:the )?(?:time|day|date))\b"),
    ),
    (
        FeedbackAction.PACE,
        re.compile(r"\b(relaxed|packed|slow(?:er)?|faster|less busy|pace)\b"),
    ),
)

RATING_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:/|out of)\s*(5|10)\b")
STARS_PATTERN = re.compile(r"(\d+)\s*stars?\b")
PERCENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
ITEM_PATTERN = re.compile(r"\bitem(?:\s*id)?\s*[:#]?\s*([A-Za-z0-9_:-]+)", re.IGNORECASE)


def _detect_target(text: str) -> FeedbackTarget:
    for target, pattern in TARGET_PATTERNS:
        if pattern.search(text):
            return target
    return FeedbackTarget.UNKNOWN


def _detect_action(text: str) -> FeedbackAction:
    if RATING_PATTERN.search(text) or STARS_PATTERN.search(text):
        return FeedbackAction.RATING
    for action, pattern in ACTION_PATTERNS:
        if pattern.search(text):
            return action
    return FeedbackAction.GENERIC


def _detect_percentage(text: str) -> Decimal | None:
    match = PERCENT_PATTERN.search(text)
    if not match:
        return None
    try:
        value = Decimal(match.group(1)) / Decimal(100)
    except (InvalidOperation, ZeroDivisionError):
        return None
    if value <= 0 or value >= 1:
        return None
    return value.quantize(Decimal("0.01"))


def _detect_rating(text: str) -> int | None:
    match = RATING_PATTERN.search(text)
    if match:
        score = Decimal(match.group(1))
        scale = Decimal(match.group(2))
        normalized = (score / scale * Decimal(5)).quantize(Decimal(1))
        return max(1, min(5, int(normalized)))
    match = STARS_PATTERN.search(text)
    if match:
        return max(1, min(5, int(match.group(1))))
    return None


def _detect_date(text: str) -> date | None:
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _detect_item_id(text: str) -> str | None:
    match = ITEM_PATTERN.search(text)
    return match.group(1) if match else None


def _clarification(action: FeedbackAction, target: FeedbackTarget) -> str:
    if target is FeedbackTarget.UNKNOWN:
        return "Which part would you like to change: transport, accommodation, or activities?"
    label = target.value.replace("experience", "activities")
    if action is FeedbackAction.CANCEL:
        return f"Which {label} item should I cancel?"
    if action is FeedbackAction.CHEAPER:
        return f"Should I lower the cost of the {label} options? If so, by how much?"
    return f"What would you like to change about the {label}?"


def parse_feedback(
    message: str, llm: Callable[[str], str] | None = None
) -> FeedbackIntent:
    text = (message or "").strip()
    lowered = text.lower()
    target = _detect_target(lowered)
    action = _detect_action(lowered)
    percentage = _detect_percentage(lowered)
    rating = _detect_rating(lowered)
    target_date = _detect_date(lowered)
    item_id = _detect_item_id(text)

    if action is FeedbackAction.RATING and target is FeedbackTarget.UNKNOWN:
        target = FeedbackTarget.ITINERARY
    if action is FeedbackAction.WEATHER and target is FeedbackTarget.UNKNOWN:
        target = FeedbackTarget.EXPERIENCE

    if action is FeedbackAction.CHEAPER and percentage is None:
        percentage = Decimal("0.20")

    ambiguous = target is FeedbackTarget.UNKNOWN or action is FeedbackAction.GENERIC
    clarified = None
    if ambiguous and llm is not None:
        llm_intent = _parse_with_llm(text, llm)
        if llm_intent is not None:
            target = llm_intent.get("target", target)
            action = llm_intent.get("action", action)
            ambiguous = target is FeedbackTarget.UNKNOWN or action is FeedbackAction.GENERIC

    if ambiguous:
        clarified = _clarification(action, target)

    if target is not FeedbackTarget.UNKNOWN and action is not FeedbackAction.GENERIC:
        confidence = 0.9 if target_date or item_id or percentage or rating else 0.8
    elif target is not FeedbackTarget.UNKNOWN or action is not FeedbackAction.GENERIC:
        confidence = 0.5
    else:
        confidence = 0.1

    affected_tasks = [] if action is FeedbackAction.RATING else tasks_for_target(target)
    return FeedbackIntent(
        action=action,
        target=target,
        affected_task_ids=affected_tasks,
        confidence=confidence,
        ambiguous=ambiguous,
        clarification=clarified,
        percentage=percentage,
        rating=rating,
        target_date=target_date,
        item_id=item_id,
        raw_text=text,
    )


def _parse_with_llm(text: str, llm: Callable[[str], str]) -> dict[str, Any] | None:
    prompt = (
        "Classify travel-planning feedback. Return strict JSON with keys "
        '"action" (cheaper|upgrade|cancel|add|move|pace|rating|weather|generic) and '
        '"target" (transport|accommodation|experience|itinerary|unknown).\n'
        f"Feedback: {text}"
    )
    try:
        raw = llm(prompt)
    except Exception:
        return None
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    import json

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    try:
        return {
            "action": FeedbackAction(str(data.get("action", "generic")).lower()),
            "target": FeedbackTarget(str(data.get("target", "unknown")).lower()),
        }
    except ValueError:
        return None
