from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from app.planner.config import (
    CHECK_IN_DURATION_MINUTES,
    CHECK_OUT_DURATION_MINUTES,
    DAY_END,
    DAY_START,
    DEFAULT_CHECK_IN,
    DEFAULT_CHECK_OUT,
    DEFAULT_CITY_SPEED_KMH,
    DEFAULT_MIN_CONNECTION_MINUTES,
    FALLBACK_PACE_LIMIT,
    MAX_ACTIVITIES_PER_DAY,
    PACE_LIMITS,
    TRANSFER_BUFFER_MINUTES,
)
from app.planner.costs import item_amount, quantize_money
from app.planner.estimates import estimate_duration_minutes
from app.planner.geo import travel_minutes
from app.planner.models import (
    DayPlan,
    ItemKind,
    ScheduledItem,
    UnscheduledActivity,
)
from app.planner.planning_input import PlanningInput
from app.planner.utils import enum_value, get_value, to_geo


@dataclass(slots=True)
class ScheduleResult:
    days: list[DayPlan] = field(default_factory=list)
    unscheduled: list[UnscheduledActivity] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlannerSettings:
    speed_kmh: float = DEFAULT_CITY_SPEED_KMH
    pace_limit: int = FALLBACK_PACE_LIMIT
    min_connection_minutes: int = DEFAULT_MIN_CONNECTION_MINUTES
    travelers: int = 1
    currency: str = ""
    interests: tuple[str, ...] = ()


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, str):
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
    return None


def _opening_windows(option: Any) -> list[tuple[time, time]]:
    raw = get_value(option, "opening_hours", None)
    windows: list[tuple[time, time]] = []
    if raw:
        for entry in raw:
            if isinstance(entry, Mapping):
                opens = (
                    entry.get("opens")
                    or entry.get("open")
                    or entry.get("start")
                    or entry.get("from")
                )
                closes = (
                    entry.get("closes")
                    or entry.get("close")
                    or entry.get("end")
                    or entry.get("to")
                )
            elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                opens, closes = entry[0], entry[1]
            else:
                opens = get_value(entry, "opens", None)
                closes = get_value(entry, "closes", None)
            start, end = _parse_time(opens), _parse_time(closes)
            if start is not None and end is not None and end > start:
                windows.append((start, end))
    if not windows:
        windows.append((DAY_START, DAY_END))
    return sorted(windows)


def _next_open_slot(
    windows: Sequence[tuple[time, time]], earliest: time
) -> tuple[time, time] | None:
    for opens, closes in windows:
        if earliest < opens:
            return opens, closes
        if opens <= earliest < closes:
            return earliest, closes
    return None


def _combine(day: date, value: time) -> datetime:
    return datetime.combine(day, value)


def _inclusive_dates(start: date, end: date) -> list[date]:
    if end < start:
        start, end = end, start
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _nights(trip: Any) -> int:
    start, end = get_value(trip, "start_date"), get_value(trip, "end_date")
    return max((end - start).days, 1)


def _lodging_total(option: Any, trip: Any) -> Decimal | None:
    total = get_value(option, "total_price", None)
    if total is not None:
        return quantize_money(Decimal(total))
    nightly = get_value(option, "nightly_price", None)
    if nightly is not None:
        return quantize_money(Decimal(nightly) * _nights(trip))
    return None


def _select_lodging(planning: PlanningInput) -> Any | None:
    options = list(planning.lodging)
    if not options:
        return None
    selected = planning.selected_lodging_id
    if selected:
        for option in options:
            if str(get_value(option, "id")) == selected:
                return option
    trip = planning.trip
    start, end = get_value(trip, "start_date"), get_value(trip, "end_date")

    def covers(option: Any) -> bool:
        check_in = get_value(option, "check_in", None)
        check_out = get_value(option, "check_out", None)
        return (
            check_in is not None
            and check_out is not None
            and check_in.date() <= start
            and check_out.date() >= end
        )

    covering = [option for option in options if covers(option)]
    pool = covering or options
    return min(
        pool,
        key=lambda option: (
            _lodging_total(option, trip) or Decimal(999999999),
            str(get_value(option, "id")),
        ),
    )


def _transport_departure(option: Any) -> datetime | None:
    value = get_value(option, "depart_at", None)
    return value if isinstance(value, datetime) else None


