from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.planner.planning_input import PlanningInput

D1 = date(2026, 5, 1)
D2 = date(2026, 5, 2)
D3 = date(2026, 5, 3)
D4 = date(2026, 5, 4)


def make_trip(**overrides: Any) -> SimpleNamespace:
    values = {
        "origin": "Cairo",
        "destination": "Rome",
        "start_date": D1,
        "end_date": D4,
        "budget": Decimal("3000.00"),
        "currency": "EUR",
        "travelers": 2,
        "pace": "balanced",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_transport(
    option_id: str = "t-out",
    depart: datetime | None = None,
    arrive: datetime | None = None,
    price: Decimal | None = Decimal("200.00"),
    currency: str = "EUR",
    mode: str = "flight",
    origin: str = "Cairo",
    destination: str = "Rome",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        mode=mode,
        origin=origin,
        destination=destination,
        depart_at=depart or datetime.combine(D1, time(8, 0)),
        arrive_at=arrive or datetime.combine(D1, time(11, 0)),
        price=price,
        currency=currency,
        fetched_at=datetime(2026, 4, 20, 12, 0),
    )


def make_lodging(
    option_id: str = "l1",
    name: str = "Hotel Roma",
    lat: float = 41.9000,
    lng: float = 12.5000,
    nightly_price: Decimal | None = Decimal("120.00"),
    total_price: Decimal | None = Decimal("360.00"),
    currency: str = "EUR",
    check_in: datetime | None = None,
    check_out: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        name=name,
        lat=lat,
        lng=lng,
        nightly_price=nightly_price,
        total_price=total_price,
        currency=currency,
        check_in=check_in or datetime.combine(D1, time(15, 0)),
        check_out=check_out or datetime.combine(D4, time(11, 0)),
        cancellation_terms="Free cancellation until 24h before",
        fetched_at=datetime(2026, 4, 20, 12, 0),
    )


def make_experience(
    option_id: str = "e1",
    name: str = "Colosseum",
    lat: float = 41.8902,
    lng: float = 12.4922,
    opening_hours: list[tuple[time, time]] | None = None,
    duration_minutes: int | None = 120,
    price: Decimal | None = Decimal("25.00"),
    currency: str = "EUR",
    category: str = "museum",
    indoor: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        name=name,
        category=category,
        lat=lat,
        lng=lng,
        opening_hours=opening_hours or [(time(9, 0), time(18, 0))],
        duration_minutes=duration_minutes,
        price=price,
        currency=currency,
        indoor=indoor,
        fetched_at=datetime(2026, 4, 20, 12, 0),
    )


def make_preferences(
    pace: str = "balanced",
    interests: tuple[str, ...] = (),
    max_activities_per_day: int | None = None,
    min_connection_minutes: int = 45,
    city_travel_speed_kmh: float = 20.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        pace=pace,
        interests=list(interests),
        dietary=[],
        travel_style=None,
        min_connection_minutes=min_connection_minutes,
        max_activities_per_day=max_activities_per_day,
        city_travel_speed_kmh=city_travel_speed_kmh,
    )


def make_planning(
    *,
    trip: Any = None,
    transport: tuple[Any, ...] | None = None,
    lodging: tuple[Any, ...] | None = None,
    experiences: tuple[Any, ...] | None = None,
    preferences: Any = None,
    **overrides: Any,
) -> PlanningInput:
    if transport is None:
        transport = (
            make_transport("t-out", datetime.combine(D1, time(8, 0)), datetime.combine(D1, time(11, 0)), Decimal("200.00")),
            make_transport("t-ret", datetime.combine(D4, time(18, 0)), datetime.combine(D4, time(21, 0)), Decimal("180.00")),
        )
    if lodging is None:
        lodging = (make_lodging(),)
    if experiences is None:
        experiences = (
            make_experience("e1", "Colosseum", 41.8902, 12.4922),
            make_experience("e2", "Roman Forum", 41.8925, 12.4853),
        )
    return PlanningInput(
        trip=trip or make_trip(),
        transport=tuple(transport),
        lodging=tuple(lodging),
        experiences=tuple(experiences),
        preferences=preferences or make_preferences(),
        **overrides,
    )
