# Person 4 — Itinerary Planner & Feedback-Based Replanning

**Owns:** TRV-06 (F8 / P6-T1…P6-T5) and TRV-12 (F15 / P10-T1…P10-T4)
**APIs owned:** `GET /api/v1/trips/{trip_id}/itinerary`, `POST /api/v1/trips/{trip_id}/feedback`
**Also owns:** the internal planner and replanning services.

This document is the working contract. Domain models (`app/domain/*`) are owned by the shared
foundation task, so this code describes the shapes it needs but does not define them. All
boundary access is duck-typed (`_get`) or expressed with `Protocol`, which keeps the planner
testable in isolation and tolerant of the final domain attribute names.

## 1. Scope and acceptance criteria

| Story | Feature | Tasks | Must produce |
|---|---|---|---|
| TRV-06 | F8 Planner | P6-T1…T5 | deterministic day-by-day plan, exact costs, conflicts, grounded explanations, estimates |
| TRV-12 | F15 Adaptation | P10-T1…T4 | feedback parsing, routing only affected tasks, replacement + re-verification, approval reset |

TRV-06 acceptance criteria (from `travio-user-stories-12.md`):

1. Fixed events (flights, check-in/out) placed first; nearby activities grouped by day; no
   overlapping slots and nothing outside opening hours.
2. Pace preference caps activities per day.
3. Total = sum of items, computed in code with `Decimal`, with a per-category breakdown.
4. Unresolvable conflicts are reported, never hidden.
5. Explanations cite only a stated preference or verifiable fact and cannot change times,
   prices, or items.
6. Missing data is labelled `estimate`.

TRV-12 acceptance criteria:

1. "cheaper hotel" → lower budget cap for the Accommodation task only.
2. Ambiguous feedback → ask for clarification.
3. A change to one day leaves unaffected days identical and re-verifies affected items.
4. A changed itinerary requires fresh approval.
5. A cancelled activity is replaced only after the replacement is re-verified.
6. Ratings are stored with the trip and never written into long-term preferences here (the
   long-term store owns that, TRV-09).

## 2. Expected domain contract (not owned here)

`app/domain/enums.py`

```python
class ItemKind(str, Enum): TRANSPORT, LODGING, ACTIVITY
class TaskType(str, Enum): TRANSPORT, ACCOMMODATION, EXPERIENCE
class Pace(str, Enum): RELAXED, BALANCED, PACKED
```

`app/domain/schemas.py`

```python
class TripRequest:
    origin: str; destination: str
    start_date: date; end_date: date
    budget: Decimal; currency: str; travelers: int
    pace: Pace | str = Pace.BALANCED

class TransportOption:
    id: str; mode: str; origin: str; destination: str
    depart_at: datetime; arrive_at: datetime
    price: Decimal; currency: str; fetched_at: datetime

class LodgingOption:
    id: str; name: str; lat: float; lng: float
    nightly_price: Decimal; total_price: Decimal; currency: str
    check_in: datetime; check_out: datetime
    cancellation_terms: str; fetched_at: datetime

class ExperienceOption:
    id: str; name: str; category: str; lat: float; lng: float
    opening_hours: list[tuple[time, time]]
    duration_minutes: int; price: Decimal; currency: str
    indoor: bool; fetched_at: datetime
    safety_flag: bool = False

class Preferences:
    pace: Pace | str = Pace.BALANCED
    interests: list[str] = []
    dietary: list[str] = []
    travel_style: str | None = None
    min_connection_minutes: int = 45
    max_activities_per_day: int | None = None
    city_travel_speed_kmh: float = 20.0
```

`app/domain/state.py` — `TravelState` exposes `trip_id`, `trip_request`, `transport_options`,
`lodging_options`, `experience_options`, `verification`, `itinerary`, `errors`.

`app/persistence/repository.py` (assumed) — `PostgresTripRepository` provides
`load_state(trip_id)` and `save_itinerary(trip_id, itinerary)`.

## 3. Module layout

```text
backend/app/
  planner/
    __init__.py
    contracts.py      # Protocols for domain inputs + Verifier
    models.py         # Pydantic plan/response models (owned by Person 4)
    config.py         # pacing, day window, speed, buffers, estimates
    estimates.py      # P6-T5 missing-data defaults + estimate labelling
    scheduler.py      # P6-T1 deterministic scheduler
    costs.py          # P6-T2 exact Decimal cost engine
    conflicts.py      # P6-T3 conflict detector
    explanations.py   # P6-T4 grounded explanation layer
    llm.py            # Groq wiring (optional; falls back when no key)
    planning_input.py # plain PlanningInput + selection helpers
    service.py        # Planner orchestration (plan / replan entry)
  feedback/
    __init__.py
    models.py         # FeedbackIntent, enums, ReplanResult
    parser.py         # P10-T2 feedback parser
    router.py         # P10-T1 intent -> affected tasks only
    replanner.py      # P10-T3 replacement + diff + re-verification
    service.py        # FeedbackService facade
  api/
    deps.py           # repository dependency (overridable in tests)
    adapters.py       # TravelState -> PlanningInput (duck-typed)
    endpoints/
      itinerary.py    # GET itinerary
      feedback.py     # POST feedback
    router.py         # /api/v1 wiring
  main.py             # FastAPI app
```