def _select_transport(planning: PlanningInput, day: date) -> Any | None:
    options = list(planning.transport)
    if not options:
        return None
    if planning.selected_transport_ids:
        wanted = set(planning.selected_transport_ids)
        selected = [option for option in options if str(get_value(option, "id")) in wanted]
        for option in selected:
            departure = _transport_departure(option)
            if departure is not None and departure.date() == day:
                return option
    same_day = [
        option
        for option in options
        if (departure := _transport_departure(option)) is not None and departure.date() == day
    ]
    if not same_day:
        return None
    return min(
        same_day,
        key=lambda option: (
            Decimal(get_value(option, "price") or "0"),
            _transport_departure(option) or datetime.max,
            str(get_value(option, "id")),
        ),
    )


def _days_without_fixed(
    planned_day: DayPlan,
) -> list[tuple[datetime, datetime]]:
    window_start = _combine(planned_day.date, DAY_START)
    window_end = _combine(planned_day.date, DAY_END)
    occupied = sorted(
        ((item.start, item.end) for item in planned_day.items if item.end > item.start),
        key=lambda pair: pair[0],
    )
    free: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for start, end in occupied:
        if start > cursor:
            free.append((cursor, min(start, window_end)))
        cursor = max(cursor, end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        free.append((cursor, window_end))
    return [(start, end) for start, end in free if end > start]


def _interest_score(option: Any, interests: Sequence[str]) -> int:
    if not interests:
        return 0
    haystack = f"{get_value(option, 'name', '')} {get_value(option, 'category', '')}".lower()
    return 1 if any(interest.lower() in haystack for interest in interests) else 0


def _make_transport_item(option: Any, settings: PlannerSettings, suffix: str = "") -> ScheduledItem:
    source_id = str(get_value(option, "id"))
    price = get_value(option, "price", None)
    amount, unit, is_estimate = item_amount(ItemKind.TRANSPORT, price, settings.travelers)
    mode = str(get_value(option, "mode", "transport")).title()
    origin = get_value(option, "origin", "")
    destination = get_value(option, "destination", "")
    return ScheduledItem(
        item_id=f"{source_id}{suffix}",
        source_id=source_id,
        kind=ItemKind.TRANSPORT,
        title=f"{mode}: {origin} → {destination}".strip(": "),
        start=get_value(option, "depart_at"),
        end=get_value(option, "arrive_at"),
        location=None,
        unit_price=price if price is not None else unit,
        quantity=settings.travelers,
        amount=amount,
        currency=str(get_value(option, "currency", settings.currency)),
        is_estimate=is_estimate,
        category="transport",
    )


def _make_lodging_items(
    lodging: Any,
    trip: Any,
    settings: PlannerSettings,
    outbound: Any | None,
    return_option: Any | None,
    notes: list[str],
) -> list[ScheduledItem]:
    source_id = str(get_value(lodging, "id"))
    currency = str(get_value(lodging, "currency", settings.currency))
    point = to_geo(get_value(lodging, "lat", None), get_value(lodging, "lng", None))
    total = _lodging_total(lodging, trip)
    amount, unit, is_estimate = item_amount(ItemKind.LODGING, total, 1)
    start_date = get_value(trip, "start_date")
    end_date = get_value(trip, "end_date")
    name = get_value(lodging, "name", "Lodging")

    items: list[ScheduledItem] = []
    if start_date != end_date:
        configured_in = get_value(lodging, "check_in", None)
        check_in_time = configured_in.time() if isinstance(configured_in, datetime) else DEFAULT_CHECK_IN
        arrival = None
        if outbound is not None:
            arrive_at = get_value(outbound, "arrive_at", None)
            if isinstance(arrive_at, datetime):
                arrival = arrive_at + timedelta(minutes=TRANSFER_BUFFER_MINUTES)
        start_dt = _combine(start_date, check_in_time)
        if arrival is not None and arrival.date() == start_date:
            start_dt = max(start_dt, arrival)
        end_dt = start_dt + timedelta(minutes=CHECK_IN_DURATION_MINUTES)
        if end_dt <= _combine(start_date, DAY_END):
            items.append(
                ScheduledItem(
                    item_id=f"checkin:{source_id}",
                    source_id=source_id,
                    kind=ItemKind.LODGING,
                    title=f"Check in: {name}",
                    start=start_dt,
                    end=end_dt,
                    location=point,
                    unit_price=unit,
                    quantity=1,
                    amount=amount,
                    currency=currency,
                    is_estimate=is_estimate,
                    category="lodging",
                )
            )
        else:
            notes.append(f"Check-in for {name} falls outside the planning window on {start_date}.")

        configured_out = get_value(lodging, "check_out", None)
        check_out_time = (
            configured_out.time() if isinstance(configured_out, datetime) else DEFAULT_CHECK_OUT
        )
        out_start = _combine(end_date, check_out_time)
        out_end = out_start + timedelta(minutes=CHECK_OUT_DURATION_MINUTES)
        if return_option is not None:
            depart_at = get_value(return_option, "depart_at", None)
            if isinstance(depart_at, datetime) and depart_at.date() == end_date:
                latest = depart_at - timedelta(
                    minutes=TRANSFER_BUFFER_MINUTES + travel_minutes(point, None, settings.speed_kmh)
                )
                if latest < out_end:
                    out_end = max(latest, _combine(end_date, DAY_START))
                    out_start = max(_combine(end_date, DAY_START), out_end - timedelta(minutes=CHECK_OUT_DURATION_MINUTES))
        if out_end > out_start:
            items.append(
                ScheduledItem(
                    item_id=f"checkout:{source_id}",
                    source_id=source_id,
                    kind=ItemKind.LODGING,
                    title=f"Check out: {name}",
                    start=out_start,
                    end=out_end,
                    location=point,
                    unit_price=Decimal("0.00"),
                    quantity=0,
                    amount=Decimal("0.00"),
                    currency=currency,
                    is_estimate=False,
                    category="lodging",
                )
            )
        else:
            notes.append(f"Checkout for {name} could not be placed before departure.")
    return items


def _build_activity(
    option: Any,
    start: datetime,
    duration_minutes: int,
    settings: PlannerSettings,
) -> ScheduledItem:
    price = get_value(option, "price", None)
    amount, unit, price_estimate = item_amount(ItemKind.ACTIVITY, price, settings.travelers)
    _, duration_estimate = estimate_duration_minutes(duration_minutes)
    return ScheduledItem(
        item_id=str(get_value(option, "id")),
        source_id=str(get_value(option, "id")),
        kind=ItemKind.ACTIVITY,
        title=str(get_value(option, "name", "Activity")),
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        location=to_geo(get_value(option, "lat", None), get_value(option, "lng", None)),
        unit_price=price if price is not None else unit,
        quantity=settings.travelers,
        amount=amount,
        currency=str(get_value(option, "currency", settings.currency)),
        is_estimate=price_estimate or duration_estimate,
        category=str(get_value(option, "category", "activity")) or "activity",
    )


def build_schedule(planning: PlanningInput) -> ScheduleResult:
    trip = planning.trip
    start_date = get_value(trip, "start_date")
    end_date = get_value(trip, "end_date")
    preferences = planning.preferences
    pace = enum_value(
        get_value(preferences, "pace", get_value(trip, "pace", "balanced")),
        "balanced",
    )
    limit = get_value(preferences, "max_activities_per_day", None)
    pace_limit = min(
        int(limit) if limit else PACE_LIMITS.get(pace, FALLBACK_PACE_LIMIT),
        MAX_ACTIVITIES_PER_DAY,
    )
    settings = PlannerSettings(
        speed_kmh=float(
            get_value(preferences, "city_travel_speed_kmh", DEFAULT_CITY_SPEED_KMH)
            or DEFAULT_CITY_SPEED_KMH
        ),
        pace_limit=pace_limit,
        min_connection_minutes=int(
            get_value(preferences, "min_connection_minutes", DEFAULT_MIN_CONNECTION_MINUTES)
            or DEFAULT_MIN_CONNECTION_MINUTES
        ),
        travelers=max(1, int(get_value(trip, "travelers", 1) or 1)),
        currency=str(get_value(trip, "currency", "")),
        interests=tuple(get_value(preferences, "interests", ()) or ()),
    )

    result = ScheduleResult()
    dates = _inclusive_dates(start_date, end_date)
    day_map: dict[date, DayPlan] = {current: DayPlan(date=current) for current in dates}

    previous = planning.previous_plan
    rebuild_dates = set(planning.rebuild_dates)
    if previous is not None and rebuild_dates:
        preserved_dates = {planned.date for planned in previous.days} - rebuild_dates
        for planned in previous.days:
            if planned.date in preserved_dates:
                day_map[planned.date] = planned.model_copy(deep=True)
        for entry in previous.unscheduled:
            if entry.day in preserved_dates:
                result.unscheduled.append(entry)
    else:
        preserved_dates = set()

    lodging = _select_lodging(planning)
    outbound = _select_transport(planning, start_date)
    return_option = _select_transport(planning, end_date) if end_date != start_date else None

    if outbound is not None and start_date not in preserved_dates:
        day_map[start_date].items.append(_make_transport_item(outbound, settings))
    elif outbound is None:
        result.notes.append(f"No transport option found for {start_date}.")
    if return_option is not None and end_date not in preserved_dates:
        suffix = ":return" if str(get_value(return_option, "id")) == str(get_value(outbound, "id")) else ""
        day_map[end_date].items.append(_make_transport_item(return_option, settings, suffix))
    elif return_option is None and end_date != start_date:
        result.notes.append(f"No transport option found for {end_date}.")

    if lodging is not None:
        lodging_items = _make_lodging_items(
            lodging, trip, settings, outbound, return_option, result.notes
        )
        for item in lodging_items:
            if item.start.date() not in preserved_dates:
                day_map[item.start.date()].items.append(item)

    used_sources = {
        item.source_id or item.item_id
        for planned in day_map.values()
        for item in planned.items
    }
    used_sources.update(planning.cancelled_item_ids)

    hotel_point = (
        to_geo(get_value(lodging, "lat", None), get_value(lodging, "lng", None))
        if lodging is not None
        else None
    )

    candidates = [
        option
        for option in planning.experiences
        if str(get_value(option, "id")) not in used_sources
        and str(get_value(option, "id")) not in set(planning.cancelled_item_ids)
    ]
    if planning.selected_experience_ids:
        wanted = set(planning.selected_experience_ids)
        candidates = [option for option in candidates if str(get_value(option, "id")) in wanted]

    for current_day in dates:
        if current_day in preserved_dates:
            continue
        planned_day = day_map[current_day]
        planned_day.items.sort(key=lambda item: (item.start, item.end, item.item_id))
        free_intervals = _days_without_fixed(planned_day)
        remaining = list(candidates)
        activities_today = planned_day.activity_count()
        location = hotel_point

        for interval_start, interval_end in free_intervals:
            cursor = interval_start
            while activities_today < settings.pace_limit and remaining:
                next_fixed = next(
                    (item for item in planned_day.items if item.start >= cursor),
                    None,
                )
                next_fixed_location = next_fixed.location if next_fixed else None
                best: tuple[tuple[int, int, str], Any, datetime, int] | None = None
                for option in remaining:
                    point = to_geo(get_value(option, "lat", None), get_value(option, "lng", None))
                    duration, _ = estimate_duration_minutes(
                        get_value(option, "duration_minutes", None)
                    )
                    travel = travel_minutes(location, point, settings.speed_kmh)
                    arrival = cursor + timedelta(minutes=travel)
                    if arrival >= interval_end:
                        continue
                    slot = _next_open_slot(_opening_windows(option), arrival.time())
                    if slot is None:
                        continue
                    opening, closing = slot
                    activity_start = datetime.combine(current_day, opening)
                    activity_start = max(activity_start, arrival)
                    activity_end = activity_start + timedelta(minutes=duration)
                    if activity_end.time() > closing:
                        continue
                    if activity_end > interval_end:
                        continue
                    if next_fixed is not None:
                        back = travel_minutes(point, next_fixed_location, settings.speed_kmh)
                        if activity_end + timedelta(minutes=back) > next_fixed.start:
                            continue
                    rank = (travel, -_interest_score(option, settings.interests), str(get_value(option, "id")))
                    if best is None or rank < best[0]:
                        best = (rank, option, activity_start, duration)
                if best is None:
                    break
                _, option, activity_start, duration = best
                item = _build_activity(option, activity_start, duration, settings)
                planned_day.items.append(item)
                remaining.remove(option)
                candidates.remove(option)
                activities_today += 1
                cursor = item.end
                location = item.location

        for option in remaining:
            result.unscheduled.append(
                UnscheduledActivity(
                    source_id=str(get_value(option, "id")),
                    title=str(get_value(option, "name", "Activity")),
                    reason="No feasible slot within opening hours, pace limit, or travel time.",
                    day=current_day,
                )
            )
        planned_day.items.sort(key=lambda item: (item.start, item.end, item.item_id))

    result.days = [day_map[current] for current in dates]
    return result
