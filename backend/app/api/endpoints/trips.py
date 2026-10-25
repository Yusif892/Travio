from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status

from app.domain.enums import IntakeStatus
from app.domain.schemas import TripCreateRequest, TripMessageRequest, TripRecord, TripRequest, TripResponse
from app.services.guardrails import evaluate_intake
from app.services.orchestration import planning_orchestrator
from app.services.store import trip_store

router = APIRouter(prefix="/trips", tags=["trips"])


def _merge_request(existing: TripRequest, update: TripRequest) -> TripRequest:
    """Only overwrite a value when the user supplied a new non-null value."""
    return TripRequest(**{name: getattr(update, name) if getattr(update, name) is not None else getattr(existing, name)
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
    if decision.status is IntakeStatus.ACCEPTED:
        await planning_orchestrator.run(record)
    trip_store.create(record)
    return _response(record, decision)


@router.post("/{trip_id}/messages", response_model=TripResponse)
async def continue_trip(trip_id: UUID, payload: TripMessageRequest,
                        x_user_id: str | None = Header(default=None)) -> TripResponse:
    record = trip_store.get(trip_id, x_user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Trip not found")
    record.messages.append({"role": "user", "content": payload.message})
    record.trip_request = _merge_request(record.trip_request, payload.request)
    # The API accepts an optional structured patch alongside conversational
    # text; fields omitted from that patch never erase prior valid answers.
    decision = evaluate_intake(record.trip_request, payload.message)
    if decision.status is IntakeStatus.ACCEPTED:
        # A resumed run only re-emits failed task identities. Successful task
        # results stay in their owned state fields and are never recomputed.
        await planning_orchestrator.run(record, retry_only=bool(record.tasks))
    trip_store.save(record)
    return _response(record, decision)