## 4. Algorithms

### 4.1 Scheduler (P6-T1) — `planner/scheduler.py`

1. Build the day list from `start_date` to `end_date` inclusive.
2. Select fixed items deterministically:
   - outbound: cheapest transport departing on `start_date`;
   - return: cheapest transport departing on `end_date`;
   - lodging: cheapest lodging whose stay covers the trip;
   - check-in at `max(arrival + transfer, lodging.check_in)`, 30 min;
   - check-out at `min(lodging.check_out, return departure - transfer)`.
3. Fixed items are placed first. Activities are only placed inside the remaining free
   intervals (day window 08:00–21:00).
4. Activities are ordered by interest match, then distance from the previous location, then
   id (stable tie-break). Greedy nearest-neighbour placement gives location-aware grouping.
5. For every candidate: travel minutes = haversine / `city_travel_speed_kmh` * 60 + buffer;
   start = next opening time at/after arrival; reject if it ends after closing, after the free
   interval, or cannot reach the next fixed item.
6. Cap activities per day: relaxed 2, balanced 3, packed 5 (or `max_activities_per_day`).
7. Activities that cannot be placed become `UNSCHEDULED_ACTIVITY` conflicts, not silent drops.
8. `rebuild_dates` / `preserve_dates`: days not rebuilt are copied verbatim from the previous
   itinerary, guaranteeing TRV-12's "unaffected days unchanged".

### 4.2 Costs (P6-T2) — `planner/costs.py`

- All money is `Decimal`; every result is quantized to 2 dp (`ROUND_HALF_UP`).
- Transport and activities: `unit_price * travelers`. Lodging: `total_price` when present,
  otherwise `nightly_price * nights` (two decimals).
- Lines are per item with a category; `by_category` sums each category; `total` is the sum of
  line amounts (never recomputed from the budget).
- Estimates are flagged per line (`is_estimate`) and aggregated into `estimated_amount`.
- Currency mismatch is an `error` conflict and the foreign line is excluded from the total.
- `within_budget` compares `total` to `trip.budget`; over-budget adds `BUDGET_EXCEEDED`.

### 4.3 Conflicts (P6-T3) — `planner/conflicts.py`

Deterministic codes: `OVERLAP`, `OUTSIDE_OPENING_HOURS`, `INSUFFICIENT_TRAVEL`,
`MIN_CONNECTION`, `BUDGET_EXCEEDED`, `LODGING_NOT_COVERING`, `CURRENCY_MISMATCH`,
`UNSCHEDULED_ACTIVITY`, `MISSING_DATA`. Every conflict carries severity (`error`/`warning`),
day, item ids, and a human-readable message. Unresolvable conflicts remain in the response.

### 4.4 Explanations (P6-T4) — `planner/explanations.py`

- Facts are built from the finished plan only (title, start/end, price, category, location)
  plus stated preferences (pace, interests).
- The LLM receives facts and must return `{item_id, text, cites:[fact_id]}`. It never writes
  back into the plan.
- Validation: cited ids must exist and belong to that item; every number in the text must
  appear in a cited fact; length limit. Invalid output is discarded.
- A deterministic fallback produces a valid explanation with no invented numbers.
- With no LLM configured, the fallback is used; tests never call the network.

### 4.5 Feedback parser (P10-T2) — `feedback/parser.py`

Deterministic keyword/regex parsing, with an optional injected LLM fallback. Extracts action
(`CHEAPER`, `UPGRADE`, `CANCEL`, `ADD`, `MOVE`, `PACE`, `RATING`, `WEATHER`, `GENERIC`),
target (`TRANSPORT`, `ACCOMMODATION`, `EXPERIENCE`, `ITINERARY`, `UNKNOWN`), percentage cap,
rating, date, item id and confidence. No target and no action → `ambiguous=True` with a
clarification question.

### 4.6 Router (P10-T1) — `feedback/router.py`

Maps only the parsed target to task ids: accommodation → `["accommodation"]`, transport →
`["transport"]`, experience → `["experience"]`. "cheaper hotel" therefore never touches the
transport or experience tasks. Ambiguous feedback produces no task request.

