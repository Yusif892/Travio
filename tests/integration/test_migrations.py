import hashlib
import uuid
from pathlib import Path

import psycopg
import pytest

from app.persistence.migrate import MIGRATIONS_DIR, MigrationError, apply_migrations
from conftest import assert_test_database

CORE_TABLES = {"trips", "itinerary_versions", "trip_approvals", "preferences",
               "trip_feedback", "schema_migrations"}
HASH = "a" * 64


def _tables(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("select tablename from pg_tables where schemaname = 'public'").fetchall()
    return {r[0] for r in rows}


def _new_trip(conn, user_id="alice", thread_id=None) -> uuid.UUID:
    return conn.execute(
        "insert into trips (thread_id, user_id) values (%s, %s) returning trip_id",
        (thread_id or str(uuid.uuid4()), user_id),
    ).fetchone()[0]


def test_guard_refuses_non_test_database():
    with pytest.raises(RuntimeError):
        assert_test_database("postgresql://u:p@localhost:5432/agentmemory")
    assert_test_database("postgresql://u:p@localhost:5432/agentmemory_test")


def test_apply_creates_core_tables(clean_db):
    applied = apply_migrations(clean_db)
    assert "0001_core_schema.sql" in applied
    assert CORE_TABLES <= _tables(clean_db)


def test_rerun_is_a_noop(clean_db):
    apply_migrations(clean_db)
    assert apply_migrations(clean_db) == []


def test_edited_applied_migration_is_rejected(clean_db, tmp_path: Path):
    (tmp_path / "0001_x.sql").write_text("create table t1 (id int);")
    apply_migrations(clean_db, tmp_path)
    (tmp_path / "0001_x.sql").write_text("create table t1 (id int, extra int);")
    with pytest.raises(MigrationError, match="modified"):
        apply_migrations(clean_db, tmp_path)


def test_failing_migration_rolls_back_and_is_not_recorded(clean_db, tmp_path: Path):
    (tmp_path / "0001_ok.sql").write_text("create table ok_table (id int);")
    (tmp_path / "0002_bad.sql").write_text("create table half_done (id int); select 1/0;")
    with pytest.raises(MigrationError, match="0002_bad.sql"):
        apply_migrations(clean_db, tmp_path)
    tables = _tables(clean_db)
    assert "ok_table" in tables and "half_done" not in tables
    with psycopg.connect(clean_db) as conn:
        names = [r[0] for r in conn.execute("select filename from schema_migrations").fetchall()]
    assert names == ["0001_ok.sql"]


def test_migrations_apply_in_filename_order(clean_db, tmp_path: Path):
    (tmp_path / "0002_b.sql").write_text("alter table a add column y int;")
    (tmp_path / "0001_a.sql").write_text("create table a (x int);")
    assert apply_migrations(clean_db, tmp_path) == ["0001_a.sql", "0002_b.sql"]


# ---- constraints of 0001_core_schema.sql --------------------------------

@pytest.fixture
def conn(clean_db):
    apply_migrations(clean_db)
    with psycopg.connect(clean_db, autocommit=True) as c:
        yield c


def test_thread_id_is_unique(conn):
    _new_trip(conn, thread_id="t-1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _new_trip(conn, user_id="bob", thread_id="t-1")


def test_trip_requires_owner_and_valid_status(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into trips (thread_id, user_id) values ('t-x', '')")
    with pytest.raises(psycopg.errors.NotNullViolation):
        conn.execute("insert into trips (thread_id, user_id) values ('t-y', null)")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into trips (thread_id, user_id, status) values ('t-z', 'a', 'bogus')")


def test_return_date_cannot_precede_departure(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into trips (thread_id, user_id, departure_date, return_date) "
                     "values ('t-d', 'a', '2026-05-10', '2026-05-01')")


def test_approval_must_reference_existing_itinerary_version(conn):
    trip_id = _new_trip(conn)
    conn.execute("insert into itinerary_versions (trip_id, version, content, content_hash) "
                 "values (%s, 1, '{}', %s)", (trip_id, HASH))
    ok = ("insert into trip_approvals (trip_id, user_id, itinerary_version, content_hash, decision) "
          "values (%s, 'alice', %s, %s, 'approved')")
    conn.execute(ok, (trip_id, 1, HASH))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(ok, (trip_id, 2, HASH))


def test_itinerary_versions_and_approvals_are_immutable(conn):
    trip_id = _new_trip(conn)
    conn.execute("insert into itinerary_versions (trip_id, version, content, content_hash) "
                 "values (%s, 1, '{}', %s)", (trip_id, HASH))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("update itinerary_versions set total_cost = 1")
    conn.execute("insert into trip_approvals (trip_id, user_id, itinerary_version, content_hash, decision) "
                 "values (%s, 'alice', 1, %s, 'rejected')", (trip_id, HASH))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("update trip_approvals set decision = 'approved'")


def test_content_hash_must_be_sha256_hex(conn):
    trip_id = _new_trip(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into itinerary_versions (trip_id, version, content, content_hash) "
                     "values (%s, 1, '{}', 'nothex')", (trip_id,))
    assert hashlib.sha256(b"x").hexdigest()  # sanity: real hashes are 64 hex chars


def test_one_global_preference_per_user_key_but_trip_override_allowed(conn):
    trip_id = _new_trip(conn)
    ins = "insert into preferences (user_id, trip_id, key, value) values (%s, %s, 'diet', %s::jsonb)"
    conn.execute(ins, ("alice", None, '["vegetarian"]'))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(ins, ("alice", None, '["vegan"]'))
    conn.execute(ins, ("alice", trip_id, '["vegan"]'))      # per-trip override
    conn.execute(ins, ("bob", None, '["halal"]'))           # other user, same key


def test_feedback_version_is_optional_but_must_exist_if_given(conn):
    trip_id = _new_trip(conn)
    ins = "insert into trip_feedback (trip_id, user_id, itinerary_version, message) values (%s, 'alice', %s, 'm')"
    conn.execute(ins, (trip_id, None))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(ins, (trip_id, 9))


def test_deleting_trip_cascades(conn):
    trip_id = _new_trip(conn)
    conn.execute("insert into itinerary_versions (trip_id, version, content, content_hash) "
                 "values (%s, 1, '{}', %s)", (trip_id, HASH))
    conn.execute("insert into trip_feedback (trip_id, user_id, message) values (%s, 'a', 'm')", (trip_id,))
    conn.execute("delete from trips where trip_id = %s", (trip_id,))
    assert conn.execute("select count(*) from itinerary_versions").fetchone()[0] == 0
    assert conn.execute("select count(*) from trip_feedback").fetchone()[0] == 0


def test_shipped_migrations_directory_exists():
    assert (MIGRATIONS_DIR / "0001_core_schema.sql").is_file()