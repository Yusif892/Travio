"""Fixtures for tests that need a real PostgreSQL (TEST_DATABASE_URL).

Safety: the fixture DROPS the ``public`` schema, so it refuses to run unless
the database name ends with ``_test``.
"""
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.persistence.db import get_database_url  # noqa: E402


def assert_test_database(dsn: str) -> None:
    dbname = psycopg.conninfo.conninfo_to_dict(dsn).get("dbname", "")
    if not dbname.endswith("_test"):
        raise RuntimeError(f"Refusing to wipe database {dbname!r}: name must end with '_test'.")


@pytest.fixture(scope="session")
def test_dsn() -> str:
    try:
        dsn = get_database_url(test=True)
    except RuntimeError:
        pytest.skip("TEST_DATABASE_URL is not set")
    assert_test_database(dsn)
    return dsn


@pytest.fixture
def clean_db(test_dsn: str) -> str:
    """Empty public schema before each test; returns the DSN."""
    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    return test_dsn