### 4.7 Replanner (P10-T3) — `feedback/replanner.py`

- Takes the current `Itinerary`, the `FeedbackIntent`, the original `PlanningInput`, and an
  injected `Verifier`.
- Applies a minimal delta: cheaper lodging replaces only the lodging items; cheaper transport
  only the transport items; a cancellation removes one activity and tries a verified
  replacement from the unused options; pace feedback rebuilds only activity days.
- Days outside the affected set are copied byte-for-byte from the previous itinerary.
- Only changed items are sent to the verifier. A replacement is inserted only when
  verification passes; otherwise the item is left as a reported gap.
- Costs/conflicts are recomputed; `version` increments and `approval_required=True`, so the
  old approval no longer applies.

## 5. API contract

`GET /api/v1/trips/{trip_id}/itinerary`
- 200 → `Itinerary` (days, cost breakdown, conflicts, explanations, version).
- 404 → no itinerary for that trip.

`POST /api/v1/trips/{trip_id}/feedback`
```json
{ "message": "make the hotel cheaper" }
```
- 200 → `{ "intent": {...}, "itinerary": {...}, "affected_task_ids": ["accommodation"],
  "changed_days": [...], "unchanged_days": [...], "reverified_item_ids": [...],
  "approval_required": true }`
- Ambiguous → 200 with `needs_clarification: true` and a clarification question, no replan.
- 404 → unknown trip/itinerary.

Both endpoints obtain state through the overridable `get_trip_repository` dependency, so API
tests run with an in-memory fake and no database.

## 6. Tests mapped to acceptance criteria

| Test file | Covers |
|---|---|
| `tests/unit/planner/test_scheduler.py` | fixed-first order, grouping, no overlap, opening hours, pace cap, travel time, preserve days |
| `tests/unit/planner/test_costs.py` | exact Decimal arithmetic, per-category breakdown, estimates, currency mismatch, budget |
| `tests/unit/planner/test_conflicts.py` | overlap, outside hours, 44/45/46-min connection, budget, lodging coverage, unscheduled |
| `tests/unit/planner/test_explanations.py` | grounded cite validation, fabricated price rejected, fallback, plan immutability |
| `tests/unit/feedback/test_parser.py` | cheaper hotel, ambiguous text, cancel, rating, weather |
| `tests/unit/feedback/test_router.py` | only affected task routed |
| `tests/unit/feedback/test_replanner.py` | unaffected days identical, only changed items re-verified, approval reset, replacement gated by verifier |
| `tests/api/test_itinerary_api.py` | 200/404, response shape |
| `tests/api/test_feedback_api.py` | routing, clarification, approval reset |

## 7. Build order

1. `models.py` + `contracts.py` + `config.py` (shared vocabulary).
2. `estimates.py` → `scheduler.py` → `costs.py` → `conflicts.py`.
3. `explanations.py` → `service.py`.
4. `feedback/parser.py` → `router.py` → `replanner.py` → `service.py`.
5. `api/deps.py` → `adapters.py` → endpoints → router/main.
6. Tests red → green, then lint/type sanity.

## 8. Open decisions

- **D-08 (adaptation triggers):** cancellation/weather entry points are implemented as
  callable service methods; the graph trigger remains a later integration item (P10-T3).
- **D-09 (currency/language):** single-currency trips in this slice; mismatches are reported.
- **D-02 (retry exhaustion)** is consumed from Verify; the planner never retries agents.
- LLM provider selection is injected (`llm` callable), so this slice has no network dependency.

## 9. Implementation status

Done and tested:

- P6-T1…T5: scheduler, exact costs, conflicts, grounded explanations, estimates.
- P10-T1…T4: parser, affected-task router, replanner, verified replacement, approval reset,
  rating handling (stored/bridged by the long-term store, TRV-09).
- `GET /api/v1/trips/{trip_id}/itinerary` and `POST /api/v1/trips/{trip_id}/feedback`
  with an overridable repository/verifier for isolated tests.
- Groq wiring: `build_planner()` uses `GROQ_API_KEY` + `GROQ_MODEL` from `.env`; without a
  key it uses the deterministic explanation fallback, so tests/offline runs never call the
  network. `groq_llm()` is the raw callable if you need it directly.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest
# 47 passed
```

Test files: `tests/unit/planner/` (scheduler, costs, conflicts, explanations, llm) and
`tests/unit/feedback/` (parser, router, replanner), plus `tests/api/` for both endpoints.

Remaining integration dependency (owned elsewhere): real `app/domain/*`, persistence
repository, and `app/verification/*` implementations. Until they exist, the API uses the
overridable dependencies and the planner accepts duck-typed option objects.
