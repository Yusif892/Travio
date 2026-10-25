from __future__ import annotations

from app.api.deps import TripRepository, get_trip_repository
from app.planner.models import Itinerary
from app.planner.utils import get_value
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["itinerary"])


@router.get("/trips/{trip_id}/itinerary", response_model=Itinerary)
def get_itinerary(
    trip_id: str,
    repository: TripRepository = Depends(get_trip_repository),
) -> Itinerary:
    state = repository.load_state(trip_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    itinerary = get_value(state, "itinerary", None)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    if isinstance(itinerary, dict):
        itinerary = Itinerary.model_validate(itinerary)
    return itinerary
