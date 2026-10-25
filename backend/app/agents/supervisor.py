<<<<<<< HEAD
=======
"""Schema-validated task decomposition for the planning workflow."""
from collections.abc import Callable

from app.domain.enums import TaskAgent
from app.domain.schemas import PlanningTask, TripRequest


class SupervisorOutputError(ValueError):
    pass


class Supervisor:
    """Produces only allow-listed agent tasks.

    The default is deterministic until a model provider is connected. A custom
    generator may be supplied, but its output is always parsed/validated here.
    """
    def __init__(self, generator: Callable[[TripRequest, str], list[dict]] | None = None) -> None:
        self._generator = generator
        self.calls = 0

    def decompose(self, request: TripRequest, message: str) -> list[PlanningTask]:
        for attempt in range(2):
            self.calls += 1
            try:
                raw = self._generator(request, message) if self._generator else self._default_tasks(message)
                tasks = [PlanningTask.model_validate(item) for item in raw]
                if len({task.agent for task in tasks}) != len(tasks):
                    raise SupervisorOutputError("duplicate agent task")
                return tasks
            except (TypeError, ValueError) as exc:
                if attempt == 1:
                    raise SupervisorOutputError("Supervisor returned invalid task output") from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _default_tasks(message: str) -> list[dict]:
        text = message.casefold()
        domains: list[TaskAgent] = []
        already_has_lodging = any(phrase in text for phrase in (
            "already have a hotel", "already booked a hotel",
            "already have accommodation", "already booked accommodation",
            "hotel is booked", "accommodation is booked",
        ))
        if any(word in text for word in ("flight", "flights", "transport", "train", "transfer")):
            domains.append(TaskAgent.TRANSPORTATION)
        if not already_has_lodging and any(word in text for word in ("hotel", "hotels", "accommodation", "lodging", "stay")):
            domains.append(TaskAgent.ACCOMMODATION)
        if any(word in text for word in ("activity", "activities", "experience", "experiences", "restaurant", "things to do")):
            domains.append(TaskAgent.EXPERIENCES)
        if not domains and any(word in text for word in ("complete", "full", "plan", "trip", "travel", "itinerary")):
            domains = list(TaskAgent)
        return [{"id": agent.value, "agent": agent, "parameters": {}} for agent in domains]
>>>>>>> f7aa50a (feat: complete supervisor graph routing and retry handling)
