from __future__ import annotations

import json

from app.planner.explanations import ExplanationService
from app.planner.service import Planner

from tests.factories import make_planning


def test_grounded_explanation_is_accepted():
    planning = make_planning()
    plan = Planner().plan(planning)
    target = plan.days[0].items[0]

    def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "explanations": [
                    {
                        "item_id": target.item_id,
                        "text": "This fits your balanced pace.",
                        "cites": ["pref.pace"],
                    }
                ]
            }
        )

    annotated = ExplanationService(llm=llm).annotate(plan, planning.preferences)
    explanation = next(
        entry for entry in annotated.explanations if entry.item_id == target.item_id
    )
    assert explanation.text == "This fits your balanced pace."
    assert explanation.cites == ["pref.pace"]
    assert annotated.item(target.item_id).explanation == explanation.text


def test_fabricated_price_is_rejected_and_fallback_used():
    planning = make_planning()
    plan = Planner().plan(planning)
    target = plan.days[0].items[0]

    def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "explanations": [
                    {
                        "item_id": target.item_id,
                        "text": "This option costs 999 EUR.",
                        "cites": ["item.title"],
                    }
                ]
            }
        )

    annotated = ExplanationService(llm=llm).annotate(plan, planning.preferences)
    explanation = next(
        entry for entry in annotated.explanations if entry.item_id == target.item_id
    )
    assert "999" not in explanation.text
    assert explanation.cites == ["item.title", "item.start"]


def test_explanations_cannot_change_times_prices_or_items():
    planning = make_planning()
    plan = Planner().plan(planning)
    before = [
        (item.item_id, item.start, item.end, item.title, item.amount)
        for day in plan.days
        for item in day.items
    ]

    def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "explanations": [
                    {
                        "item_id": before[0][0],
                        "text": "Changed to a free private tour at midnight.",
                        "cites": ["item.title"],
                    }
                ]
            }
        )

    annotated = ExplanationService(llm=llm).annotate(plan, planning.preferences)
    after = [
        (item.item_id, item.start, item.end, item.title, item.amount)
        for day in annotated.days
        for item in day.items
    ]
    assert before == after


def test_fallback_works_without_an_llm():
    planning = make_planning()
    plan = Planner().plan(planning)
    annotated = ExplanationService().annotate(plan, planning.preferences)
    assert len(annotated.explanations) == sum(len(day.items) for day in plan.days)
    assert all(explanation.text for explanation in annotated.explanations)
    assert all(explanation.cites for explanation in annotated.explanations)
