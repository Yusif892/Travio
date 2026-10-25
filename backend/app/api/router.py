from fastapi import APIRouter

from app.api.endpoints import feedback, itinerary
from app.api.endpoints.trips import router as trips_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(trips_router)
api_router.include_router(itinerary.router)
api_router.include_router(feedback.router)
