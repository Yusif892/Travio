from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.feedback.models import (
    FeedbackAction,
    FeedbackIntent,
    FeedbackTarget,
    ReplanResult,
)
from app.feedback.router import route_feedback
from app.planner.conflicts import detect_conflicts
from app.planner.costs import compute_costs, item_amount, quantize_money
from app.planner.estimates import estimate_duration_minutes
from app.planner.explanations import fallback_explanation
from app.planner.models import (
    DayPlan,
    ItemKind,
    Itinerary,
    PlanExplanation,
    ScheduledItem,
    UnscheduledActivity,
)
from app.planner.planning_input import PlanningInput
from app.planner.utils import get_value, to_geo

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "for", "of", "my", "please", "this",
    "that", "it", "we", "i", "want", "would", "like", "change", "make", "cancel",
}


def _outcome(outcome: Any) -> tuple[bool, str | None]:
    if outcome is None:
        return False, "no verification result"
    if isinstance(outcome, bool):
        return outcome, None if outcome else "rejected by verification"
    if isinstance(outcome, Mapping):
        return bool(outcome.get("passed")), outcome.get("reason")
    return bool(getattr(outcome, "passed", False)), getattr(outcome, "reason", None)


class Replanner:
    """Applies the smallest possible change and re-verifies only what changed."""

    def __init__(self, verifier: Any = None) -> None:
        self._verifier = verifier

    def replan(
        self,
        *,
        itinerary: Itinerary,
        planning: PlanningInput,
        intent: FeedbackIntent,
    ) -> ReplanResult:
        affected = route_feedback(intent)
        if intent.ambiguous:
            return self._unchanged(
                itinerary,
                intent,
                notes=["Feedback needs clarification before replanning."],
                needs_clarification=True,
                clarification=intent.clarification,
            )

        if intent.action is FeedbackAction.RATING:
            return self._unchanged(
                itinerary,
                intent,
                notes=[
                    (
                        f"Rating {intent.rating or 'received'} recorded for this trip. "
                        "Long-term preferences are updated by the memory store."
                    )
                ],
                approval_required=False,
            )

        if intent.action is FeedbackAction.CHEAPER:
            if intent.target is FeedbackTarget.ACCOMMODATION:
                return self._cheaper_lodging(itinerary, planning, intent, affected)
            if intent.target is FeedbackTarget.TRANSPORT:
                return self._cheaper_transport(itinerary, planning, intent, affected)
            if intent.target in (FeedbackTarget.ITINERARY, FeedbackTarget.UNKNOWN):
                result = self._cheaper_lodging(itinerary, planning, intent, affected)
                if result.changed_days:
                    return result
                return self._cheaper_transport(itinerary, planning, intent, affected)

        if intent.action is FeedbackAction.CANCEL and intent.target is FeedbackTarget.EXPERIENCE:
            return self._cancel_activity(itinerary, planning, intent, affected)

        if intent.action is FeedbackAction.WEATHER:
            return self._weather_swap(itinerary, planning, intent, affected)

        if intent.action in (FeedbackAction.ADD, FeedbackAction.MOVE, FeedbackAction.PACE):
            return self._unchanged(
                itinerary,
                intent,
                notes=[f"The {intent.action.value} request needs a concrete target before replanning."],
                needs_clarification=True,
                clarification=(
                    "Which day and item should I change, and should the trip be more relaxed or more packed?"
                    if intent.action is FeedbackAction.PACE
                    else "Which day and activity should I add or move?"
                ),
            )

        if intent.action is FeedbackAction.UPGRADE:
            return self._unchanged(
                itinerary,
                intent,
                notes=["Upgrade feedback is routed, but this slice supports cheaper, cancel, and weather changes."],
            )

        return self._unchanged(itinerary, intent, notes=["No applicable change was found."])

    # ------------------------------------------------------------------ helpers

    def _unchanged(
        self,
        itinerary: Itinerary,
        intent: FeedbackIntent,
        *,
        notes: list[str],
        needs_clarification: bool = False,
        clarification: str | None = None,
        approval_required: bool = False,
    ) -> ReplanResult:
        return ReplanResult(
            itinerary=itinerary,
            affected_task_ids=route_feedback(intent),
            changed_days=[],
            unchanged_days=[day.date for day in itinerary.days],
            approval_required=approval_required,
            needs_clarification=needs_clarification,
            clarification=clarification,
            notes=notes,
        )

    def _travelers(self, planning: PlanningInput) -> int:
        return max(1, int(get_value(planning.trip, "travelers", 1) or 1))

    def _lodging_total(self, option: Any, planning: PlanningInput) -> Decimal | None:
        total = get_value(option, "total_price", None)
        if total is not None:
            return quantize_money(Decimal(total))
        nightly = get_value(option, "nightly_price", None)
        if nightly is None:
            return None
        start = get_value(planning.trip, "start_date")
        end = get_value(planning.trip, "end_date")
        nights = max((end - start).days, 1)
        return quantize_money(Decimal(nightly) * nights)

    def _verify(self, items: Sequence[ScheduledItem]) -> tuple[list[str], list[str]]:
        if not items:
            return [], []
        if self._verifier is None:
            return [item.item_id for item in items], []
        try:
            outcomes = self._verifier(items)
        except Exception as exc:  # verifier failure is a failed verification, not a crash
            return [item.item_id for item in items], [f"verifier error: {exc}"]
        ids: list[str] = []
        failures: list[str] = []
        for item in items:
            ids.append(item.item_id)
            passed, reason = _outcome(outcomes.get(item.item_id))
            if not passed:
                failures.append(f"{item.item_id}: {reason or 'rejected'}")
        return ids, failures

    def _finalize(
        self,
        original: Itinerary,
        days: list[DayPlan],
        planning: PlanningInput,
        changed: set[date],
    ) -> ReplanResult:
        currency = original.currency
        cost = compute_costs(planning.trip, days, currency)
        updated = original.model_copy(deep=True)
        updated.version = original.version + 1
        updated.days = days
        updated.cost = cost
        updated.conflicts = detect_conflicts(updated, planning)

        previous = {explanation.item_id: explanation for explanation in original.explanations}
        explanations: list[PlanExplanation] = []
        for day in days:
            for item in day.items:
                if item.explanation is None:
                    explanation = previous.get(item.item_id) or fallback_explanation(item)
                    item.explanation = explanation.text
                source = previous.get(item.item_id)
                citations = source.cites if source is not None else fallback_explanation(item).cites
                explanations.append(
                    PlanExplanation(
                        item_id=item.item_id,
                        text=item.explanation or "",
                        cites=list(citations),
                    )
                )
        updated.explanations = explanations

        changed_days = sorted(day for day in changed if updated.day(day) is not None)
        return ReplanResult(
            itinerary=updated,
            changed_days=changed_days,
            unchanged_days=[day.date for day in original.days if day.date not in set(changed_days)],
            approval_required=True,
        )

    def _replace_transport_item(
        self,
        item: ScheduledItem,
        option: Any,
        planning: PlanningInput,
    ) -> ScheduledItem:
        price = get_value(option, "price", None)
        amount, unit, is_estimate = item_amount(
            ItemKind.TRANSPORT, price, self._travelers(planning)
        )
        mode = str(get_value(option, "mode", "transport")).title()
        origin = get_value(option, "origin", "")
        destination = get_value(option, "destination", "")
        return ScheduledItem(
            item_id=str(get_value(option, "id")),
            source_id=str(get_value(option, "id")),
            kind=ItemKind.TRANSPORT,
            title=f"{mode}: {origin} → {destination}".strip(": "),
            start=get_value(option, "depart_at"),
            end=get_value(option, "arrive_at"),
            unit_price=price if price is not None else unit,
            quantity=self._travelers(planning),
            amount=amount,
            currency=str(get_value(option, "currency", planning.trip.currency)),
            is_estimate=is_estimate,
            category="transport",
        )

    def _cheaper_transport(
        self,
        itinerary: Itinerary,
        planning: PlanningInput,
        intent: FeedbackIntent,
        affected: list[str],
    ) -> ReplanResult:
        percentage = intent.percentage or Decimal("0.20")
        days = [day.model_copy(deep=True) for day in itinerary.days]
        used = {
            item.source_id
            for day in itinerary.days
            for item in day.items
            if item.kind is ItemKind.TRANSPORT
        }
        replacements: list[ScheduledItem] = []
        changed: set[date] = set()

        for day in days:
            for index, item in enumerate(day.items):
                if item.kind is not ItemKind.TRANSPORT:
                    continue
                cap = quantize_money(item.amount * (Decimal(1) - percentage))
                candidates = []
                for option in planning.transport:
                    option_id = str(get_value(option, "id"))
                    if option_id in used:
                        continue
                    depart_at = get_value(option, "depart_at", None)
                    if depart_at is None or depart_at.date() != item.start.date():
                        continue
                    price = get_value(option, "price", None)
                    if price is None:
                        continue
                    candidate_amount, _, _ = item_amount(
                        ItemKind.TRANSPORT, price, self._travelers(planning)
                    )
                    if candidate_amount > cap:
                        continue
                    candidates.append((candidate_amount, option))
                if not candidates:
                    continue
                _, option = min(
                    candidates,
                    key=lambda entry: (
                        entry[0],
                        str(get_value(entry[1], "id")),
                    ),
                )
                new_item = self._replace_transport_item(item, option, planning)
                day.items[index] = new_item
                replacements.append(new_item)
                changed.add(day.date)
                used.add(str(get_value(option, "id")))

        if not replacements:
            return self._unchanged(
                itinerary,
                intent,
                notes=["No cheaper transport option was found for the affected days."],
            )

        reverified, failures = self._verify(replacements)
        if failures:
            return self._unchanged(
                itinerary,
                intent,
                notes=["Transport change was not applied because verification failed."],
            )
        result = self._finalize(itinerary, days, planning, changed)
        result.affected_task_ids = affected
        result.reverified_item_ids = reverified
        result.verification_failures = failures
        return result

    def _cheaper_lodging(
        self,
        itinerary: Itinerary,
        planning: PlanningInput,
        intent: FeedbackIntent,
        affected: list[str],
    ) -> ReplanResult:
        current_sources = {
            item.source_id
            for day in itinerary.days
            for item in day.items
            if item.kind is ItemKind.LODGING and item.source_id
        }
        if not current_sources:
            return self._unchanged(itinerary, intent, notes=["No lodging on the itinerary to change."])
        current_total = sum(
            (item.amount for day in itinerary.days for item in day.items
             if item.kind is ItemKind.LODGING),
            Decimal("0.00"),
        )
        percentage = intent.percentage or Decimal("0.20")
        cap = quantize_money(current_total * (Decimal(1) - percentage))

        candidates = []
        for option in planning.lodging:
            option_id = str(get_value(option, "id"))
            if option_id in current_sources:
                continue
            total = self._lodging_total(option, planning)
            if total is not None and total <= cap:
                candidates.append((total, option_id, option))
        if not candidates:
            return self._unchanged(
                itinerary,
                intent,
                notes=[
                    f"No lodging option at or below {cap} {itinerary.currency} was found."
                ],
            )
        _, new_id, option = min(candidates, key=lambda entry: (entry[0], entry[1]))
        total = self._lodging_total(option, planning)
        amount, unit, is_estimate = item_amount(ItemKind.LODGING, total, 1)
        new_name = str(get_value(option, "name", "Lodging"))
        point = to_geo(get_value(option, "lat", None), get_value(option, "lng", None))
        currency = str(get_value(option, "currency", itinerary.currency))

        days = [day.model_copy(deep=True) for day in itinerary.days]
        replacements: list[ScheduledItem] = []
        changed: set[date] = set()
        for day in days:
            for index, item in enumerate(day.items):
                if item.kind is not ItemKind.LODGING or item.source_id not in current_sources:
                    continue
                is_checkout = "checkout" in item.item_id
                new_item = item.model_copy(
                    update={
                        "item_id": f"{'checkout' if is_checkout else 'checkin'}:{new_id}",
                        "source_id": new_id,
                        "title": f"{'Check out' if is_checkout else 'Check in'}: {new_name}",
                        "location": point,
                        "currency": currency,
                        "unit_price": Decimal("0.00") if is_checkout else unit,
                        "quantity": 0 if is_checkout else 1,
                        "amount": Decimal("0.00") if is_checkout else amount,
                        "is_estimate": False if is_checkout else is_estimate,
                        "explanation": None,
                    }
                )
                day.items[index] = new_item
                replacements.append(new_item)
                changed.add(day.date)
                if is_checkout:
                    pass

        reverified, failures = self._verify(replacements)
        if failures:
            return self._unchanged(
                itinerary,
                intent,
                notes=["Lodging change was not applied because verification failed."],
            )
        result = self._finalize(itinerary, days, planning, changed)
        result.affected_task_ids = affected
        result.reverified_item_ids = reverified
        result.verification_failures = failures
        return result

    def _find_activity(self, itinerary: Itinerary, intent: FeedbackIntent) -> ScheduledItem | None:
        if intent.item_id:
            for day in itinerary.days:
                for item in day.items:
                    if intent.item_id in (item.item_id, item.source_id):
                        return item
        words = [
            word for word in intent.raw_text.lower().replace("'", " ").split()
            if len(word) > 3 and word not in STOPWORDS
        ]
        best: tuple[int, ScheduledItem] | None = None
        for day in itinerary.days:
            for item in day.items:
                if item.kind is not ItemKind.ACTIVITY:
                    continue
                score = sum(1 for word in words if word in item.title.lower())
                if score and (best is None or score > best[0]):
                    best = (score, item)
        if best is not None:
            return best[1]
        for day in itinerary.days:
            for item in day.items:
                if item.kind is ItemKind.ACTIVITY:
                    return item
        return None

    def _build_activity(
        self,
        option: Any,
        start: Any,
        planning: PlanningInput,
        duration_minutes: int | None = None,
    ) -> ScheduledItem:
        duration = duration_minutes
        if duration is None:
            duration, _ = estimate_duration_minutes(get_value(option, "duration_minutes", None))
        price = get_value(option, "price", None)
        amount, unit, is_estimate = item_amount(
            ItemKind.ACTIVITY, price, self._travelers(planning)
        )
        return ScheduledItem(
            item_id=str(get_value(option, "id")),
            source_id=str(get_value(option, "id")),
            kind=ItemKind.ACTIVITY,
            title=str(get_value(option, "name", "Activity")),
            start=start,
            end=start + timedelta(minutes=duration),
            location=to_geo(get_value(option, "lat", None), get_value(option, "lng", None)),
            unit_price=price if price is not None else unit,
            quantity=self._travelers(planning),
            amount=amount,
            currency=str(get_value(option, "currency", planning.trip.currency)),
            is_estimate=is_estimate,
            category=str(get_value(option, "category", "activity")) or "activity",
        )

    def _unused_experiences(
        self, itinerary: Itinerary, planning: PlanningInput
    ) -> list[Any]:
        used = {
            item.source_id
            for day in itinerary.days
            for item in day.items
            if item.kind is ItemKind.ACTIVITY
        }
        return [
            option
            for option in planning.experiences
            if str(get_value(option, "id")) not in used
        ]

    def _cancel_activity(
        self,
        itinerary: Itinerary,
        planning: PlanningInput,
        intent: FeedbackIntent,
        affected: list[str],
    ) -> ReplanResult:
        target = self._find_activity(itinerary, intent)
        if target is None:
            return self._unchanged(itinerary, intent, notes=["No activity matched the request."])

        days = [day.model_copy(deep=True) for day in itinerary.days]
        changed: set[date] = set()
        target_day = next(day for day in days if day.date == target.start.date())
        original_index = next(
            (index for index, item in enumerate(target_day.items) if item.item_id == target.item_id),
            None,
        )
        if original_index is None:
            return self._unchanged(itinerary, intent, notes=["Activity could not be located."])
        original_item = target_day.items[original_index]
        next_item = (
            target_day.items[original_index + 1]
            if original_index + 1 < len(target_day.items)
            else None
        )
        target_day.items.pop(original_index)
        changed.add(target_day.date)

        replacements: list[ScheduledItem] = []
        failures: list[str] = []
        reverified: list[str] = []
        for option in self._unused_experiences(itinerary, planning):
            candidate = self._build_activity(option, original_item.start, planning)
            if next_item is not None and candidate.end > next_item.start:
                continue
            ids, candidate_failures = self._verify([candidate])
            reverified.extend(ids)
            if candidate_failures:
                failures.extend(candidate_failures)
                continue
            target_day.items.insert(original_index, candidate)
            replacements.append(candidate)
            break

        if not replacements:
            target_day.items.sort(key=lambda item: (item.start, item.end, item.item_id))
            result = self._finalize(itinerary, days, planning, changed)
            result.itinerary.unscheduled = list(itinerary.unscheduled) + [
                UnscheduledActivity(
                    source_id=original_item.source_id or original_item.item_id,
                    title=original_item.title,
                    reason="Cancelled by the traveler and no verified replacement was available.",
                    day=target_day.date,
                )
            ]
            result.itinerary.conflicts = detect_conflicts(result.itinerary, planning)
            result.affected_task_ids = affected
            result.reverified_item_ids = reverified
            result.verification_failures = failures
            result.notes = ["No verified replacement was found; the item was left as a gap."]
            return result

        target_day.items.sort(key=lambda item: (item.start, item.end, item.item_id))
        result = self._finalize(itinerary, days, planning, changed)
        result.affected_task_ids = affected
        result.reverified_item_ids = reverified
        result.verification_failures = failures
        result.notes = [f"Replaced '{original_item.title}' with a verified alternative."]
        return result

    def _weather_swap(
        self,
        itinerary: Itinerary,
        planning: PlanningInput,
        intent: FeedbackIntent,
        affected: list[str],
    ) -> ReplanResult:
        option_by_id = {
            str(get_value(option, "id")): option for option in planning.experiences
        }
        target_dates = {intent.target_date} if intent.target_date else {
            day.date for day in itinerary.days
        }
        days = [day.model_copy(deep=True) for day in itinerary.days]
        changed: set[date] = set()
        replacements: list[ScheduledItem] = []
        failures: list[str] = []
        reverified: list[str] = []

        for day in days:
            if day.date not in target_dates:
                continue
            for index, item in enumerate(day.items):
                if item.kind is not ItemKind.ACTIVITY:
                    continue
                source = option_by_id.get(item.source_id or item.item_id)
                if source is None or bool(get_value(source, "indoor", False)):
                    continue
                used = {
                    other.source_id
                    for other_day in days
                    for other in other_day.items
                }
                for option in planning.experiences:
                    option_id = str(get_value(option, "id"))
                    if option_id in used or not bool(get_value(option, "indoor", False)):
                        continue
                    candidate = self._build_activity(option, item.start, planning)
                    ids, candidate_failures = self._verify([candidate])
                    reverified.extend(ids)
                    if candidate_failures:
                        failures.extend(candidate_failures)
                        continue
                    next_item = day.items[index + 1] if index + 1 < len(day.items) else None
                    if next_item is not None and candidate.end > next_item.start:
                        continue
                    day.items[index] = candidate
                    replacements.append(candidate)
                    changed.add(day.date)
                    used.add(option_id)
                    break

        if not replacements:
            return self._unchanged(
                itinerary,
                intent,
                notes=["No verified indoor replacement was available."],
            )
        result = self._finalize(itinerary, days, planning, changed)
        result.affected_task_ids = affected
        result.reverified_item_ids = reverified
        result.verification_failures = failures
        result.notes = ["Outdoor activities were swapped for verified indoor alternatives."]
        return result
