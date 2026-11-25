"""Freshness rules + targeted re-fetch requests."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .contracts import RefetchRequest

MAX_AGE = {
    "price": timedelta(hours=1),
    "opening_hours": timedelta(hours=24),
    "weather": timedelta(hours=3),
    "availability": timedelta(minutes=15),
}


@dataclass
class FetchedItem:
    item_id: str
    kind: str            # key of MAX_AGE
    tool: str            # tool to call again
    fetched_at: datetime


def find_stale(items: list[FetchedItem], now: datetime) -> list[RefetchRequest]:
    """Only the stale items come back, so we never re-run everything."""
    out = []
    for it in items:
        max_age = MAX_AGE.get(it.kind)
        if max_age and now - it.fetched_at > max_age:   # exactly max_age is still fresh
            out.append(RefetchRequest(it.item_id, it.tool, f"{it.kind} older than {max_age}"))
    return out
