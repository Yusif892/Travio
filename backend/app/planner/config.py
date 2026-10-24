from __future__ import annotations

from datetime import time
from decimal import Decimal

from app.planner.models import ItemKind

DAY_START = time(8, 0)
DAY_END = time(21, 0)
DEFAULT_CHECK_IN = time(15, 0)
DEFAULT_CHECK_OUT = time(11, 0)
CHECK_IN_DURATION_MINUTES = 30
CHECK_OUT_DURATION_MINUTES = 30

TRANSFER_BUFFER_MINUTES = 15
TRAVEL_BUFFER_MINUTES = 10
DEFAULT_TRAVEL_MINUTES = 15
DEFAULT_CITY_SPEED_KMH = 20.0
DEFAULT_ACTIVITY_MINUTES = 90
DEFAULT_MIN_CONNECTION_MINUTES = 45

PACE_LIMITS = {"relaxed": 2, "balanced": 3, "packed": 5}
FALLBACK_PACE_LIMIT = 3

ESTIMATE_PRICES = {
    ItemKind.TRANSPORT: Decimal("50.00"),
    ItemKind.LODGING: Decimal("100.00"),
    ItemKind.ACTIVITY: Decimal("25.00"),
}

MAX_ACTIVITIES_PER_DAY = 5
