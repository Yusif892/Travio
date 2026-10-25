"""Executable LangGraph assembly for the Supervisor planning stage."""
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.domain.enums import TaskAgent
from app.domain.schemas import PlanningTask, TripRecord, TripRequest, WorkflowError
from app.domain.state import TravelState
from app.services.orchestration import OUTPUT_FIELD, PlanningOrchestrator


def build_workflow(orchestrator: PlanningOrchestrator) -> Any:
    """Build a conditional supervisor route with a parallel fan-out/join.

    All worker nodes participate in the join barrier, but only nodes holding a
    selected task call an agent. Each selected agent owns one option field.
    """
    async def supervisor(state: TravelState) -> dict[str, Any]:
        request = TripRequest.model_validate(state["trip_request"])
        message = (state.get("messages") or [{"content": ""}])[-1].get("content", "")
        try:
            tasks = orchestrator.supervisor.decompose(request, message or "plan my complete trip")
            return {"tasks": [task.model_dump(mode="json") for task in tasks]}
        except Exception as exc:
            return {"tasks": [], "errors": [WorkflowError(code="invalid_supervisor_output", message=str(exc)).model_dump()]}

    def has_tasks(state: TravelState) -> str:
        return "fanout" if state.get("tasks") else "assemble"

    async def worker(agent: TaskAgent, state: TravelState) -> dict[str, Any]:
        task_data = next((item for item in state.get("tasks", []) if item["agent"] == agent.value), None)
        if task_data is None:
            return {"task_updates": []}
        task = PlanningTask.model_validate(task_data)
        local = TripRecord(trip_request=TripRequest.model_validate(state["trip_request"]), tasks=[task])
        await orchestrator._run_task(local, task)
        update: dict[str, Any] = {
            "task_updates": [task.model_dump(mode="json")],
            "errors": [error.model_dump() for error in local.errors],
        }
        update[OUTPUT_FIELD[agent]] = getattr(local, OUTPUT_FIELD[agent])
        return update

    async def transportation(state: TravelState) -> dict[str, Any]:
        return await worker(TaskAgent.TRANSPORTATION, state)

    async def accommodation(state: TravelState) -> dict[str, Any]:
        return await worker(TaskAgent.ACCOMMODATION, state)

    async def experiences(state: TravelState) -> dict[str, Any]:
        return await worker(TaskAgent.EXPERIENCES, state)

    def assemble(state: TravelState) -> dict[str, Any]:
        updates = {item["id"]: item for item in state.get("task_updates", [])}
        tasks = [{**task, **updates.get(task["id"], {})} for task in state.get("tasks", [])]
        if not tasks and not state.get("errors"):
            return {"errors": [WorkflowError(code="no_tasks_selected", message="No planning domains were selected.").model_dump()]}
        return {"tasks": tasks}

    graph = StateGraph(TravelState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("fanout", lambda _: {})
    graph.add_node("transportation", transportation)
    graph.add_node("accommodation", accommodation)
    graph.add_node("experiences", experiences)
    graph.add_node("assemble", assemble)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", has_tasks, {"fanout": "fanout", "assemble": "assemble"})
    graph.add_edge("fanout", "transportation")
    graph.add_edge("fanout", "accommodation")
    graph.add_edge("fanout", "experiences")
    graph.add_edge(["transportation", "accommodation", "experiences"], "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


async def run_planning_graph(record: TripRecord, orchestrator: PlanningOrchestrator) -> TripRecord:
    """Run a new plan through LangGraph and map its state back to persistence."""
    final = await build_workflow(orchestrator).ainvoke({
        "trip_request": record.trip_request.model_dump(mode="json"),
        "messages": record.messages,
        "errors": [error.model_dump() for error in record.errors],
    })
    record.tasks = [PlanningTask.model_validate(task) for task in final.get("tasks", [])]
    record.transport_options = final.get("transport_options", [])
    record.lodging_options = final.get("lodging_options", [])
    record.experience_options = final.get("experience_options", [])
    record.errors = [WorkflowError.model_validate(error) for error in final.get("errors", [])]
    return record
