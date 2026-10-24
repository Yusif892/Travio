from __future__ import annotations

from collections.abc import Callable

from app.feedback.models import FeedbackIntent, FeedbackResult
from app.feedback.parser import parse_feedback
from app.feedback.replanner import Replanner
from app.planner.models import Itinerary
from app.planner.planning_input import PlanningInput


class FeedbackService:
    def __init__(
        self,
        replanner: Replanner | None = None,
        parser_llm: Callable[[str], str] | None = None,
    ) -> None:
        self._replanner = replanner or Replanner()
        self._parser_llm = parser_llm

    def handle(
        self,
        *,
        itinerary: Itinerary,
        planning: PlanningInput,
        message: str,
    ) -> FeedbackResult:
        intent: FeedbackIntent = parse_feedback(message, llm=self._parser_llm)
        result = self._replanner.replan(
            itinerary=itinerary, planning=planning, intent=intent
        )
        return FeedbackResult(intent=intent, **result.model_dump())
