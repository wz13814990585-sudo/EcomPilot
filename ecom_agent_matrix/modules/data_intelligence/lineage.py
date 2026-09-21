"""SQL lineage construction without credentials or raw identity secrets."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from ...core.security import TenantScope
from .schemas import SQLLineage, ValidatedSQL


def build_lineage(
    validated: ValidatedSQL,
    *,
    scope: TenantScope,
    row_count: int,
    truncated: bool,
    latency_ms: float,
) -> SQLLineage:
    return SQLLineage(
        query_id=f"sql-{uuid.uuid4()}",
        generated_sql=validated.sql,
        referenced_tables=validated.referenced_tables,
        referenced_columns=validated.referenced_columns,
        timestamp=datetime.now(timezone.utc),
        tenant_id=scope.tenant_id,
        store_id=scope.store_id,
        row_count=row_count,
        truncated=truncated,
        execution_latency_ms=latency_ms,
    )


__all__ = ["build_lineage"]
