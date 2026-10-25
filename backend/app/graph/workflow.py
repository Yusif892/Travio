"""Graph entry-point contract.

The executable worker fan-out lives in ``PlanningOrchestrator`` so its agent
adapters can remain async and independently testable. This builder is the
LangGraph integration seam for replacing the in-memory trip store with a
checkpointer; it deliberately exposes no booking node.
"""
from langgraph.graph import END, START, StateGraph

from app.domain.state import TravelState


def _complete(state: TravelState) -> TravelState:
    return state


def build_workflow():
    graph = StateGraph(TravelState)
    graph.add_node("planning_complete", _complete)
    graph.add_edge(START, "planning_complete")
    graph.add_edge("planning_complete", END)
    return graph.compile()
