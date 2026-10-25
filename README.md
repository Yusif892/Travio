# TRAVIO

## Local development

Create a Python 3.11+ virtual environment, install dependencies, then run:

```powershell
$env:PYTHONPATH = "backend"
uvicorn app.main:app --app-dir backend --reload
pytest tests
```

The initial API contract is `POST /api/v1/trips` and
`POST /api/v1/trips/{trip_id}/messages`. Intake guardrails are deterministic:
requests missing origin, destination, dates, budget, or travellers receive a
clarification response, and unsafe/off-topic requests are rejected. Neither
outcome invokes planning agents.

Persistence is currently an in-memory adapter; replace it with the project
PostgreSQL repository while retaining the `TripRecord` contract and ownership
checks. Booking is explicitly outside this service and no endpoint claims a
booking occurred.
