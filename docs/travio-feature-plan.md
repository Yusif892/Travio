# TRAVIO: Implementation Plan as Features

Each feature maps to a component in `travio.drawio`. "Recommendation" items are my suggestions and are not in the diagram.

---

## F1. Input Guardrails
**Architecture:** Input Guardrails node, Reject / Ask for clarification node.

**Implement:**
1. Scope check: accept travel requests only.
2. Safety and prompt-injection check.
3. Completeness check for origin, destination, dates, budget, travelers.
4. `valid` goes to the Supervisor. `invalid` goes to Reject/Clarify, which asks the user only for the missing or problematic items.

**Recommendations:**
- Do the completeness check with plain code (required fields) and use the LLM only for scope, safety, and injection.
- The diagram doesn't show where Reject/Clarify goes next. End the turn and resume when the user replies; the checkpointer keeps what was already collected.

---

## F2. Shared TravelState
**Architecture:** TravelState (extends MessagesState), shared by all nodes.

**Implement:**
1. Fields: `messages`, `trip_request`, `tasks`, `transport_options`, `lodging_options`, `experience_options`, `verification`, `itinerary`, `approval`, `bookings`, `errors`.
2. Each parallel agent writes to its own field. Shared collections (`errors`, options) use reducers so concurrent writes merge safely.
3. Per-task `retry_count`, so Verify can retry only what failed.

**Recommendations:**
- Use Pydantic models for every field and `Decimal` for money.
- Keep memory outside the State in the MVP, as the diagram says.
- Trim long message history instead of keeping everything.

---

## F3. Supervisor (understand, decompose, route)
**Architecture:** "Understand & Decompose" node with conditional edges.

**Implement:**
1. LLM with structured output produces a task list (which agents, with what parameters).
2. A routing function sends only the selected tasks to Transportation, Accommodation, and Experience in parallel.
3. On a retry or a "Not Approved" return, re-route only the affected tasks and fold the user's feedback into their parameters.

**Recommendations:**
- In retry mode, skip the LLM and re-emit the failed tasks directly, so the Supervisor doesn't re-plan everything.
- Treat dependencies explicitly (for example, "activities near the hotel" needs lodging first).

---

## F4. Transportation Agent
**Architecture:** Transportation Agent.

**Implement:**
1. Search flights, trains, and transfers through a provider interface.
2. Return normalized options (times in UTC, price, stops) with a `fetched_at` timestamp.
3. On tool failure, return partial results and log the error instead of crashing.

**Recommendations:**
- Start with mock data, then add one real provider (for example Amadeus or Duffel).
- Only allow the agent to recommend options that the tool actually returned.

---

## F5. Accommodation Agent
**Architecture:** Accommodation Agent.

**Implement:**
1. Search hotels for the trip dates, budget, and travelers.
2. Return location (lat/lng), nightly and total price, cancellation terms, `fetched_at`.
3. Same partial-result behavior as F4.

**Recommendations:**
- Check that the total equals nightly price times nights plus fees.
- Keep the same normalized format as F4 so Verify and Planner treat all agents alike.

---

## F6. Experience Agent
**Architecture:** Experience Agent.

**Implement:**
1. Search activities and restaurants, respecting preferences (dietary, travel style).
2. Return location, opening hours, duration, price, indoor/outdoor, `fetched_at`.
3. Same partial-result behavior as F4.

**Recommendations:**
- Put weather data here (the diagram mentions bad weather only under Adaptation, so it has no owner yet).
- Opening hours are the most common source of verification failures, so store them in a structured format.

---

## F7. Verification Middleware
**Architecture:** Verify node plus the "Verification checks" panel.

**Implement:**
1. Feasibility: connection times, travel times between stops, opening hours.
2. Freshness: data age below its limit, otherwise re-fetch.
3. Constraints: budget, dates, dietary, travel style.
4. Safety: no unsafe activity or area recommended.
5. `YES` goes to Planner. `NO` re-runs only the failed task, while `retry_count < max`.

