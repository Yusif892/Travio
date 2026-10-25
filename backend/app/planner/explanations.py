from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from app.planner.models import Itinerary, PlanExplanation, ScheduledItem
from app.planner.utils import enum_value, get_value

MAX_TEXT_LENGTH = 400
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


class ExplanationService:
    """Grounds explanations in plan facts. The LLM never mutates the plan."""

    def __init__(self, llm: Callable[[str], str] | None = None) -> None:
        self._llm = llm

    def annotate(self, itinerary: Itinerary, preferences: Any = None) -> Itinerary:
        annotated = itinerary.model_copy(deep=True)
        accepted: dict[str, PlanExplanation] = {}
        if self._llm is not None:
            try:
                accepted = self._ask_llm(annotated, preferences)
            except Exception:
                accepted = {}

        explanations: list[PlanExplanation] = []
        for planned_day in annotated.days:
            for item in planned_day.items:
                explanation = accepted.get(item.item_id) or self._fallback(item)
                item.explanation = explanation.text
                explanations.append(explanation)
        annotated.explanations = explanations
        return annotated

    def _facts(self, item: ScheduledItem, preferences: Any) -> dict[str, str]:
        facts = {
            "item.title": item.title,
            "item.start": item.start.strftime("%Y-%m-%d %H:%M"),
            "item.end": item.end.strftime("%Y-%m-%d %H:%M"),
            "item.price": f"{item.amount} {item.currency}".strip(),
            "item.category": item.category or item.kind.value,
        }
        if item.location is not None:
            facts["item.location"] = f"{item.location.lat:.3f},{item.location.lng:.3f}"
        pace = get_value(preferences, "pace", None)
        if pace is not None:
            facts["pref.pace"] = enum_value(pace)
        interests = get_value(preferences, "interests", None)
        if interests:
            facts["pref.interests"] = ", ".join(str(value) for value in interests)
        return facts

    def _ask_llm(
        self, itinerary: Itinerary, preferences: Any
    ) -> dict[str, PlanExplanation]:
        payload = []
        fact_sets: dict[str, dict[str, str]] = {}
        for planned_day in itinerary.days:
            for item in planned_day.items:
                facts = self._facts(item, preferences)
                fact_sets[item.item_id] = facts
                payload.append({"item_id": item.item_id, "facts": facts})
        prompt = (
            "You explain itinerary choices for a traveler. Use ONLY the supplied facts. "
            "Do not change any time, price, or item. Return strict JSON: "
            '{"explanations":[{"item_id":"...","text":"...","cites":["fact.id"]}]}. '
            "Every number in text must appear in the cited facts.\n"
            + json.dumps({"items": payload}, ensure_ascii=False)
        )
        raw = self._llm(prompt) if self._llm else ""
        data = _load_json(raw)
        entries = data.get("explanations", []) if isinstance(data, Mapping) else data
        accepted: dict[str, PlanExplanation] = {}
        if not isinstance(entries, list):
            return accepted
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            item_id = entry.get("item_id")
            text = entry.get("text")
            cites = entry.get("cites")
            if not isinstance(item_id, str) or not isinstance(text, str) or not isinstance(cites, list):
                continue
            facts = fact_sets.get(item_id)
            if facts is None:
                continue
            cite_ids = [str(cite) for cite in cites]
            if not cite_ids or any(cite not in facts for cite in cite_ids):
                continue
            clean_text = text.strip()
            if not clean_text or len(clean_text) > MAX_TEXT_LENGTH:
                continue
            cited_values = " ".join(facts[cite] for cite in cite_ids)
            if any(token not in cited_values for token in NUMBER_PATTERN.findall(clean_text)):
                continue
            accepted[item_id] = PlanExplanation(
                item_id=item_id, text=clean_text, cites=cite_ids
            )
        return accepted

    @staticmethod
    def _fallback(item: ScheduledItem) -> PlanExplanation:
        return fallback_explanation(item)


def fallback_explanation(item: ScheduledItem) -> PlanExplanation:
    text = f"{item.title} is scheduled on {item.start:%Y-%m-%d} at {item.start:%H:%M}."
    return PlanExplanation(
        item_id=item.item_id,
        text=text,
        cites=["item.title", "item.start"],
    )


def _load_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}
