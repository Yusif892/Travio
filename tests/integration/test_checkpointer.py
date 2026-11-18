"""LangGraph checkpoint persistence on PostgreSQL (needs TEST_DATABASE_URL + langgraph)."""
import asyncio
from operator import add
from typing import Annotated, TypedDict

import pytest

pytest.importorskip("langgraph.checkpoint.postgres")

from langgraph.graph import END, START, StateGraph  # noqa: E402

from app.persistence.checkpointer import async_postgres_checkpointer, thread_config  # noqa: E402


class State(TypedDict, total=False):
    trail: Annotated[list[str], add]


def build(saver):
    graph = StateGraph(State)
    graph.add_node("plan", lambda _: {"trail": ["plan"]})
    graph.add_node("book", lambda _: {"trail": ["book"]})
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "book")
    graph.add_edge("book", END)
    # pause before booking, like the human-approval interrupt
    return graph.compile(checkpointer=saver, interrupt_before=["book"])


def test_graph_state_survives_restart_and_resumes(clean_db):
    config = thread_config("thread-1")

    async def scenario():
        async with async_postgres_checkpointer(clean_db, setup=True) as saver:
            graph = build(saver)
            first = await graph.ainvoke({"trail": []}, config)
            assert first["trail"] == ["plan"]
            assert (await graph.aget_state(config)).next == ("book",)

        # simulated process restart: brand-new connection and graph object
        async with async_postgres_checkpointer(clean_db) as saver:
            graph = build(saver)
            assert (await graph.aget_state(config)).next == ("book",)
            final = await graph.ainvoke(None, config)
            assert final["trail"] == ["plan", "book"]
            assert (await graph.aget_state(config)).next == ()

    asyncio.run(scenario())


def test_threads_are_isolated(clean_db):
    async def scenario():
        async with async_postgres_checkpointer(clean_db, setup=True) as saver:
            graph = build(saver)
            await graph.ainvoke({"trail": []}, thread_config("thread-a"))
            other = await graph.aget_state(thread_config("thread-b"))
            assert other.values == {} and other.next == ()

    asyncio.run(scenario())