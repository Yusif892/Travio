from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.planner.service import Planner
from app.planner.validation import PlanningValidationError

from tests.factories import D1, D4, make_experience, make_planning, make_transport, make_trip


def test_reversed_dates_are_rejected():
    planning = make_planning(trip=make_trip(start_date=D4, end_date=D1))

    with pytest.raises(PlanningValidationError, match="end_date cannot be before"):
        Planner().plan(planning)


def test_missing_destination_is_rejected():
    planning = make_planning(trip=make_trip(destination="  "))

    with pytest.raises(PlanningValidationError, match="destination is required"):
        Planner().plan(planning)


def test_zero_travelers_is_rejected():
    planning = make_planning(trip=make_trip(travelers=0))

    with pytest.raises(PlanningValidationError, match="at least 1"):
        Planner().plan(planning)


def test_missing_currency_is_rejected():
    planning = make_planning(trip=make_trip(currency=""))

    with pytest.raises(PlanningValidationError, match="trip.currency"):
        Planner().plan(planning)


def test_invalid_option_currency_is_rejected():
    experience = make_experience("e-bad", currency="EURO")
    planning = make_planning(experiences=(experience,))

    with pytest.raises(PlanningValidationError, match="3-letter ISO currency"):
        Planner().plan(planning)


def test_timezone_aware_transport_is_rejected():
    depart = datetime.combine(D1, datetime.min.time(), tzinfo=timezone.utc)
    transport = (
        make_transport("t-aware", depart=depart, arrive=depart + timedelta(hours=2)),
    )
    planning = make_planning(transport=transport)

    with pytest.raises(PlanningValidationError, match="naive UTC"):
        Planner().plan(planning)


def test_non_positive_activity_duration_is_rejected():
    experience = make_experience("e-zero", duration_minutes=0)
    planning = make_planning(experiences=(experience,))

    with pytest.raises(PlanningValidationError, match="greater than 0"):
        Planner().plan(planning)


def test_missing_trip_dates_are_rejected():
    planning = make_planning(trip=make_trip(start_date=None))

    with pytest.raises(PlanningValidationError, match="start_date must be a date"):
        Planner().plan(planning)
