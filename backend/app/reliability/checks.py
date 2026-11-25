"""Deterministic checks (TRV-04). Pure functions, no LLM, easy to test."""
from dataclasses import dataclass, field
from datetime import datetime, time

from .contracts import Issue, Severity, VerificationResult


@dataclass
class Activity:
    name: str
    start: datetime
    end: datetime
    opens: time | None = None
    closes: time | None = None
    cost: float = 0.0
    is_meal: bool = False
    diet_tags: set[str] = field(default_factory=set)   # e.g. {"vegetarian"}
    unsafe: bool = False
    travel_minutes_from_prev: int = 0


@dataclass
class Itinerary:
    activities: list[Activity]
    budget: float
    trip_start: datetime
    trip_end: datetime
    required_diet: set[str] = field(default_factory=set)


def _res(*issues: Issue) -> VerificationResult:
    return VerificationResult(issues=list(issues))


def check_timing(it: Itinerary) -> VerificationResult:
    out = VerificationResult()
    acts = sorted(it.activities, key=lambda a: a.start)
    for a in acts:
        if a.end <= a.start:
            out.issues.append(Issue("BAD_DURATION", f"{a.name} ends before it starts"))
    for prev, cur in zip(acts, acts[1:]):
        gap = (cur.start - prev.end).total_seconds() / 60
        if gap < 0:
            out.issues.append(Issue("OVERLAP", f"{prev.name} overlaps {cur.name}"))
        elif gap < cur.travel_minutes_from_prev:
            out.issues.append(Issue(
                "TRAVEL_TOO_SHORT",
                f"Only {gap:.0f} min to reach {cur.name}, need {cur.travel_minutes_from_prev}"))
    return out


def check_opening_hours(it: Itinerary) -> VerificationResult:
    out = VerificationResult()
    for a in it.activities:
        if a.opens and a.closes:
            # boundary: starting exactly at open / ending exactly at close is OK
            if a.start.time() < a.opens or a.end.time() > a.closes:
                out.issues.append(Issue("OUTSIDE_HOURS", f"{a.name} is outside {a.opens}-{a.closes}"))
    return out


def check_budget(it: Itinerary) -> VerificationResult:
    total = sum(a.cost for a in it.activities)
    if total > it.budget:   # exactly at the limit passes
        return _res(Issue("BUDGET_EXCEEDED", f"Total {total} > budget {it.budget}"))
    return VerificationResult()


def check_dates(it: Itinerary) -> VerificationResult:
    out = VerificationResult()
    if it.trip_end < it.trip_start:
        out.issues.append(Issue("BAD_TRIP_DATES", "Trip ends before it starts"))
    for a in it.activities:
        if a.start < it.trip_start or a.end > it.trip_end:
            out.issues.append(Issue("OUTSIDE_TRIP", f"{a.name} is outside the trip dates"))
    return out


def check_dietary(it: Itinerary) -> VerificationResult:
    out = VerificationResult()
    for a in it.activities:
        if a.is_meal and not it.required_diet.issubset(a.diet_tags):
            missing = it.required_diet - a.diet_tags
            out.issues.append(Issue("DIET_MISMATCH", f"{a.name} lacks {sorted(missing)}"))
    return out


def check_safety(it: Itinerary) -> VerificationResult:
    return VerificationResult(issues=[
        Issue("UNSAFE", f"{a.name} is flagged unsafe", Severity.CRITICAL)
        for a in it.activities if a.unsafe
    ])


ALL_CHECKS = [check_timing, check_opening_hours, check_budget,
              check_dates, check_dietary, check_safety]


def verify_itinerary(it: Itinerary) -> VerificationResult:
    result = VerificationResult()
    for check in ALL_CHECKS:
        result.extend(check(it))
    return result
