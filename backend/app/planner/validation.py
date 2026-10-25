from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.planner.planning_input import PlanningInput
from app.planner.utils import get_value

CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
MAX_REPORTED_ERRORS = 20


class PlanningValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        message = "; ".join(errors[:MAX_REPORTED_ERRORS])
        super().__init__(message)


def _is_naive(value: datetime) -> bool:
    return value.tzinfo is None or value.utcoffset() is None


def _validate_datetime(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, datetime):
        errors.append(f"{label} must be a datetime")
        return None
    if not _is_naive(value):
        errors.append(
            f"{label} must be naive UTC; timezone-aware datetimes are not supported"
        )
        return None
    return value


def _validate_currency(
    value: Any, label: str, errors: list[str], *, required: bool = False
) -> None:
    text = str(value or "").strip().upper()
    if not text:
        if required:
            errors.append(f"{label} is required")
        return
    if not CURRENCY_PATTERN.fullmatch(text):
        errors.append(f"{label} must be a 3-letter ISO currency code")


def _validate_price(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        return
    try:
        price = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{label} must be a number")
        return
    if price < 0:
        errors.append(f"{label} cannot be negative")


def _validate_coordinate(
    value: Any, label: str, minimum: float, maximum: float, errors: list[str]
) -> None:
    if value is None:
        return
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a number")
        return
    if not minimum <= coordinate <= maximum:
        errors.append(f"{label} must be between {minimum:g} and {maximum:g}")


def _validate_non_negative_int(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        return
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be an integer")
        return
    if number < 0:
        errors.append(f"{label} cannot be negative")


def _validate_positive_number(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a number")
        return
    if number <= 0:
        errors.append(f"{label} must be greater than 0")


def _validate_trip(planning: PlanningInput, errors: list[str]) -> None:
    trip = planning.trip
    if trip is None:
        errors.append("trip is required")
        return

    destination = str(get_value(trip, "destination", "") or "").strip()
    if not destination:
        errors.append("trip.destination is required")

    start = get_value(trip, "start_date", None)
    end = get_value(trip, "end_date", None)
    for label, value in (("trip.start_date", start), ("trip.end_date", end)):
        if not isinstance(value, date) or isinstance(value, datetime):
            errors.append(f"{label} must be a date")
    if (
        isinstance(start, date)
        and not isinstance(start, datetime)
        and isinstance(end, date)
        and not isinstance(end, datetime)
        and end < start
    ):
        errors.append("trip.end_date cannot be before trip.start_date")

    travelers = get_value(trip, "travelers", 0)
    try:
        count = int(travelers)
    except (TypeError, ValueError):
        errors.append("trip.travelers must be an integer")
    else:
        if count < 1:
            errors.append("trip.travelers must be at least 1")

    budget = get_value(trip, "budget", None)
    if budget is not None:
        try:
            amount = Decimal(budget)
        except (InvalidOperation, TypeError, ValueError):
            errors.append("trip.budget must be a number")
        else:
            if amount < 0:
                errors.append("trip.budget cannot be negative")

    _validate_currency(get_value(trip, "currency", ""), "trip.currency", errors, required=True)


def _validate_options(planning: PlanningInput, errors: list[str]) -> None:
    for index, option in enumerate(planning.transport):
        label = f"transport[{get_value(option, 'id', index)}]"
        depart = _validate_datetime(get_value(option, "depart_at", None), f"{label}.depart_at", errors)
        arrive = _validate_datetime(get_value(option, "arrive_at", None), f"{label}.arrive_at", errors)
        if depart is not None and arrive is not None and arrive <= depart:
            errors.append(f"{label}.arrive_at must be after depart_at")
        _validate_price(get_value(option, "price", None), f"{label}.price", errors)
        _validate_currency(get_value(option, "currency", ""), f"{label}.currency", errors)

    for index, option in enumerate(planning.lodging):
        label = f"lodging[{get_value(option, 'id', index)}]"
        check_in = _validate_datetime(get_value(option, "check_in", None), f"{label}.check_in", errors)
        check_out = _validate_datetime(get_value(option, "check_out", None), f"{label}.check_out", errors)
        if check_in is not None and check_out is not None and check_out <= check_in:
            errors.append(f"{label}.check_out must be after check_in")
        _validate_price(get_value(option, "total_price", None), f"{label}.total_price", errors)
        _validate_price(get_value(option, "nightly_price", None), f"{label}.nightly_price", errors)
        _validate_currency(get_value(option, "currency", ""), f"{label}.currency", errors)
        _validate_coordinate(get_value(option, "lat", None), f"{label}.lat", -90, 90, errors)
        _validate_coordinate(get_value(option, "lng", None), f"{label}.lng", -180, 180, errors)

    for index, option in enumerate(planning.experiences):
        label = f"experience[{get_value(option, 'id', index)}]"
        duration = get_value(option, "duration_minutes", None)
        if duration is not None:
            try:
                minutes = int(duration)
            except (TypeError, ValueError):
                errors.append(f"{label}.duration_minutes must be an integer")
            else:
                if minutes <= 0:
                    errors.append(f"{label}.duration_minutes must be greater than 0")
        _validate_price(get_value(option, "price", None), f"{label}.price", errors)
        _validate_currency(get_value(option, "currency", ""), f"{label}.currency", errors)
        _validate_coordinate(get_value(option, "lat", None), f"{label}.lat", -90, 90, errors)
        _validate_coordinate(get_value(option, "lng", None), f"{label}.lng", -180, 180, errors)

    preferences = planning.preferences
    if preferences is None:
        return
    _validate_non_negative_int(
        get_value(preferences, "min_connection_minutes", None),
        "preferences.min_connection_minutes",
        errors,
    )
    max_activities = get_value(preferences, "max_activities_per_day", None)
    if max_activities is not None:
        try:
            limit = int(max_activities)
        except (TypeError, ValueError):
            errors.append("preferences.max_activities_per_day must be an integer")
        else:
            if limit < 1:
                errors.append("preferences.max_activities_per_day must be at least 1")
    _validate_positive_number(
        get_value(preferences, "city_travel_speed_kmh", None),
        "preferences.city_travel_speed_kmh",
        errors,
    )


def validate_planning_input(planning: PlanningInput) -> None:
    """Reject structurally invalid plans before scheduling.

    Currency mismatches between the trip and an option remain a reported conflict
    rather than a hard failure, because the itinerary can still exclude and flag them.
    """

    if planning is None:
        raise PlanningValidationError(["planning input is required"])
    errors: list[str] = []
    _validate_trip(planning, errors)
    _validate_options(planning, errors)
    if errors:
        raise PlanningValidationError(errors)
