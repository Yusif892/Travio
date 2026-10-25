from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Protocol

from app.planner.models import ScheduledItem


class TripRequestLike(Protocol):
    origin: str
    destination: str
    start_date: date
    end_date: date
    budget: Decimal
    currency: str
    travelers: int


class TransportOptionLike(Protocol):
    id: str
    mode: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    price: Decimal | None
    currency: str


class LodgingOptionLike(Protocol):
    id: str
    name: str
    lat: float
    lng: float
    nightly_price: Decimal | None
    total_price: Decimal | None
    currency: str
    check_in: datetime
    check_out: datetime


class ExperienceOptionLike(Protocol):
    id: str
    name: str
    category: str
    lat: float
    lng: float
    opening_hours: Sequence[tuple[time, time]]
    duration_minutes: int | None
    price: Decimal | None
    currency: str
    indoor: bool


class PreferenceLike(Protocol):
    pace: object
    interests: Sequence[str]
    min_connection_minutes: int
    max_activities_per_day: int | None
    city_travel_speed_kmh: float


class VerificationOutcomeLike(Protocol):
    passed: bool
    reason: str | None


class Verifier(Protocol):
    def __call__(
        self, items: Sequence[ScheduledItem]
    ) -> Mapping[str, VerificationOutcomeLike | bool]: ...
