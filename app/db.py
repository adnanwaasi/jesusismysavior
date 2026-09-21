from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def create_db_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def apply_migrations(engine: Engine) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    with engine.begin() as connection:
        # Monitor and every worker may start together. Serialize the tiny migration
        # transaction so only one process can apply a version at a time.
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(4815162342)")
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {row[0] for row in connection.exec_driver_sql("SELECT version FROM schema_migrations")}
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in applied:
                continue
            connection.exec_driver_sql(path.read_text())
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": path.name})
