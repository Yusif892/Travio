from datetime import datetime, time, timedelta

import pytest
from pydantic import BaseModel

from backend.app.reliability.checks import Activity, Itinerary, check_budget, check_opening_hours, check_timing, verify_itinerary
from backend.app.reliability.contracts import RetryConfig
from backend.app.reliability.errors import RetryExhaustedError, ToolNotAllowedError
from backend.app. reliability.freshness import FetchedItem, find_stale
from backend.app.reliability.middleware import call_tool, redact_pii
from backend.app.reliability.retry import IdempotencyStore, RetryTracker, fallback_for

D = datetime(2026, 12, 1, 9, 0)
from typing import Any

def act(**kw: Any) -> Activity:
    base: dict[str, Any] = dict(name="A", start=D, end=D + timedelta(hours=1))
    base.update(kw)
    return Activity(**base)



def itin(acts, budget=100.0):
    return Itinerary(acts, budget, D - timedelta(days=1), D + timedelta(days=3))


# ---- boundary values ----
def test_budget_exactly_at_limit_passes():
    assert check_budget(itin([act(cost=100.0)])).passed


def test_budget_over_limit_fails():
    assert not check_budget(itin([act(cost=100.01)])).passed


def test_closing_exactly_at_activity_end_passes():
    a = act(opens=time(9, 0), closes=time(10, 0))
    assert check_opening_hours(itin([a])).passed


def test_activity_after_closing_fails():
    a = act(opens=time(9, 0), closes=time(9, 30))
    assert not check_opening_hours(itin([a])).passed


def test_overlap_detected():
    a, b = act(name="A"), act(name="B", start=D + timedelta(minutes=30), end=D + timedelta(hours=2))
    assert not check_timing(itin([a, b])).passed


def test_unsafe_is_critical():
    r = verify_itinerary(itin([act(unsafe=True)]))
    assert not r.passed and r.severity.value == "critical"


# ---- stale data ----
def test_stale_data_triggers_targeted_refetch():
    now = D
    items = [
        FetchedItem("p1", "price", "get_price", now - timedelta(hours=2)),      # stale
        FetchedItem("h1", "opening_hours", "get_hours", now - timedelta(hours=2)),  # fresh
    ]
    reqs = find_stale(items, now)
    assert [r.item_id for r in reqs] == ["p1"]


def test_exactly_max_age_is_fresh():
    assert find_stale([FetchedItem("p", "price", "t", D - timedelta(hours=1))], D) == []


# ---- middleware ----
class Out(BaseModel):
    value: int


def make_call(fn, tracker, **kw):
    return call_tool(agent="planner", tool="search_places", fn=fn, args={}, output_model=Out,
                     task_id="t1", tracker=tracker, sleep=lambda s: None, **kw)


def fast_tracker(n=3):
    return RetryTracker(RetryConfig(max_attempts=n, timeout_s=1))


def test_success():
    assert make_call(lambda: {"value": 1}, fast_tracker()).value == 1


def test_retry_exhaustion_returns_fallback():
    t = fast_tracker(3)
    with pytest.raises(RetryExhaustedError) as e:
        make_call(lambda: (_ for _ in ()).throw(RuntimeError("boom")), t)
    assert e.value.attempts == 3
    assert fallback_for(e.value)["escalate"] is True


def test_malformed_output_rejected():
    with pytest.raises(RetryExhaustedError):
        make_call(lambda: {"value": "not-an-int"}, fast_tracker(2))


def test_tool_failure_then_recovery():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("temporary")
        return {"value": 7}

    assert make_call(flaky, fast_tracker()).value == 7


def test_timeout():
    import time as _t
    t = RetryTracker(RetryConfig(max_attempts=1, timeout_s=0.05))
    with pytest.raises(RetryExhaustedError):
        make_call(lambda: _t.sleep(0.3) or {"value": 1}, t)


def test_allowlist_blocks_other_tools():
    with pytest.raises(ToolNotAllowedError):
        call_tool(agent="planner", tool="book_hotel", fn=lambda: {}, args={}, output_model=Out,
                  task_id="x", tracker=fast_tracker())


def test_booking_retry_does_not_book_twice():
    count = {"n": 0}

    def book():
        count["n"] += 1
        return {"value": count["n"]}

    store, t = IdempotencyStore(), fast_tracker()
    for _ in range(2):
        call_tool(agent="booking", tool="book_hotel", fn=book, args={}, output_model=Out,
                  task_id="b1", tracker=t, idempotency_key="trip42-hotel", store=store)
    assert count["n"] == 1


def test_pii_redaction():
    out = redact_pii("mail me at ali@example.com or +20 100 123 4567")
    assert "ali@example.com" not in out and "123 4567" not in out


def test_retry_counters_are_per_task():
    t = fast_tracker()
    t.record_attempt("a"); t.record_attempt("a")
    assert t.attempts("a") == 2 and t.attempts("b") == 0
