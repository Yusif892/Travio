from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.planner.estimates import estimate_price
from app.planner.models import (
    CostBreakdown,
    CostLine,
    ItemKind,
    ScheduledItem,
    UnscheduledActivity,
)
from app.planner.utils import get_value

TWO_PLACES = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def item_amount(
    kind: ItemKind,
    unit_price: Decimal | None,
    quantity: int,
) -> tuple[Decimal, Decimal, bool]:
    """Return (amount, effective_unit_price, is_estimate)."""
    is_estimate = unit_price is None
    effective_unit = estimate_price(kind) if unit_price is None else Decimal(unit_price)
    amount = quantize_money(effective_unit * max(int(quantity), 0))
    return amount, quantize_money(effective_unit), is_estimate


def compute_costs(
    trip: Any,
    days: list[Any],
    currency: str,
    unscheduled: list[UnscheduledActivity] | None = None,
) -> CostBreakdown:
    lines: list[CostLine] = []
    excluded: list[CostLine] = []
    by_category: dict[str, Decimal] = {}
    total = Decimal("0.00")
    estimated = Decimal("0.00")

    for day in days:
        for item in day.items:
            line = CostLine(
                item_id=item.item_id,
                category=item.category or item.kind.value,
                amount=item.amount,
                currency=item.currency,
                is_estimate=item.is_estimate,
            )
            if item.currency and item.currency != currency:
                excluded.append(line)
                continue
            lines.append(line)
            total += line.amount
            by_category[line.category] = by_category.get(line.category, Decimal("0.00")) + line.amount
            if line.is_estimate:
                estimated += line.amount

    budget = get_value(trip, "budget", None)
    budget_decimal = None if budget is None else quantize_money(Decimal(budget))
    total = quantize_money(total)
    within_budget = True if budget_decimal is None else total <= budget_decimal

    return CostBreakdown(
        currency=currency,
        lines=lines,
        by_category={key: quantize_money(value) for key, value in by_category.items()},
        total=total,
        estimated_amount=quantize_money(estimated),
        excluded_lines=excluded,
        budget=budget_decimal,
        within_budget=within_budget,
    )


def recompute_item_amount(item: ScheduledItem) -> ScheduledItem:
    amount, unit, is_estimate = item_amount(item.kind, item.unit_price, item.quantity)
    return item.model_copy(update={"amount": amount, "unit_price": unit, "is_estimate": is_estimate})
