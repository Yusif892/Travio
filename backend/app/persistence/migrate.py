"""Minimal SQL migration runner.

* Applies ``db/migrations/*.sql`` in filename order, each in its own transaction.
* Records every applied file with a SHA-256 checksum in ``schema_migrations``.
* Refuses to continue if an already-applied file was edited afterwards
  (add a new numbered migration instead).
* Uses a Postgres advisory lock so two processes cannot migrate at once.

Usage (from the repository root)::

    PYTHONPATH=backend python -m app.persistence.migrate          # DATABASE_URL
    PYTHONPATH=backend python -m app.persistence.migrate --test   # TEST_DATABASE_URL
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import psycopg

from app.persistence.db import get_database_url

# backend/app/persistence/migrate.py -> repository root is parents[3]
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"
_LOCK_ID = 727_005  # arbitrary application-wide advisory lock key


class MigrationError(RuntimeError):
    pass


def apply_migrations(dsn: str, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations and return the file names applied now."""
    files = sorted(Path(migrations_dir).glob("*.sql"))
    applied_now: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            conn.execute(
                "create table if not exists schema_migrations ("
                " filename text primary key,"
                " checksum text not null,"
                " applied_at timestamptz not null default now())"
            )
            done = dict(conn.execute("select filename, checksum from schema_migrations").fetchall())
            for path in files:
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                if path.name in done:
                    if done[path.name] != checksum:
                        raise MigrationError(
                            f"{path.name} was modified after it was applied; create a new migration instead."
                        )
                    continue
                try:
                    with conn.transaction():  # all-or-nothing per file
                        conn.execute(sql)
                        conn.execute(
                            "insert into schema_migrations (filename, checksum) values (%s, %s)",
                            (path.name, checksum),
                        )
                except psycopg.Error as exc:
                    raise MigrationError(f"{path.name} failed and was rolled back: {exc}") from exc
                applied_now.append(path.name)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (_LOCK_ID,))
    return applied_now


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply TRAVIO database migrations.")
    parser.add_argument("--test", action="store_true", help="use TEST_DATABASE_URL")
    args = parser.parse_args()
    applied = apply_migrations(get_database_url(test=args.test))
    print("applied: " + ", ".join(applied) if applied else "database is up to date")


if __name__ == "__main__":
    main()