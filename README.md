# TRAVIO

TRAVIO is an AI-assisted travel-planning backend. It collects a structured trip
request, runs deterministic intake guardrails, fans out planning work to
specialised agents, and builds a day-by-day itinerary with costs, conflicts, and
explanations. Travellers can then submit natural-language feedback to replan
only the affected parts of the trip.

The API is built with FastAPI, orchestration uses LangGraph, and persistence
targets PostgreSQL.

## Highlights

- **Deterministic intake guardrails** — travel scope, prompt-injection markers,
  and required fields are checked in code before any agent runs.
- **Parallel planning** — a supervisor produces allow-listed tasks for
  transportation, accommodation, and experiences; independent tasks run
  concurrently and write to separate state fields.
- **Deterministic planner** — scheduling, opening hours, travel time, budget
  arithmetic, and conflict detection are plain Python, not model calls.
- **Targeted feedback replanning** — feedback is parsed, routed to the affected
  domain, re-verified, and saved as a new itinerary version while unchanged days
  stay intact.
- **PostgreSQL schema and migrations** — trips, immutable itinerary versions,
  approvals, preferences, and feedback, with a checksum-verified migration
  runner.
- **API hardening** — ownership checks, optional API-key auth, request
  validation, and idempotent feedback submissions.

## Architecture

```text
Client
  |
  v
FastAPI (/api/v1)
  |
  +-- POST /trips -----------------> intake guardrails (deterministic)
  |                                    | accepted
  |                                    v
  |                                 LangGraph workflow
  |                                    | supervisor (task decomposition)
  |                                    v
  |                                 parallel fan-out
  |                              transportation | accommodation | experiences
  |                                    | join
  |                                    v
  |                                 assemble TripRecord
  |
  +-- GET  /trips/{id}/itinerary --> trip repository -> Itinerary
  |
  +-- POST /trips/{id}/feedback ---> parser -> router -> replanner
                                       -> re-verify changed items
                                       -> new itinerary version
```

Design principles:

- Code owns validation, scheduling, money, and budget checks. The LLM is used
  only where language is unavoidable (optional explanation writing and optional
  feedback classification), and always has a deterministic fallback.
- Money uses `Decimal`; currencies are ISO 4217 codes; planner datetimes are
  naive UTC.
- Each agent owns one output field, so concurrent writes cannot clobber another
  domain's results.
- Failures are data: a failed agent or tool becomes a per-task `errors` entry
  while successful sibling results remain usable.

## Tech stack

| Area           | Technology                               |
| -------------- | ---------------------------------------- |
| Language       | Python 3.11+                             |
| API            | FastAPI, Uvicorn, Pydantic v2            |
| Orchestration  | LangGraph, LangChain                     |
| LLM (optional) | Groq (`llama-3.1-8b-instant` by default) |
| Database       | PostgreSQL, psycopg 3, psycopg_pool      |
| HTTP client    | httpx, requests                          |
| Testing        | pytest, httpx TestClient                 |
| Linting        | Ruff                                     |

## Project layout

```text
travio/
├── backend/app/
│   ├── main.py                 # FastAPI app and /health
│   ├── api/                    # Routers, endpoints, auth, idempotency, adapters
│   ├── agents/                 # Supervisor and domain agents (provider seams)
│   ├── domain/                 # Trip schemas, enums, TravelState
│   ├── graph/                  # LangGraph supervisor fan-out/fan-in workflow
│   ├── services/               # Intake guardrails, orchestration, in-memory store
│   ├── planner/                # Scheduling, costs, conflicts, explanations, LLM
│   ├── feedback/               # Feedback parsing, routing, replanning
│   ├── persistence/            # DB connections and migration runner
│   ├── providers/              # External provider adapters (placeholder)
│   ├── verification/           # Verification adapter (placeholder)
│   └── booking/                # Booking workflow (placeholder)
├── db/migrations/              # Checksum-tracked SQL migrations
├── tests/
│   ├── unit/                   # Planner and feedback unit tests
│   ├── api/                    # API contract and hardening tests
│   └── integration/            # PostgreSQL migration/schema tests
├── docs/                       # Feature plan, user stories, folder guide
├── frontend/                   # UI placeholder
├── requirements.txt
├── pytest.ini
└── .env.example
```

See [docs/folder-guide.md](docs/folder-guide.md) for the directory conventions.

## Getting started

### Prerequisites

- Python 3.11 or newer
- PostgreSQL 14+ (only needed for persistence and integration tests)
- Optional: a Groq API key for LLM-written explanations

### Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in the values you need. The application starts without
`GROQ_API_KEY`; explanations fall back to deterministic text.

### Run the API

```powershell
$env:PYTHONPATH = "backend"
uvicorn app.main:app --app-dir backend --reload
```

- API root: `http://127.0.0.1:8000`
- Health check: `GET http://127.0.0.1:8000/health`
- OpenAPI docs: `http://127.0.0.1:8000/docs`

### Run tests

```powershell
python -m pytest -q
```

`pytest.ini` already adds `backend` to `pythonpath`, so no environment variable
is needed for the test run.

- Unit and API tests run without a database.
- PostgreSQL integration tests are skipped unless `TEST_DATABASE_URL` is set.
- The integration fixture **drops the `public` schema** before each test and
  refuses to run unless the database name ends with `_test`.

Run only fast tests:

```powershell
python -m pytest tests/unit tests/api -q
```

Run integration tests against a disposable test database:

```powershell
$env:TEST_DATABASE_URL = "postgresql://user:password@localhost:5432/travio_test"
python -m pytest tests/integration -q
```

### Apply database migrations

```powershell
$env:PYTHONPATH = "backend"
python -m app.persistence.migrate          # uses DATABASE_URL
python -m app.persistence.migrate --test   # uses TEST_DATABASE_URL
```

The runner applies `db/migrations/*.sql` in filename order, one transaction per
file, records a SHA-256 checksum for each applied file, and refuses to continue
if an applied migration was edited afterwards. Add a new numbered migration
instead of editing history.

## Configuration

Environment variables are read from the process environment and, when present,
a git-ignored `.env` file at the repository root.

| Variable                | Required              | Purpose                                                                   |
| ----------------------- | --------------------- | ------------------------------------------------------------------------- |
| `DATABASE_URL`          | For persistence       | Main PostgreSQL DSN                                                       |
| `TEST_DATABASE_URL`     | For integration tests | Test DSN; database name must end in `_test`                               |
| `GROQ_API_KEY`          | No                    | Enables Groq-generated explanations                                       |
| `GROQ_MODEL`            | No                    | Overrides the default Groq model                                          |
| `TAVILY_API_KEY`        | No                    | Web search provider for future agents                                     |
| `AVIATIONSTACK_API_KEY` | No                    | Flight data provider for future agents                                    |
| `DEFAULT_ORIGIN_DATA`   | No                    | Default origin hint for agents                                            |
| `LANGSMITH_TRACING`     | No                    | Enables LangSmith tracing                                                 |
| `LANGSMITH_ENDPOINT`    | No                    | LangSmith API endpoint                                                    |
| `LANGSMITH_API_KEY`     | No                    | LangSmith API key                                                         |
| `LANGSMITH_PROJECT`     | No                    | LangSmith project name                                                    |
| `TRAVIO_API_KEY`        | No                    | When set, requests must send `X-API-Key` or `Authorization: Bearer <key>` |
| `TRAVIO_REQUIRE_AUTH`   | No                    | When true, API key and `X-User-Id` are mandatory                          |

Never commit real secrets. `.env` and key files are ignored by Git.

## API

All routes are under `/api/v1`.

| Method | Path                         | Description                                                |
| ------ | ---------------------------- | ---------------------------------------------------------- |
| `POST` | `/trips`                     | Create a trip, run intake guardrails, and plan if accepted |
| `POST` | `/trips/{trip_id}/messages`  | Continue a trip with more details or a request patch       |
| `GET`  | `/trips/{trip_id}/itinerary` | Fetch the latest itinerary                                 |
| `POST` | `/trips/{trip_id}/feedback`  | Replan in response to natural-language feedback            |
| `GET`  | `/health`                    | Liveness check (outside `/api/v1`)                         |

### Trip intake

`POST /api/v1/trips` accepts a structured request and an optional message.

```json
{
  "user_id": "demo-user",
  "message": "Plan my complete trip",
  "request": {
    "origin": "Cairo",
    "destination": "Rome",
    "departure_date": "2027-05-01",
    "return_date": "2027-05-07",
    "budget": "1500.00",
    "travelers": 2,
    "preferences": ["museums", "local food"]
  }
}
```

Response (`201 Created`):

```json
{
  "trip_id": "2f1c...",
  "thread_id": "9a8b...",
  "status": "accepted",
  "message": "Your travel request is ready for planning.",
  "missing_fields": [],
  "tasks": [
    {
      "id": "transportation",
      "agent": "transportation",
      "status": "failed",
      "retry_count": 0
    }
  ],
  "errors": []
}
```

`status` is one of:

- `accepted` — all required fields are present; the planning workflow runs.
- `clarification_needed` — `missing_fields` lists what the user must provide.
- `rejected` — the request is unsafe, off-topic, or contains injection markers.

Rejected and clarification responses never invoke planning agents. Optional
auth is enforced through `get_current_user`; trip ownership uses `X-User-Id`.

Required trip fields: `origin`, `destination`, both dates, `budget`, and
`travelers`.

### Continue a trip

`POST /api/v1/trips/{trip_id}/messages` accepts a required `message` and an
optional partial `request`. Omitted or `null` patch fields preserve existing
answers. When the trip has an owner, send `X-User-Id`.

```json
{
  "message": "Here are the missing details",
  "request": {
    "destination": "Rome",
    "departure_date": "2027-05-01",
    "return_date": "2027-05-07",
    "budget": "1500.00",
    "travelers": 2
  }
}
```

If a task failed, the endpoint retries only failed tasks. If planning had
already succeeded, the supervisor re-runs only the domains explicitly named in
the new message.

### Itinerary

`GET /api/v1/trips/{trip_id}/itinerary` returns the stored `Itinerary`:
day plans, scheduled items, cost breakdown, conflicts, explanations, and
unscheduled activities. Returns `404` for an unknown trip, a missing itinerary,
or a trip owned by another user.

### Feedback

`POST /api/v1/trips/{trip_id}/feedback` accepts:

```json
{
  "message": "Make the hotel cheaper by 20%",
  "expected_version": 1
}
```

Optional headers:

- `X-User-Id` — required when the trip has an owner.
- `Idempotency-Key` — 1–128 characters of `[A-Za-z0-9._:-]`; replays a cached
  response for the same user, trip, and key.

Feedback is parsed into an action and target, routed to the affected domain, and
re-verified. The response reports the parsed intent, changed and unchanged days,
re-verified item IDs, verification failures, whether approval is required, and
any clarification question.

Supported replans currently include cheaper transport/lodging, cancelling an
activity with a verified replacement, and weather-driven indoor swaps. Ambiguous
feedback returns `needs_clarification` without saving a new itinerary. A
mismatched `expected_version` returns `409`; invalid planner input returns `422`.

## Planner behaviour

The planner is deterministic and accepts a `PlanningInput` containing the trip,
transport/lodging/experience options, preferences, and optionally a previous
plan.

- Fixed events are placed first: outbound/return transport, check-in, checkout.
- Activities are assigned to free slots using opening hours, travel time, pace
  limits, and hotel location.
- Costs are grouped by category and checked against the trip budget.
- Conflicts include overlaps, opening-hours violations, insufficient travel
  time, missed connections, budget exceeded, uncovered lodging, currency
  mismatch, and unscheduled activities.
- Explanations are grounded in source option IDs; without an LLM they fall back
  to deterministic text.

## Database

Migration `0001_core_schema.sql` creates:

| Table                | Purpose                                                       |
| -------------------- | ------------------------------------------------------------- |
| `trips`              | Persistent trip state, options, current itinerary, and status |
| `itinerary_versions` | Immutable itinerary snapshots with SHA-256 content hashes     |
| `trip_approvals`     | Approval/rejection tied to an exact itinerary version         |
| `preferences`        | Long-term user preferences with optional per-trip overrides   |
| `trip_feedback`      | Raw feedback plus parsed intent                               |
| `schema_migrations`  | Applied migration filenames and checksums                     |

Schema constraints enforce ownership (`user_id` is required), valid statuses,
date ordering, positive budgets/travellers, immutable versions and approvals,
and cascading deletes from `trips`.

## Current status and limitations

The repository contains working slices of the full architecture; some seams are
intentionally still stubs:

- Transportation, accommodation, and experience agents are provider seams that
  currently return no options. Planning tasks therefore report `failed` until
  real providers are connected.
- `/trips` uses an in-memory store, so records are lost on restart. The
  PostgreSQL repository adapter is not yet in the tree; itinerary and feedback
  endpoints therefore rely on dependency injection (the tests supply fakes).
- Verification is an injected dependency. When absent, changed items are treated
  as verified without an external check.
- Booking and human approval are not implemented. No endpoint claims a booking
  occurred.
- Feedback idempotency is process-local; a shared cache is required for multiple
  API workers.
- The planner expects `start_date`, `end_date`, and `currency` on the trip
  object, while the public intake schema uses `departure_date` and
  `return_date`; aligning those contracts is follow-up work.
- `frontend/` is a placeholder; the UI is not implemented yet.
