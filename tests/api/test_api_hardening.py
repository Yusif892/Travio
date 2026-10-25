from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.api.deps import get_trip_repository, get_verifier
from app.api.idempotency import IdempotencyStore, get_idempotency_store
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


def _state(planning, plan, **overrides):
    values = {
        "trip_request": planning.trip,
        "transport_options": list(planning.transport),
        "lodging_options": list(planning.lodging),
        "experience_options": list(planning.experiences),
        "preferences": planning.preferences,
        "itinerary": plan,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _setup(options=None, **state_overrides):
    l1 = make_lodging("l1", "Hotel Roma", total_price=Decimal("360.00"))
    l2 = make_lodging(
        "l2",
        "Budget Inn",
        total_price=Decimal("240.00"),
        nightly_price=Decimal("80.00"),
    )
    planning = make_planning(
        lodging=(l1, l2),
        selected_lodging_id="l1",
        **({} if options is None else options),
    )
    plan = Planner().plan(planning, trip_id="trip-1")
    repo = FakeRepository(_state(planning, plan, **state_overrides))
    store = IdempotencyStore()
    app.dependency_overrides[get_trip_repository] = lambda: repo
    app.dependency_overrides[get_verifier] = lambda: AcceptingVerifier()
    app.dependency_overrides[get_idempotency_store] = lambda: store
    return repo, TestClient(app)


def test_blank_feedback_message_is_rejected():
    repo, client = _setup()
    try:
        response = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "   "},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert repo.saved == []


def test_stale_expected_version_returns_409_without_saving():
    repo, client = _setup()
    try:
        response = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper", "expected_version": 99},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "version conflict" in response.json()["detail"]
    assert repo.saved == []


def test_idempotency_key_replays_without_saving_twice():
    repo, client = _setup()
    headers = {"Idempotency-Key": "feedback-1"}
    try:
        first = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper"},
            headers=headers,
        )
        second = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(repo.saved) == 1


def test_invalid_idempotency_key_is_rejected():
    repo, client = _setup()
    try:
        response = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper"},
            headers={"Idempotency-Key": "bad key with spaces"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert repo.saved == []


def test_auth_is_required_when_configured(monkeypatch):
    monkeypatch.setenv("TRAVIO_API_KEY", "secret-key")
    monkeypatch.setenv("TRAVIO_REQUIRE_AUTH", "1")
    repo, client = _setup()
    try:
        missing = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper"},
        )
        allowed = client.post(
            "/api/v1/trips/trip-1/feedback",
            json={"message": "make the hotel cheaper"},
            headers={"X-API-Key": "secret-key", "X-User-Id": "alice"},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert allowed.status_code == 200


def test_trip_owned_by_another_user_is_hidden():
    repo, client = _setup(owner_id="alice")
    try:
        forbidden = client.get(
            "/api/v1/trips/trip-1/itinerary",
            headers={"X-User-Id": "bob"},
        )
        allowed = client.get(
            "/api/v1/trips/trip-1/itinerary",
            headers={"X-User-Id": "alice"},
        )
    finally:
        app.dependency_overrides.clear()

    assert forbidden.status_code == 404
    assert allowed.status_code == 200
    assert repo.state.owner_id == "alice"
