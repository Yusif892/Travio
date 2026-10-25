"""Bounded, concurrent planning execution and targeted retry support."""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents import accommodation_agent, experiences_agent, transport_agent
from app.agents.supervisor import Supervisor, SupervisorOutputError
from app.domain.enums import TaskAgent, TaskStatus
from app.domain.schemas import PlanningTask, TripRecord, WorkflowError

Agent = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]
OUTPUT_FIELD = {
    TaskAgent.TRANSPORTATION: "transport_options",
    TaskAgent.ACCOMMODATION: "lodging_options",
    TaskAgent.EXPERIENCES: "experience_options",
}


class PlanningOrchestrator:
    def __init__(self, supervisor: Supervisor | None = None, agents: dict[TaskAgent, Agent] | None = None,
                 max_retries: int = 1) -> None:
        self.supervisor = supervisor or Supervisor()
        self.agents = agents or {
            TaskAgent.TRANSPORTATION: transport_agent.run,
            TaskAgent.ACCOMMODATION: accommodation_agent.run,
            TaskAgent.EXPERIENCES: experiences_agent.run,
        }
        self.max_retries = max_retries

    async def run(self, record: TripRecord, retry_only: bool = False) -> TripRecord:
        if retry_only:
            selected = [task for task in record.tasks if task.status is TaskStatus.FAILED and task.retry_count < self.max_retries]
            for task in selected:
                task.retry_count += 1
                task.status = TaskStatus.PENDING
        else:
            try:
                selected = self.supervisor.decompose(record.trip_request, record.messages[-1]["content"] if record.messages else "")
                record.tasks = selected
            except SupervisorOutputError as exc:
                record.errors.append(WorkflowError(code="invalid_supervisor_output", message=str(exc)))
                return record
        if not selected:
            record.errors.append(WorkflowError(code="no_tasks_selected", message="No planning domains were selected."))
            return record

        # gather launches every independent selected task before waiting for any;
        # each task has a dedicated output field, preventing cross-domain writes.
        await asyncio.gather(*(self._run_task(record, task) for task in selected))
        return record

    async def _run_task(self, record: TripRecord, task: PlanningTask) -> None:
        agent = self.agents.get(task.agent)
        if agent is None:
            task.status = TaskStatus.FAILED
            task.failure_reason = "No registered agent"
            record.errors.append(WorkflowError(code="unknown_agent", message=task.failure_reason, task_id=task.id))
            return
        task.status = TaskStatus.RUNNING
        try:
            result = await agent({**task.parameters, "failure_reason": task.failure_reason})
            if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
                raise ValueError("agent result must be a list of objects")
            setattr(record, OUTPUT_FIELD[task.agent], result)
            task.status = TaskStatus.SUCCEEDED
            task.failure_reason = None
        except Exception as exc:  # retained as state, other parallel tasks continue
            task.status = TaskStatus.FAILED
            task.failure_reason = str(exc)
            record.errors.append(WorkflowError(code="agent_failed", message=str(exc), task_id=task.id))


planning_orchestrator = PlanningOrchestrator()
