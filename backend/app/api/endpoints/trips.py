from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status

from app.domain.enums import IntakeStatus
from app.domain.schemas import TripCreateRequest, TripMessageRequest, TripRecord, TripRequest, TripResponse
from app.graph.workflow import run_planning_graph
from app.services.guardrails import evaluate_intake
from app.services.store import trip_store

router = APIRouter(prefix="/trips", tags=["trips"])


def _merge_request(existing: TripRequest, update: TripRequest) -> TripRequest:
    """Only overwrite a value when the user supplied a new non-null value."""
    return TripRequest(**{name: getattr(update, name) if name in update.model_fields_set and getattr(update, name) is not None else getattr(existing, name)
                          for name in TripRequest.model_fields})


def _response(record: TripRecord, decision) -> TripResponse:
    return TripResponse(trip_id=record.trip_id, thread_id=record.thread_id, status=decision.status,
                        message=decision.message, missing_fields=decision.missing_fields,
                        tasks=record.tasks, errors=record.errors)


@router.post("", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(payload: TripCreateRequest) -> TripResponse:
    record = TripRecord(user_id=payload.user_id, trip_request=payload.request)
    if payload.message:
        record.messages.append({"role": "user", "content": payload.message})
    decision = evaluate_intake(record.trip_request, payload.message)
<<<<<<< HEAD
=======
    if decision.status is IntakeStatus.ACCEPTED:
        await run_planning_graph(record, planning_orchestrator)
>>>>>>> f7aa50a (feat: complete supervisor graph routing and retry handling)
    trip_store.create(record)
    # Supervisor/agents are intentionally not called until the deterministic
    # intake decision is accepted. Orchestration is added on branch two.
    return _response(record, decision)


@router.post("/{trip_id}/messages", response_model=TripResponse)
async def continue_trip(trip_id: UUID, payload: TripMessageRequest,
                        x_user_id: str | None = Header(default=None)) -> TripResponse:
    record = trip_store.get(trip_id, x_user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Trip not found")
    record.messages.append({"role": "user", "content": payload.message})
    if payload.request is not None:
        record.trip_request = _merge_request(record.trip_request, payload.request)
    # The API accepts an optional structured patch alongside conversational
    # text; fields omitted from that patch never erase prior valid answers.
    decision = evaluate_intake(record.trip_request, payload.message)
<<<<<<< HEAD
=======
    if decision.status is IntakeStatus.ACCEPTED:
        # Retry failures directly; otherwise map explicit feedback to only the
        # named planning domain so successful unrelated results remain intact.
        if any(task.status.value == "failed" for task in record.tasks):
            await planning_orchestrator.run(record, retry_only=True)
        elif record.tasks:
            await planning_orchestrator.rerun_changed_domains(record, payload.message)
>>>>>>> f7aa50a (feat: complete supervisor graph routing and retry handling)
    trip_store.save(record)
    return _response(record, decision)
