from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.api.deps import get_trip_repository, get_verifier
from app.main import app
from app.planner.service import Planner
from fastapi.testclient import TestClient

from tests.factories import make_lodging, make_planning


class FakeRepository:
    def __init__(self, state) -> None:
        self.state = state
        self.saved = []

    def load_state(self, trip_id: str):
        return self.state if trip_id == "trip-1" else None

    def save_itinerary(self, trip_id: str, itinerary) -> None:
        self.saved.append(itinerary)


class AcceptingVerifier:
    def __call__(self, items):
        return {item.item_id: {"passed": True, "reason": None} for item in items}


def _state(planning, plan):
    return SimpleNamespace(
        trip_request=planning.trip,
        transport_options=list(planning.transport),
        lodging_options=list(planning.lodging),
        experience_options=list(planning.experiences),
        preferences=planning.preferences,
        itinerary=plan,
    )


def _cheaper_lodging_setup():
    l1 = make_lodging("l1", "Hotel Roma", total_price=Decimal("360.00"))
    l2 = make_lodging(
        "l2",
        "Budget Inn",
        total_price=Decimal("240.00"),
        nightly_price=Decimal("80.00"),
    )
    planning = make_planning(lodging=(l1, l2), selected_lodging_id="l1")
    plan = Planner().plan(planning, trip_id="trip-1")
    repo = FakeRepository(_state(planning, plan))
    app.dependency_overrides[get_trip_repository] = lambda: repo
    app.dependency_overrides[get_verifier] = lambda: AcceptingVerifier()
    return repo, TestClient(app)


def test_feedback_routes_change_and_requires_new_approval():
    repo, client = _cheaper_lodging_setup()
    try:
        response = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"]["affected_task_ids"] == ["accommodation"]
    assert body["approval_required"] is True
    assert body["changed_days"]
    assert len(repo.saved) == 1
    assert repo.saved[0].cost.by_category["lodging"] == Decimal("240.00")


def test_ambiguous_feedback_returns_clarification_without_saving():
    repo, client = _cheaper_lodging_setup()
    try:
        response = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "change it"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["needs_clarification"] is True
    assert body["changed_days"] == []
    assert body["clarification"]
    assert repo.saved == []


def test_feedback_returns_404_for_unknown_trip():
    _repo, client = _cheaper_lodging_setup()
    try:
        response = client.post(
            "/api/v1/trips/unknown/feedback",
            json={"message": "make the hotel cheaper"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
