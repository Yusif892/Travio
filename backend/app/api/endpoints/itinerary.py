from __future__ import annotations

from typing import Annotated

from app.api.deps import TripRepository, get_trip_repository
from app.api.security import enforce_owner, get_current_user
from app.planner.models import Itinerary
from app.planner.utils import get_value
from fastapi import APIRouter, Depends, HTTPException, Path

router = APIRouter(tags=["itinerary"])

TripId = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]


@router.get("/trips/{trip_id}/itinerary", response_model=Itinerary)
def get_itinerary(
    trip_id: TripId,
    user: str | None = Depends(get_current_user),
    repository: TripRepository = Depends(get_trip_repository),
) -> Itinerary:
    state = repository.load_state(trip_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    enforce_owner(state, user)

    itinerary = get_value(state, "itinerary", None)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    if isinstance(itinerary, dict):
        itinerary = Itinerary.model_validate(itinerary)
    return itinerary
