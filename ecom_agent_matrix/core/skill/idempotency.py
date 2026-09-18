"""Idempotency records for side-effecting skills."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.security.scope import TenantScope
from ecom_agent_matrix.db.base import AsyncPGClient


@dataclass(frozen=True)
class IdempotencyRecord:
    status: str
    result: dict | None = None


class IdempotencyStore(Protocol):
    async def get(self, key: str, *, scope: TenantScope) -> IdempotencyRecord | None: ...
    async def begin(
        self, key: str, *, scope: TenantScope, task_id: str, skill_name: str
    ) -> bool: ...
    async def complete(self, key: str, *, scope: TenantScope, result: dict) -> None: ...
    async def fail(self, key: str, *, scope: TenantScope, error_code: str) -> None: ...


def idempotency_key(
    *, tenant_id: str, store_id: str, task_id: str, skill_name: str, params: dict
) -> str:
    canonical = json.dumps(
        [tenant_id, store_id, task_id, skill_name, params],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str, *, scope: TenantScope) -> IdempotencyRecord | None:
        return self._records.get(key)

    async def begin(self, key: str, *, scope: TenantScope, task_id: str, skill_name: str) -> bool:
        async with self._lock:
            if key in self._records:
                return False
            self._records[key] = IdempotencyRecord("running")
            return True

    async def complete(self, key: str, *, scope: TenantScope, result: dict) -> None:
        self._records[key] = IdempotencyRecord("succeeded", result)

    async def fail(self, key: str, *, scope: TenantScope, error_code: str) -> None:
        self._records[key] = IdempotencyRecord("failed", {"error_code": error_code})


class PostgresIdempotencyStore:
    async def get(self, key: str, *, scope: TenantScope) -> IdempotencyRecord | None:
        rows = await AsyncPGClient.execute_write(
            "SELECT status,result_json FROM skill_execution_idempotency "
            "WHERE idempotency_key=%s AND tenant_id=%s AND store_id=%s",
            [key, scope.tenant_id, scope.store_id],
            scope=scope,
        )
        if not rows:
            return None
        raw = rows[0][1]
        if isinstance(raw, str):
            raw = json.loads(raw)
        return IdempotencyRecord(str(rows[0][0]), raw if isinstance(raw, dict) else None)

    async def begin(self, key: str, *, scope: TenantScope, task_id: str, skill_name: str) -> bool:
        rows = await AsyncPGClient.execute_write(
            "INSERT INTO skill_execution_idempotency"
            "(idempotency_key,tenant_id,store_id,task_id,skill_name,status,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,'running',%s,%s) "
            "ON CONFLICT (idempotency_key) DO NOTHING RETURNING idempotency_key",
            [
                key,
                scope.tenant_id,
                scope.store_id,
                task_id,
                skill_name,
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
            ],
            scope=scope,
        )
        return bool(rows)

    async def complete(self, key: str, *, scope: TenantScope, result: dict) -> None:
        await AsyncPGClient.execute_write(
            "UPDATE skill_execution_idempotency SET status='succeeded',result_json=%s::jsonb,"
            "updated_at=%s WHERE idempotency_key=%s AND tenant_id=%s AND store_id=%s",
            [
                json.dumps(result, ensure_ascii=False, default=str),
                datetime.now(timezone.utc),
                key,
                scope.tenant_id,
                scope.store_id,
            ],
            scope=scope,
        )

    async def fail(self, key: str, *, scope: TenantScope, error_code: str) -> None:
        await AsyncPGClient.execute_write(
            "UPDATE skill_execution_idempotency SET status='failed',error_code=%s,updated_at=%s "
            "WHERE idempotency_key=%s AND tenant_id=%s AND store_id=%s",
            [error_code, datetime.now(timezone.utc), key, scope.tenant_id, scope.store_id],
            scope=scope,
        )


default_idempotency_store: IdempotencyStore = (
    PostgresIdempotencyStore()
    if str(settings.APP_ENV).lower() == "production"
    else MemoryIdempotencyStore()
)

__all__ = [
    "IdempotencyRecord",
    "IdempotencyStore",
    "MemoryIdempotencyStore",
    "PostgresIdempotencyStore",
    "default_idempotency_store",
    "idempotency_key",
]
