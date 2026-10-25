"""LangGraph-compatible state shape.

Agent result fields are deliberately disjoint.  Errors use ``add_errors`` so
parallel branches cannot discard each other's diagnostic records.
"""
from operator import add
from typing import Annotated, Any, TypedDict


def add_errors(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [*(left or []), *(right or [])]


class TravelState(TypedDict, total=False):
    messages: Annotated[list[dict[str, str]], add]
    trip_request: dict[str, Any]
    tasks: list[dict[str, Any]]
    task_updates: Annotated[list[dict[str, Any]], add]
    transport_options: list[dict[str, Any]]
    lodging_options: list[dict[str, Any]]
    experience_options: list[dict[str, Any]]
    verification: dict[str, Any]
    itinerary: dict[str, Any]
    approval: dict[str, Any]
    bookings: list[dict[str, Any]]
    errors: Annotated[list[dict[str, Any]], add_errors]
