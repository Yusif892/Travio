"""PostgreSQL-backed trip store / repository tests (need TEST_DATABASE_URL)."""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.enums import TaskAgent, TaskStatus
from app.domain.schemas import PlanningTask, TripRecord, TripRequest, WorkflowError
from app.persistence.migrate import apply_migrations
from app.persistence.repository import (
    ItineraryConflictError,
    PostgresTripRepository,
    PostgresTripStore,
    TripNotFoundError,
)
from app.planner.models import CostBreakdown, Itinerary


@pytest.fixture
def pool(clean_db):
    apply_migrations(clean_db)
    connection_pool = ConnectionPool(clean_db, min_size=1, max_size=3, kwargs={"row_factory": dict_row}, open=True)
    yield connection_pool
    connection_pool.close()


@pytest.fixture
def store(pool):
    return PostgresTripStore(pool)


@pytest.fixture
def repo(pool):
    return PostgresTripRepository(pool)


def make_record(user_id="alice", **overrides) -> TripRecord:
    values = dict(
        user_id=user_id,
        trip_request=TripRequest(origin="Cairo", destination="Rome", departure_date=date(2027, 5, 1),
                                 return_date=date(2027, 5, 7), budget=Decimal("1500"), travelers=2),
        messages=[{"role": "user", "content": "plan my trip"}],
        tasks=[PlanningTask(id="transportation", agent=TaskAgent.TRANSPORTATION, status=TaskStatus.SUCCEEDED)],
        errors=[WorkflowError(code="agent_failed", message="boom", task_id="transportation")],
    )
    values.update(overrides)
    return TripRecord(**values)


def make_itinerary(trip_id, version=1, notes=None) -> Itinerary:
    return Itinerary(trip_id=str(trip_id), version=version, currency="EUR",
                     cost=CostBreakdown(currency="EUR", total=Decimal("100.00")), notes=notes or [])


# ---- trip store ---------------------------------------------------------

def test_create_and_get_round_trip(store):
    record = store.create(make_record())
    loaded = store.get(record.trip_id, "alice")
    assert loaded is not None and loaded.model_dump() == record.model_dump()


def test_other_users_cannot_read_a_trip(store):
    record = store.create(make_record("alice"))
    assert store.get(record.trip_id, "bob") is None
    assert store.get(record.trip_id, None) is None
    assert store.get(record.trip_id, "alice") is not None


def test_anonymous_trips_are_only_visible_to_anonymous_callers(store):
    record = store.create(make_record(user_id=None))
    loaded = store.get(record.trip_id, None)
    assert loaded is not None and loaded.user_id is None
    assert store.get(record.trip_id, "bob") is None


def test_save_updates_fields(store):
    record = store.create(make_record())
    record.messages.append({"role": "user", "content": "cheaper hotel"})
    record.lodging_options = [{"id": "h1", "name": "Hotel Roma"}]
    store.save(record)
    loaded = store.get(record.trip_id, "alice")
    assert loaded.messages[-1]["content"] == "cheaper hotel"
    assert loaded.lodging_options == [{"id": "h1", "name": "Hotel Roma"}]


def test_save_cannot_take_over_another_users_trip(store):
    record = store.create(make_record("alice"))
    hijack = record.model_copy(update={"user_id": "mallory", "messages": [{"role": "user", "content": "pwned"}]})
    with pytest.raises(TripNotFoundError):
        store.save(hijack)
    assert store.get(record.trip_id, "alice").messages[0]["content"] == "plan my trip"


def test_save_unknown_trip_raises(store):
    with pytest.raises(TripNotFoundError):
        store.save(make_record())


def test_thread_id_must_be_unique(store):
    first = store.create(make_record())
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.create(make_record("bob", thread_id=first.thread_id))


def test_data_survives_a_new_connection_pool(store, clean_db):
    record = store.create(make_record())
    fresh = ConnectionPool(clean_db, min_size=1, max_size=1, open=True)
    try:
        assert PostgresTripStore(fresh).get(record.trip_id, "alice") is not None
    finally:
        fresh.close()


def test_list_trips_is_isolated_and_newest_first(store):
    first = store.create(make_record("alice"))
    second = store.create(make_record("alice"))
    store.create(make_record("bob"))
    ids = [row["trip_id"] for row in store.list_trips("alice")]
    assert ids == [second.trip_id, first.trip_id]
    assert store.list_trips("nobody") == []


# ---- repository used by the itinerary / feedback API -------------------------

def test_load_state_exposes_planner_shape(store, repo):
    record = make_record(lodging_options=[{"id": "h1", "check_in": "2027-05-01T14:00:00"}])
    store.create(record)
    state = repo.load_state(str(record.trip_id))
    assert state["owner_id"] == "alice" and state["itinerary"] is None
    assert state["trip_request"]["start_date"] == date(2027, 5, 1)
    assert state["lodging_options"][0]["check_in"].hour == 14


def test_load_state_returns_none_for_unknown_or_malformed_ids(repo):
    assert repo.load_state("trip-1") is None
    assert repo.load_state(str(uuid4())) is None


def test_save_itinerary_stores_versions_and_updates_current(store, repo, pool):
    record = store.create(make_record())
    repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 1))
    repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 2, notes=["v2"]))
    state = repo.load_state(str(record.trip_id))
    assert state["itinerary"].version == 2 and state["itinerary"].notes == ["v2"]
    with pool.connection() as conn:
        count = conn.execute("select count(*) from itinerary_versions where trip_id = %s", (record.trip_id,)).fetchone()
    assert list(count.values())[0] == 2


def test_save_itinerary_is_idempotent(store, repo, pool):
    record = store.create(make_record())
    itinerary = make_itinerary(record.trip_id)
    repo.save_itinerary(str(record.trip_id), itinerary)
    repo.save_itinerary(str(record.trip_id), itinerary)
    with pool.connection() as conn:
        count = conn.execute("select count(*) from itinerary_versions").fetchone()
    assert list(count.values())[0] == 1


def test_saved_version_cannot_be_overwritten_or_rolled_back(store, repo):
    record = store.create(make_record())
    repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 1))
    with pytest.raises(ItineraryConflictError):
        repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 1, notes=["tampered"]))
    repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 2))
    with pytest.raises(ItineraryConflictError):
        repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 1, notes=["old"]))


def test_save_itinerary_rejects_wrong_or_unknown_trip(store, repo):
    record = store.create(make_record())
    with pytest.raises(ValueError):
        repo.save_itinerary(str(record.trip_id), make_itinerary(uuid4()))
    ghost = uuid4()
    with pytest.raises(TripNotFoundError):
        repo.save_itinerary(str(ghost), make_itinerary(ghost))
    with pytest.raises(TripNotFoundError):
        repo.save_itinerary("trip-1", make_itinerary(ghost))


def test_store_save_does_not_roll_back_a_newer_itinerary(store, repo):
    record = store.create(make_record())
    stale = store.get(record.trip_id, "alice")
    repo.save_itinerary(str(record.trip_id), make_itinerary(record.trip_id, 1))
    store.save(stale)  # stale copy has no itinerary
    assert repo.load_state(str(record.trip_id))["itinerary"].version == 1


def test_database_failure_rolls_back_the_whole_save(store, repo, pool):
    record = store.create(make_record())
    with pytest.raises(psycopg.errors.CheckViolation):
        # a negative budget violates the CHECK constraint -> the update is rolled back
        broken = record.model_copy(deep=True)
        broken.trip_request = TripRequest.model_construct(budget=Decimal("-5"))
        store.save(broken)
    assert store.get(record.trip_id, "alice").trip_request.budget == Decimal("1500")