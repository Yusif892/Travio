"""LangGraph checkpoint persistence on PostgreSQL.

Checkpoint tables (checkpoints, checkpoint_blobs, checkpoint_writes,
checkpoint_migrations) are created and migrated by LangGraph itself through
``setup()``; they are intentionally NOT part of db/migrations.

The planning graph runs with ``ainvoke``, so use the async saver:

    async with async_postgres_checkpointer(setup=True) as saver:   # setup once at startup
        graph = build_workflow(orchestrator, checkpointer=saver)
        await graph.ainvoke(state, {"configurable": {"thread_id": record.thread_id}})

``thread_id`` is ``TripRecord.thread_id`` (stored in ``trips.thread_id``).
On Windows psycopg's async mode needs the selector event loop; on Linux no change is needed.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.persistence.db import get_database_url


def thread_config(thread_id: str) -> dict:
    """LangGraph ``config`` that selects one trip's conversation."""
    return {"configurable": {"thread_id": thread_id}}


@asynccontextmanager
async def async_postgres_checkpointer(dsn: str | None = None, *, setup: bool = False) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(dsn or get_database_url()) as saver:
        if setup:
            await saver.setup()
        yield saver


@contextmanager
def postgres_checkpointer(dsn: str | None = None, *, setup: bool = False) -> Iterator[PostgresSaver]:
    """Synchronous variant (for ``graph.invoke`` and scripts)."""
    with PostgresSaver.from_conn_string(dsn or get_database_url()) as saver:
        if setup:
            saver.setup()
        yield saver