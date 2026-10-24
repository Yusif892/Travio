from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ItemKind(str, Enum):
    TRANSPORT = "transport"
    LODGING = "lodging"
    ACTIVITY = "activity"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ConflictCode(str, Enum):
    OVERLAP = "OVERLAP"
    OUTSIDE_OPENING_HOURS = "OUTSIDE_OPENING_HOURS"
    INSUFFICIENT_TRAVEL = "INSUFFICIENT_TRAVEL"
    MIN_CONNECTION = "MIN_CONNECTION"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    LODGING_NOT_COVERING = "LODGING_NOT_COVERING"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    UNSCHEDULED_ACTIVITY = "UNSCHEDULED_ACTIVITY"
    MISSING_DATA = "MISSING_DATA"


class GeoPoint(BaseModel):
    lat: float
    lng: float


class ScheduledItem(BaseModel):
    item_id: str
    source_id: str | None = None
    kind: ItemKind
    title: str
    start: datetime
    end: datetime
    location: GeoPoint | None = None
    unit_price: Decimal | None = None
    quantity: int = 1
    amount: Decimal = Decimal("0.00")
    currency: str = ""
    is_estimate: bool = False
    category: str = ""
    explanation: str | None = None


class DayPlan(BaseModel):
    date: date
    items: list[ScheduledItem] = Field(default_factory=list)

    def activity_count(self) -> int:
        return sum(1 for item in self.items if item.kind is ItemKind.ACTIVITY)


class CostLine(BaseModel):
    item_id: str
    category: str
    amount: Decimal
    currency: str
    is_estimate: bool = False


class CostBreakdown(BaseModel):
    currency: str
    lines: list[CostLine] = Field(default_factory=list)
    by_category: dict[str, Decimal] = Field(default_factory=dict)
    total: Decimal = Decimal("0.00")
    estimated_amount: Decimal = Decimal("0.00")
    excluded_lines: list[CostLine] = Field(default_factory=list)
    budget: Decimal | None = None
    within_budget: bool = True


class Conflict(BaseModel):
    code: ConflictCode
    severity: Severity
    message: str
    day: date | None = None
    item_ids: list[str] = Field(default_factory=list)


class PlanExplanation(BaseModel):
    item_id: str
    text: str
    cites: list[str] = Field(default_factory=list)


class UnscheduledActivity(BaseModel):
    source_id: str
    title: str
    reason: str
    day: date | None = None


class Itinerary(BaseModel):
    trip_id: str
    version: int = 1
    currency: str = ""
    days: list[DayPlan] = Field(default_factory=list)
    cost: CostBreakdown
    conflicts: list[Conflict] = Field(default_factory=list)
    explanations: list[PlanExplanation] = Field(default_factory=list)
    unscheduled: list[UnscheduledActivity] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def day(self, day_date: date) -> DayPlan | None:
        for planned in self.days:
            if planned.date == day_date:
                return planned
        return None

    def item(self, item_id: str) -> ScheduledItem | None:
        for planned in self.days:
            for item in planned.items:
                if item.item_id == item_id:
                    return item
        return None
