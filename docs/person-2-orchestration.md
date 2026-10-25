# Person 2 orchestration contract

`POST /api/v1/trips` accepts a structured `request` and optional `message`.
The required fields are origin, destination, departure/return dates, budget,
and travellers. Its response status is `clarification_needed`, `rejected`, or
`accepted`; rejected and clarification states do not execute any agent.

`POST /api/v1/trips/{trip_id}/messages` accepts a required message plus an
optional `request` patch. Null/omitted patch fields preserve the stored trip
details. This endpoint requires `X-User-Id` when the record has an owner.

Once intake is accepted, the supervisor produces validated, allow-listed tasks
for transportation, accommodation, and experiences. Independent tasks are
launched together and write only their own state fields. Agent failures become
per-task `failed` statuses and `errors`; successful sibling results remain.
Calling the run in retry mode reuses failed task parameters and failure reason,
increments only that task's counter, and never calls the supervisor again.

There is currently an in-memory store because no project persistence adapter
exists. Production integration should replace it with the PostgreSQL/
LangGraph checkpointer while preserving `TripRecord.thread_id` and this API
contract. Booking is not part of this workflow.
