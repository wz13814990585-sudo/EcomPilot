"""Shared PostgreSQL fixtures for enterprise integration evaluation."""

from __future__ import annotations

from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from ecom_agent_matrix.config.settings import settings

HERE = Path(__file__).parent
READ_ROLE = "ecom_eval_read"
READ_PASSWORD = "eval_read_password"


def connect_admin():
    return psycopg2.connect(
        host=settings.PG_HOST,
        port=settings.PG_PORT,
        user=settings.PG_USER,
        password=settings.PG_PWD,
        dbname=settings.PG_DB,
        connect_timeout=3,
    )


def connect_read():
    return psycopg2.connect(
        host=settings.PG_HOST,
        port=settings.PG_PORT,
        user=settings.PG_READ_USER or READ_ROLE,
        password=settings.PG_READ_PWD or READ_PASSWORD,
        dbname=settings.PG_DB,
        connect_timeout=3,
    )


def seed_database() -> None:
    connection = connect_admin()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute((HERE / "seed.sql").read_text())
    finally:
        connection.close()


def execute_scoped(
    connection,
    sql: str,
    *,
    tenant_id: str = "tenant-a",
    store_id: str = "store-a",
) -> list[dict]:
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("BEGIN READ ONLY")
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [tenant_id])
            cursor.execute("SELECT set_config('app.store_id', %s, true)", [store_id])
            cursor.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        connection.commit()
        return rows
    except Exception:
        connection.rollback()
        raise


__all__ = [
    "READ_PASSWORD",
    "READ_ROLE",
    "connect_admin",
    "connect_read",
    "execute_scoped",
    "seed_database",
]
