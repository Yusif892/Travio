from __future__ import annotations

from typing import Any

from app.api.adapters import planning_input_from_state
from app.api.deps import TripRepository, get_trip_repository, get_verifier
from app.feedback.models import FeedbackResult
from app.feedback.replanner import Replanner
from app.feedback.service import FeedbackService
from app.planner.models import Itinerary
from app.planner.utils import get_value
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/trips/{trip_id}/feedback", response_model=FeedbackResult)
def submit_feedback(
    trip_id: str,
    payload: FeedbackRequest,
    repository: TripRepository = Depends(get_trip_repository),
    verifier: Any = Depends(get_verifier),
) -> FeedbackResult:
    state = repository.load_state(trip_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    itinerary = get_value(state, "itinerary", None)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    if isinstance(itinerary, dict):
        itinerary = Itinerary.model_validate(itinerary)

    planning = planning_input_from_state(state)
    service = FeedbackService(replanner=Replanner(verifier=verifier))
    result = service.handle(itinerary=itinerary, planning=planning, message=payload.message)

    if result.itinerary is not None and result.changed_days:
        repository.save_itinerary(trip_id, result.itinerary)
    return result
