from app.api.endpoints import feedback, itinerary
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(itinerary.router)
api_router.include_router(feedback.router)
from fastapi import APIRouter

from .endpoints.trips import router as trips_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(trips_router)
