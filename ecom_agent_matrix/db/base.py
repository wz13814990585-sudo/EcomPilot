"""Separated read/write PostgreSQL pools with transaction-local tenant scope."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import aiopg

from ..config.settings import settings
from ..core.security import TenantScope, require_tenant_scope
from ..core.security import tenant_scope_from_skill_context


class AsyncPGClient:
    _pool = None  # legacy/admin compatibility
    _read_pool = None
    _write_pool = None

    @classmethod
    def _dsn(cls, role: Literal["legacy", "read", "write"]) -> str:
        if role == "read":
            user = settings.PG_READ_USER or settings.PG_USER
            password = settings.PG_READ_PWD or settings.PG_PWD
        elif role == "write":
            user = settings.PG_WRITE_USER or settings.PG_USER
            password = settings.PG_WRITE_PWD or settings.PG_PWD
        else:
            user, password = settings.PG_USER, settings.PG_PWD
        return (
            f"host={settings.PG_HOST} port={settings.PG_PORT} "
            f"user={user} password={password} dbname={settings.PG_DB}"
        )

    @classmethod
    async def get_pool(cls):
        if cls._pool is None:
            cls._pool = await aiopg.create_pool(
                cls._dsn("legacy"),
                minsize=settings.DB_POOL_MIN_SIZE,
                maxsize=settings.DB_POOL_MAX_SIZE,
                timeout=settings.DB_CONNECT_TIMEOUT,
            )
        return cls._pool

    @classmethod
    async def get_read_pool(cls):
        if cls._read_pool is None:
            cls._read_pool = await aiopg.create_pool(
                cls._dsn("read"),
                minsize=settings.DB_POOL_MIN_SIZE,
                maxsize=settings.DB_POOL_MAX_SIZE,
                timeout=settings.DB_CONNECT_TIMEOUT,
            )
        return cls._read_pool

    @classmethod
    async def get_write_pool(cls):
        if cls._write_pool is None:
            cls._write_pool = await aiopg.create_pool(
                cls._dsn("write"),
                minsize=settings.DB_POOL_MIN_SIZE,
                maxsize=settings.DB_POOL_MAX_SIZE,
                timeout=settings.DB_CONNECT_TIMEOUT,
            )
        return cls._write_pool

    @classmethod
    async def execute_sql(cls, sql: str, params: list | None = None):
        """Legacy/dev/migration API. Production business code uses explicit methods."""
        pool = await cls.get_pool()
        async with asyncio.timeout(float(settings.DB_ACQUIRE_TIMEOUT)):
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    if params:
                        await cur.execute(sql, params)
                    else:
                        await cur.execute(sql)
                    return await cur.fetchall() if cur.description else []

    @classmethod
    async def _execute_scoped(
        cls,
        *,
        role: Literal["read", "write"],
        sql: str,
        params: list | dict | None,
        scope: TenantScope,
        max_rows: int | None = None,
    ) -> tuple[list[Any], bool]:
        require_tenant_scope(
            scope,
            production=str(settings.APP_ENV).lower() == "production",
        )
        pool = await (cls.get_read_pool() if role == "read" else cls.get_write_pool())
        timeout_ms = (
            settings.DB_READ_STATEMENT_TIMEOUT_MS
            if role == "read"
            else settings.DB_WRITE_STATEMENT_TIMEOUT_MS
        )
        async with asyncio.timeout(float(settings.DB_ACQUIRE_TIMEOUT)):
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # aiopg core exposes transaction contexts on Cursor, not Connection.
                    # All local settings and the business statement share this boundary.
                    async with cur.begin():
                        if role == "read":
                            await cur.execute("SET TRANSACTION READ ONLY")
                        await cur.execute(
                            "SELECT set_config('statement_timeout', %s, true)",
                            [str(int(timeout_ms))],
                        )
                        # set_config(..., true) is transaction-local and cannot leak through pooling.
                        await cur.execute(
                            "SELECT set_config('app.tenant_id', %s, true), "
                            "set_config('app.store_id', %s, true)",
                            [
                                scope.tenant_id if scope.usable else "",
                                scope.store_id if scope.usable else "",
                            ],
                        )
                        await cur.execute(sql, params or [])
                        if not cur.description:
                            return [], False
                        if max_rows is None:
                            return list(await cur.fetchall()), False
                        rows = list(await cur.fetchmany(max_rows + 1))
                        return rows[:max_rows], len(rows) > max_rows

    @classmethod
    async def execute_read(
        cls,
        sql: str,
        params: list | dict | None = None,
        *,
        scope: TenantScope | None = None,
    ) -> list[Any]:
        scope = scope or tenant_scope_from_skill_context()
        rows, _ = await cls._execute_scoped(
            role="read", sql=sql, params=params, scope=scope or TenantScope()
        )
        return rows

    @classmethod
    async def execute_read_bounded(
        cls,
        sql: str,
        params: list | dict | None = None,
        *,
        scope: TenantScope | None = None,
        max_rows: int | None = None,
    ) -> tuple[list[Any], bool]:
        scope = scope or tenant_scope_from_skill_context()
        limit = max(1, int(max_rows or settings.DB_READ_MAX_ROWS))
        return await cls._execute_scoped(
            role="read", sql=sql, params=params, scope=scope or TenantScope(), max_rows=limit
        )

    @classmethod
    async def execute_write(
        cls,
        sql: str,
        params: list | dict | None = None,
        *,
        scope: TenantScope | None = None,
    ) -> list[Any]:
        scope = scope or tenant_scope_from_skill_context()
        rows, _ = await cls._execute_scoped(
            role="write", sql=sql, params=params, scope=scope or TenantScope()
        )
        return rows

    @classmethod
    async def execute_system(cls, sql: str, params: list | None = None) -> list[Any]:
        return await cls.execute_sql(sql, params)

    @classmethod
    async def execute_health(cls, role: Literal["read", "write"] = "read") -> list[Any]:
        """Probe an application runtime role without using legacy/admin credentials."""
        pool = await (cls.get_read_pool() if role == "read" else cls.get_write_pool())
        async with asyncio.timeout(float(settings.DB_ACQUIRE_TIMEOUT)):
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1 AS ok")
                    return list(await cur.fetchall())

    @classmethod
    async def execute_metadata(cls, sql: str, params: list | None = None) -> list[Any]:
        """Execute fixed catalog-discovery reads through the read-only application pool."""
        pool = await cls.get_read_pool()
        async with asyncio.timeout(float(settings.DB_ACQUIRE_TIMEOUT)):
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    async with cur.begin():
                        await cur.execute("SET TRANSACTION READ ONLY")
                        await cur.execute(sql, params or [])
                        return list(await cur.fetchall())

    @classmethod
    async def close(cls):
        for attr in ("_pool", "_read_pool", "_write_pool"):
            pool = getattr(cls, attr)
            if pool:
                pool.close()
                await pool.wait_closed()
                setattr(cls, attr, None)


def validate_database_security_configuration(config=settings) -> None:
    if str(config.APP_ENV or "").strip().lower() != "production":
        return
    read_user = str(config.PG_READ_USER or "").strip()
    read_password = str(config.PG_READ_PWD or "").strip()
    write_user = str(config.PG_WRITE_USER or "").strip()
    write_password = str(config.PG_WRITE_PWD or "").strip()
    if (
        not read_user
        or not read_password
        or not write_user
        or not write_password
        or read_user == write_user
    ):
        raise RuntimeError("READ_DB_CONFIGURATION_INVALID")


async def validate_database_runtime_roles(config=settings) -> None:
    """Fail production startup if either application role can bypass RLS."""
    if str(config.APP_ENV or "").strip().lower() != "production":
        return
    for role, pool_getter in (
        ("READ", AsyncPGClient.get_read_pool),
        ("WRITE", AsyncPGClient.get_write_pool),
    ):
        try:
            pool = await pool_getter()
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                    row = await cur.fetchone()
            if not row or bool(row[0]) or bool(row[1]):
                raise RuntimeError(f"{role}_DB_ROLE_INVALID")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"{role}_DB_ROLE_VALIDATION_FAILED") from exc


__all__ = [
    "AsyncPGClient",
    "validate_database_runtime_roles",
    "validate_database_security_configuration",
]
