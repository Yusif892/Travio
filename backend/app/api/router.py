from app.api.endpoints import feedback, itinerary
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(itinerary.router)
api_router.include_router(feedback.router)
