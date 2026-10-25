"""Stable API and orchestration contracts owned by the intake layer."""
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import IntakeStatus, TaskAgent, TaskStatus


class TripRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str | None = None
    destination: str | None = None
    departure_date: date | None = None
    return_date: date | None = None
    budget: Decimal | None = Field(default=None, gt=0)
    travelers: int | None = Field(default=None, gt=0)
    preferences: list[str] = Field(default_factory=list)

    @field_validator("origin", "destination")
    @classmethod
    def strip_locations(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    def missing_fields(self) -> list[str]:
        required = {
            "origin": self.origin,
            "destination": self.destination,
            "dates": self.departure_date and self.return_date,
            "budget": self.budget,
            "travelers": self.travelers,
        }
        return [name for name, value in required.items() if value is None or value is False]


class TripCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: TripRequest = Field(default_factory=TripRequest)
    message: str = Field(default="", max_length=8000)
    user_id: str | None = Field(default=None, max_length=128)


class TripMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=8000)
    request: TripRequest | None = None


class PlanningTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    agent: TaskAgent
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = Field(default=0, ge=0)
    failure_reason: str | None = None


class WorkflowError(BaseModel):
    code: str
    message: str
    task_id: str | None = None


class TripResponse(BaseModel):
    trip_id: UUID
    thread_id: str
    status: IntakeStatus
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    tasks: list[PlanningTask] = Field(default_factory=list)
    errors: list[WorkflowError] = Field(default_factory=list)


class TripRecord(BaseModel):
    trip_id: UUID = Field(default_factory=uuid4)
    thread_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    trip_request: TripRequest = Field(default_factory=TripRequest)
    messages: list[dict[str, str]] = Field(default_factory=list)
    tasks: list[PlanningTask] = Field(default_factory=list)
    transport_options: list[dict[str, Any]] = Field(default_factory=list)
    lodging_options: list[dict[str, Any]] = Field(default_factory=list)
    experience_options: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    itinerary: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    bookings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[WorkflowError] = Field(default_factory=list)
