"""Deterministic intake safety and completeness checks.

This module intentionally never calls a model: any future semantic classifier
is advisory only and cannot turn an unsafe or incomplete request into a plan.
"""
from dataclasses import dataclass

from app.domain.enums import IntakeStatus
from app.domain.schemas import TripRequest

INJECTION_MARKERS = (
    "ignore previous instructions", "ignore all previous instructions",
    "system prompt", "developer message", "bypass guardrail", "jailbreak",
    "call unauthorized tool", "book this trip",
)
TRAVEL_MARKERS = (
    "trip", "travel", "flight", "fly", "hotel", "accommodation", "stay",
    "visit", "vacation", "holiday", "itinerary", "train", "activity",
    "destination", "airport", "restaurant",
)


@dataclass(frozen=True)
class IntakeDecision:
    status: IntakeStatus
    message: str
    missing_fields: list[str]


def evaluate_intake(request: TripRequest, message: str) -> IntakeDecision:
    text = message.casefold()
    if any(marker in text for marker in INJECTION_MARKERS):
        return IntakeDecision(IntakeStatus.REJECTED, "I can only help with safe travel planning requests.", [])

    # Structured fields themselves establish travel scope, even when the user
    # uses a short message such as "please plan this".
    has_structured_trip_data = any((request.origin, request.destination, request.departure_date,
                                   request.return_date, request.budget, request.travelers))
    if message and not has_structured_trip_data and not any(marker in text for marker in TRAVEL_MARKERS):
        return IntakeDecision(IntakeStatus.REJECTED, "I can help with travel planning, but not that request.", [])

    missing = request.missing_fields()
    if missing:
        human_fields = ", ".join(missing)
        return IntakeDecision(IntakeStatus.CLARIFICATION_NEEDED,
                              f"Please provide: {human_fields}.", missing)
    return IntakeDecision(IntakeStatus.ACCEPTED, "Your travel request is ready for planning.", [])
