from __future__ import annotations

from typing import Annotated, Any

from app.api.adapters import planning_input_from_state
from app.api.deps import TripRepository, get_trip_repository, get_verifier
from app.api.idempotency import (
    IdempotencyStore,
    get_idempotency_store,
    idempotency_cache_key,
    validate_idempotency_key,
)
from app.api.security import enforce_owner, get_current_user
from app.feedback.models import FeedbackResult
from app.feedback.replanner import Replanner
from app.feedback.service import FeedbackService
from app.planner.models import Itinerary
from app.planner.utils import get_value
from app.planner.validation import PlanningValidationError
from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

router = APIRouter(tags=["feedback"])

TripId = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("message cannot be blank")
        if any(ord(char) < 32 and char not in "\n\t" for char in text):
            raise ValueError("message contains control characters")
        return text


@router.post("/trips/{trip_id}/feedback", response_model=FeedbackResult)
def submit_feedback(
    trip_id: TripId,
    payload: FeedbackRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: str | None = Depends(get_current_user),
    repository: TripRepository = Depends(get_trip_repository),
    verifier: Any = Depends(get_verifier),
    store: IdempotencyStore = Depends(get_idempotency_store),
) -> FeedbackResult:
    key = validate_idempotency_key(idempotency_key)
    cache_key = idempotency_cache_key(user, trip_id, key) if key else None

    state = repository.load_state(trip_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    enforce_owner(state, user)

    itinerary = get_value(state, "itinerary", None)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    if isinstance(itinerary, dict):
        itinerary = Itinerary.model_validate(itinerary)

    if cache_key is not None:
        cached = store.get(cache_key)
        if cached is not None:
            return cached

    if payload.expected_version is not None and itinerary.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "Itinerary version conflict: expected "
                f"{payload.expected_version}, current {itinerary.version}"
            ),
        )

    try:
        planning = planning_input_from_state(state)
        service = FeedbackService(replanner=Replanner(verifier=verifier))
        result = service.handle(
            itinerary=itinerary, planning=planning, message=payload.message
        )
    except (PlanningValidationError, ValueError) as exc:
        errors = getattr(exc, "errors", [str(exc)])
        raise HTTPException(status_code=422, detail={"errors": errors}) from None

    if result.itinerary is not None and result.changed_days:
        repository.save_itinerary(trip_id, result.itinerary)
    if cache_key is not None:
        store.put(cache_key, result)
    return result
