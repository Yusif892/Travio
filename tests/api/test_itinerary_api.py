from __future__ import annotations

from types import SimpleNamespace

from app.api.deps import get_trip_repository
from app.main import app
from app.planner.service import Planner
from fastapi.testclient import TestClient

from tests.factories import make_planning


class FakeRepository:
    def __init__(self, state) -> None:
        self.state = state
        self.saved = []

    def load_state(self, trip_id: str):
        return self.state if trip_id == "trip-1" else None

    def save_itinerary(self, trip_id: str, itinerary) -> None:
        self.saved.append(itinerary)


def _state(planning, plan):
    return SimpleNamespace(
        trip_request=planning.trip,
        transport_options=list(planning.transport),
        lodging_options=list(planning.lodging),
        experience_options=list(planning.experiences),
        preferences=planning.preferences,
        itinerary=plan,
    )


def _client_with(repo) -> TestClient:
    app.dependency_overrides[get_trip_repository] = lambda: repo
    return TestClient(app)


def test_get_itinerary_returns_plan():
    planning = make_planning()
    plan = Planner().plan(planning, trip_id="trip-1")
    client = _client_with(FakeRepository(_state(planning, plan)))
    try:
        response = client.get("/api/v1/trips/trip-1/itinerary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["trip_id"] == "trip-1"
    assert len(body["days"]) == 4
    assert "cost" in body


def test_get_itinerary_returns_404_for_unknown_trip():
    client = _client_with(FakeRepository(None))
    try:
        response = client.get("/api/v1/trips/missing/itinerary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
