"""Read-only bounded SQL execution and result-quality validation."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ...config.settings import settings
from ...core.security import TenantScope
from ...db.base import AsyncPGClient
from .lineage import build_lineage
from .schemas import ColumnAccess, SQLExecutionResult, SchemaCatalog, ValidatedSQL

ReadExecutor = Callable[..., Awaitable[tuple[list[Any], bool]]]


class SQLExecutionFailure(RuntimeError):
    def __init__(self, category: str, *, repairable: bool) -> None:
        self.category = category
        self.repairable = repairable
        super().__init__(category)


def classify_execution_error(exc: Exception) -> SQLExecutionFailure:
    text = f"{type(exc).__name__} {exc}".lower()
    non_repairable = ("permission", "rls", "read-only", "timeout", "cancel", "too many")
    if any(marker in text for marker in non_repairable):
        category = (
            "permission_denied" if "permission" in text or "rls" in text else "execution_guard"
        )
        return SQLExecutionFailure(category, repairable=False)
    repairable_markers = {
        "undefinedcolumn": "undefined_column",
        "undefined column": "undefined_column",
        "undefinedtable": "undefined_table",
        "does not exist": "undefined_identifier",
        "ambiguous": "ambiguous_column",
        "datatype": "type_mismatch",
        "type mismatch": "type_mismatch",
        "syntax": "syntax_error",
    }
    for marker, category in repairable_markers.items():
        if marker in text:
            return SQLExecutionFailure(category, repairable=True)
    return SQLExecutionFailure("database_error", repairable=False)


def _mask(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if "@" in text:
        local, domain = text.split("@", 1)
        return f"{local[:1]}***@{domain}"
    if len(text) >= 4:
        return f"***{text[-4:]}"
    return "***"


def _normalize_rows(rows: list[Any], output_columns: tuple[str, ...]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(dict(row))
            continue
        values = list(row) if isinstance(row, (tuple, list)) else [row]
        names = list(output_columns)
        if len(names) != len(values) or "*" in names:
            names = [f"column_{index + 1}" for index in range(len(values))]
        normalized.append(dict(zip(names, values, strict=True)))
    return normalized


def _apply_output_policy(
    rows: list[dict[str, Any]], validated: ValidatedSQL, catalog: SchemaCatalog
) -> list[dict[str, Any]]:
    masked_names: set[str] = set()
    for reference in validated.referenced_columns:
        table_name, _, column_name = reference.partition(".")
        table = catalog.table(table_name)
        column = table.column(column_name) if table else None
        if column and column.access == ColumnAccess.MASK:
            masked_names.add(column_name)
    masked_names.update(name.lower() for name in validated.masked_output_columns)
    return [
        {
            key: (_mask(value) if key.lower() in masked_names else value)
            for key, value in row.items()
        }
        for row in rows
    ]


def _quality(rows: list[dict[str, Any]], truncated: bool) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not rows:
        warnings.append("EMPTY_RESULT")
    values = [value for row in rows for value in row.values()]
    if values and sum(value is None for value in values) / len(values) >= 0.5:
        warnings.append("NULL_HEAVY_RESULT")
    if any(
        isinstance(value, float) and (math.isnan(value) or math.isinf(value)) for value in values
    ):
        warnings.append("INVALID_NUMERIC_VALUE")
    if truncated:
        warnings.append("RESULT_TRUNCATED")
    quality = "valid" if not warnings else "empty" if warnings == ["EMPTY_RESULT"] else "warning"
    return quality, warnings


class SafeSQLExecutor:
    def __init__(self, execute_read: ReadExecutor | None = None) -> None:
        self.execute_read = execute_read or AsyncPGClient.execute_read_bounded

    async def execute(
        self,
        validated: ValidatedSQL,
        *,
        params: list[Any] | dict[str, Any],
        scope: TenantScope,
        catalog: SchemaCatalog,
        max_rows: int,
    ) -> SQLExecutionResult:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(float(settings.SQL_QUERY_TIMEOUT)):
                rows, truncated = await self.execute_read(
                    validated.sql,
                    params,
                    scope=scope,
                    max_rows=max_rows,
                )
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception as exc:
            raise classify_execution_error(exc) from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        normalized = _normalize_rows(list(rows), validated.output_columns)
        normalized = _apply_output_policy(normalized, validated, catalog)
        quality, warnings = _quality(normalized, bool(truncated))
        lineage = build_lineage(
            validated,
            scope=scope,
            row_count=len(normalized),
            truncated=bool(truncated),
            latency_ms=latency_ms,
        )
        return SQLExecutionResult(
            rows=normalized,
            row_count=len(normalized),
            truncated=bool(truncated),
            result_quality=quality,
            warnings=warnings,
            lineage=lineage,
        )


__all__ = [
    "SQLExecutionFailure",
    "SafeSQLExecutor",
    "classify_execution_error",
]