**Recommendations:**
- Write these checks as plain code, not LLM calls.
- Define what happens when retries run out (the diagram doesn't). Suggested: continue to the Planner and tell the user what's missing.
- Set a separate freshness limit for each data type (flights short, opening hours long).

---

## F8. Planner
**Architecture:** Planner node.

**Implement:**
1. Build a day-by-day schedule: fixed events first (flights, check-in), then activities.
2. Group activities by location and account for travel time.
3. Compute total cost and per-category budget.
4. Detect conflicts and explain each recommendation.

**Recommendations:**
- Code does the scheduling, arithmetic, and budget. The LLM only chooses among options that already fit and writes the explanations.
- Mark estimated values as estimates.

---

## F9. Output Guardrails
**Architecture:** Output Guardrails node, with `fail → fix` back to Planner.

**Implement:**
1. Grounding: every itinerary item comes from a tool result.
2. Budget: total recomputed in code and within the limit.
3. No booking is claimed without a confirmation.

**Recommendations:**
- Cap the Planner loop (for example 2 attempts), then escalate to the user.

---

## F10. Human Approval
**Architecture:** Human Approval node (`interrupt()`).

**Implement:**
1. Pause the graph and show the itinerary.
2. `approved` goes to Booking. `Not Approved (user feedback)` goes to the Supervisor.

**Recommendations:**
- Re-check prices when the user approves, since a long wait can make them stale.
- Convert free-text feedback ("cheaper hotel") into a concrete change to the affected task.

---

## F11. Booking
**Architecture:** Booking node.

**Implement:**
1. Book flight, hotel, and activities only after approval.
2. Use an idempotency key per item.
3. Save confirmations to State.

**Recommendations:**
- Build against a sandbox or mock booking API first.
- Decide what happens on partial success (flight booked, hotel failed). The diagram has no failure edge.
- Never retry a booking call without its idempotency key.

---

## F12. Agent Middleware
**Architecture:** Agent Middleware panel (wraps every agent and tool call).

**Implement, one hook at a time:**
1. `before_agent`: load user preferences and short-term memory.
2. `before_model`: trim or summarize messages, redact PII.
3. `wrap_tool_call`: timeout, retry with backoff, fallback tool, write errors to State.
4. `after_model`: validate structured output, grounding check.
5. `after_agent`: write results to State, log trace, tokens, latency.
6. `human_in_the_loop`: pause before booking tools.
7. Retry and Recovery: tool fails, retry, try an alternative, then flag a partial result to Verify.

**Recommendations:**
- Put anything that wraps every call here. Put anything that changes the flow (guardrails, Verify, approval) in graph nodes.
- Allow booking tools only inside the Booking node, as a second layer of protection.

---

## F13. Three-Layer Guardrails
**Architecture:** Guardrails (3 layers) panel.

**Implement:**
1. Input layer: F1.
2. Tool/agent layer: schema validation, allow-listed tools, spend limits.
3. Output layer: F9, plus human confirmation before booking (F10).

**Recommendation:** Add a per-trip spend limit in addition to per-item limits.

---

## F14. Memory
**Architecture:** MEMORY panel.

**Implement:**
1. Short-term: PostgreSQL-backed LangGraph checkpointer using `thread_id` per trip.
2. Long-term in PostgreSQL: user preferences, past trips, feedback.
3. Stable `user_id` across sessions.

**Recommendations:**
- Keep preferences separate from one-time trip constraints, so "budget this time" doesn't overwrite a long-term preference.
- Update preferences from explicit statements or repeated feedback, not from a single choice.

---

## F15. Adaptation and Feedback
**Architecture:** Adaptation & Feedback panel.

**Implement:**
1. Rejection feedback goes to the Supervisor (already drawn).
2. Cancelled activity or bad weather: replace the item and re-verify.
3. User ratings update long-term preferences.

**Recommendations:**
- The diagram doesn't show what triggers cancellation or weather replanning or where ratings are collected. Treat this as a later feature.
- When replanning, change only the affected items and keep the approved parts.

---

## Suggested build order
1. F2 State
2. F4, F5, F6 agents (on mock data)
3. F3 Supervisor
4. F7 Verify
5. F8 Planner
6. F1 and F9 guardrails
7. F12 Middleware (can run alongside steps 4–6)
8. F14 Memory
9. F10 Approval, then F11 Booking
10. F15 Adaptation (later)

## MVP vs later
- **MVP:** F1–F11, F14 (checkpointer plus preferences), basic F12.
- **Later:** F15, multiple providers, full PII redaction, learning from ratings.
