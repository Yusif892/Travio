from __future__ import annotations

import itertools
from datetime import time

from app.planner.geo import travel_minutes
from app.planner.models import ItemKind
from app.planner.service import Planner

from tests.factories import (
    D1,
    D2,
    D3,
    D4,
    make_experience,
    make_planning,
    make_preferences,
)


def _all_items(plan):
    return [item for day in plan.days for item in day.items]


def _activities(day):
    return [item for item in day.items if item.kind is ItemKind.ACTIVITY]


def _overlaps(first, second) -> bool:
    return first.start < second.end and second.start < first.end


def test_fixed_events_are_placed_first_and_not_overlapped():
    plan = Planner().plan(make_planning())
    assert [day.date for day in plan.days] == [D1, D2, D3, D4]

    first_day = plan.day(D1)
    transport = [item for item in first_day.items if item.kind is ItemKind.TRANSPORT]
    checkin = [item for item in first_day.items if item.item_id.startswith("checkin:")]
    assert transport and transport[0].start.hour == 8
    assert checkin and checkin[0].start.hour == 15

    fixed = transport + checkin
    for activity in _activities(first_day):
        for event in fixed:
            assert not _overlaps(activity, event)

    last_day = plan.day(D4)
    assert any(item.kind is ItemKind.TRANSPORT for item in last_day.items)
    assert any(item.item_id.startswith("checkout:") for item in last_day.items)


def test_slots_never_overlap():
    plan = Planner().plan(make_planning())
    for day in plan.days:
        ordered = sorted(day.items, key=lambda item: item.start)
        for previous, current in itertools.pairwise(ordered):
            assert not _overlaps(previous, current)


def test_activity_gaps_respect_travel_time():
    experiences = (
        make_experience("e1", "A", 41.8902, 12.4922),
        make_experience("e2", "B", 41.9000, 12.5000),
        make_experience("e3", "C", 41.9100, 12.5100),
        make_experience("e4", "D", 41.9200, 12.5200),
        make_experience("e5", "E", 41.9300, 12.5300),
    )
    plan = Planner().plan(
        make_planning(experiences=experiences, preferences=make_preferences(pace="packed"))
    )
    for day in plan.days:
        activities = _activities(day)
        for previous, current in itertools.pairwise(activities):
            gap = int((current.start - previous.end).total_seconds() // 60)
            assert gap >= travel_minutes(previous.location, current.location, 20.0)


def test_activity_stays_inside_opening_hours():
    experience = make_experience(
        "e1",
        "Morning museum",
        opening_hours=[(time(10, 0), time(13, 0))],
        duration_minutes=120,
    )
    plan = Planner().plan(
        make_planning(
            experiences=(experience,),
            preferences=make_preferences(max_activities_per_day=1),
        )
    )
    scheduled = _all_items(plan)
    activity = next(item for item in scheduled if item.kind is ItemKind.ACTIVITY)
    assert activity.start.time() >= time(10, 0)
    assert activity.end.time() <= time(13, 0)


def test_pace_preference_caps_activities_per_day():
    experiences = tuple(
        make_experience(f"e{index}", f"Activity {index}", 41.89 + index * 0.001, 12.49)
        for index in range(1, 9)
    )
    plan = Planner().plan(
        make_planning(experiences=experiences, preferences=make_preferences(pace="relaxed"))
    )
    assert all(day.activity_count() <= 2 for day in plan.days)
    assert sum(day.activity_count() for day in plan.days) >= 4


def test_nearby_activity_is_grouped_first():
    near = make_experience("near", "Near", 41.8902, 12.4922)
    far = make_experience("far", "Far", 42.5000, 13.5000)
    plan = Planner().plan(
        make_planning(
            experiences=(far, near),
            preferences=make_preferences(max_activities_per_day=1),
        )
    )
    first_day_activities = _activities(plan.day(D1))
    assert first_day_activities
    assert first_day_activities[0].source_id == "near"


def test_preserved_days_are_copied_verbatim():
    planner = Planner()
    planning = make_planning()
    original = planner.plan(planning)

    locked = original.model_copy(deep=True)
    locked.days[0].items[0].title = "LOCKED BY FEEDBACK"
    locked_day_two = locked.day(D2).model_dump()

    replanned = planner.plan(
        planning.with_changes(previous_plan=locked, rebuild_dates=frozenset({D2}))
    )

    assert replanned.days[0].items[0].title == "LOCKED BY FEEDBACK"
    assert replanned.day(D3).model_dump() == locked.day(D3).model_dump()
    assert replanned.day(D4).model_dump() == locked.day(D4).model_dump()
    assert isinstance(locked_day_two, dict)
