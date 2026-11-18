"""Pure conversion tests: no database required."""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from app.domain.enums import TaskAgent, TaskStatus
from app.domain.schemas import PlanningTask, TripRecord, TripRequest, WorkflowError
from app.persistence import codec
from app.planner.models import CostBreakdown, Itinerary


def _record(user_id="alice") -> TripRecord:
    return TripRecord(
        user_id=user_id,
        trip_request=TripRequest(origin="Cairo", destination="Rome", departure_date=date(2027, 5, 1),
                                 return_date=date(2027, 5, 7), budget=Decimal("1500"), travelers=2),
        messages=[{"role": "user", "content": "plan"}],
        tasks=[PlanningTask(id="transportation", agent=TaskAgent.TRANSPORTATION, status=TaskStatus.SUCCEEDED)],
        errors=[WorkflowError(code="x", message="boom", task_id="transportation")],
    )


def _row(record: TripRecord) -> dict:
    params = codec.record_to_params(record)
    row = dict(params)
    row["itinerary"] = params["itinerary"]
    return row


def test_owner_defaults_to_anonymous():
    assert codec.owner_of(None) == codec.ANONYMOUS_USER
    assert codec.owner_of("  ") == codec.ANONYMOUS_USER
    assert codec.owner_of(" bob ") == "bob"


def test_record_round_trip():
    record = _record()
    restored = codec.row_to_record(_row(record))
    assert restored.model_dump() == record.model_dump()


def test_anonymous_record_round_trip_keeps_user_none():
    record = _record(user_id=None)
    row = _row(record)
    assert row["user_id"] == codec.ANONYMOUS_USER
    assert codec.row_to_record(row).user_id is None


def test_params_flatten_request_columns():
    params = codec.record_to_params(_record())
    assert params["destination"] == "Rome" and params["travelers"] == 2
    assert params["departure_date"] == date(2027, 5, 1)
    assert params["trip_request"]["budget"] == "1500"  # JSON-safe


def test_decode_option_parses_iso_datetimes_and_normalises_to_naive_utc():
    option = codec.decode_option({"id": "f1", "depart_at": "2027-05-01T08:00:00",
                                  "arrive_at": "2027-05-01T11:00:00Z", "price": "200.00"})
    assert option["depart_at"] == datetime(2027, 5, 1, 8, 0)
    assert option["arrive_at"] == datetime(2027, 5, 1, 11, 0) and option["arrive_at"].tzinfo is None
    assert option["price"] == "200.00"
    assert codec.decode_option({"check_in": "not-a-date"})["check_in"] == "not-a-date"


def test_state_from_row_exposes_planner_field_names():
    record = _record()
    row = _row(record)
    row["lodging_options"] = [{"id": "h1", "check_in": "2027-05-01T14:00:00"}]
    state = codec.state_from_row(row)
    trip = state["trip_request"]
    assert trip["start_date"] == date(2027, 5, 1) and trip["end_date"] == date(2027, 5, 7)
    assert trip["currency"] == codec.DEFAULT_CURRENCY and trip["trip_id"] == str(record.trip_id)
    assert state["owner_id"] == "alice" and state["itinerary"] is None
    assert state["lodging_options"][0]["check_in"] == datetime(2027, 5, 1, 14, 0)


def test_anonymous_trip_has_no_owner_in_state():
    state = codec.state_from_row(_row(_record(user_id=None)))
    assert state["owner_id"] is None  # enforce_owner() then lets anonymous callers through


def test_itinerary_digest_is_stable_and_content_sensitive():
    trip_id = str(uuid4())
    make = lambda notes: Itinerary(trip_id=trip_id, version=1, currency="eur",
                                   cost=CostBreakdown(currency="EUR", total=Decimal("12.50")), notes=notes)
    content, digest, total, currency = codec.itinerary_digest(make([]))
    assert len(digest) == 64 and total == Decimal("12.50") and currency == "EUR"
    assert content["trip_id"] == trip_id
    assert codec.itinerary_digest(make([]))[1] == digest
    assert codec.itinerary_digest(make(["changed"]))[1] != digest
    assert codec.itinerary_digest(Itinerary(trip_id=trip_id, cost=CostBreakdown(currency="")))[3] is None