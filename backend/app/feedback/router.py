from __future__ import annotations

from collections.abc import Iterable

from app.feedback.models import FeedbackIntent, tasks_for_target


def route_feedback(
    intent: FeedbackIntent,
    available_tasks: Iterable[str] | None = None,
) -> list[str]:
    if intent.ambiguous:
        return []
    tasks = list(intent.affected_task_ids) or tasks_for_target(intent.target)
    if available_tasks is not None:
        allowed = set(available_tasks)
        tasks = [task for task in tasks if task in allowed]
    return list(dict.fromkeys(tasks))
