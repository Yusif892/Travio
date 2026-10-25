from fastapi import APIRouter

from .endpoints.trips import router as trips_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(trips_router)
