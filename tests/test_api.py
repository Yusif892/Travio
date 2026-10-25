from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_incomplete_trip_does_not_plan():
    response = client.post("/api/v1/trips", json={"request": {"destination": "Rome"}, "message": "plan a trip"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "clarification_needed"
    assert body["tasks"] == []
    assert "origin" in body["missing_fields"]


def test_continue_preserves_existing_request():
    response = client.post("/api/v1/trips", json={"request": {"origin": "Cairo"}, "message": "plan travel"})
    trip_id = response.json()["trip_id"]
    continued = client.post(f"/api/v1/trips/{trip_id}/messages", json={"message": "Here are the missing details", "request": {"destination": "Rome", "departure_date": "2027-05-01", "return_date": "2027-05-07", "budget": "1500", "travelers": 2}})
    assert continued.status_code == 200
    assert continued.json()["status"] == "accepted"
