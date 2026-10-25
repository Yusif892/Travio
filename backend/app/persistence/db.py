"""Database connection helpers.

Credentials come only from the environment (``DATABASE_URL`` /
``TEST_DATABASE_URL``), optionally loaded from a git-ignored ``.env`` file.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def get_database_url(test: bool = False) -> str:
    """Return the configured DSN; raise a clear error if it is missing."""
    load_dotenv()
    name = "TEST_DATABASE_URL" if test else "DATABASE_URL"
    url = os.environ.get(name)
    if not url:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return url


def get_pool(dsn: str | None = None) -> ConnectionPool:
    """Lazily create the shared pool (rows come back as dicts)."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(dsn or get_database_url(), min_size=1, max_size=10,
                               kwargs={"row_factory": dict_row}, open=False)
        _pool.open(wait=True, timeout=10)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Borrow a pooled connection; commits on success, rolls back on error."""
    with get_pool().connection() as conn:
        yield conn