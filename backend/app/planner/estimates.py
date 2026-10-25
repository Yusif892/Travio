from __future__ import annotations

from decimal import Decimal

from app.planner.config import DEFAULT_ACTIVITY_MINUTES, ESTIMATE_PRICES
from app.planner.models import ItemKind


def estimate_price(kind: ItemKind) -> Decimal:
    return ESTIMATE_PRICES[kind]


def estimate_duration_minutes(duration_minutes: int | None) -> tuple[int, bool]:
    if duration_minutes is None or duration_minutes <= 0:
        return DEFAULT_ACTIVITY_MINUTES, True
    return int(duration_minutes), False


def missing_price(price: Decimal | None) -> bool:
    return price is None
