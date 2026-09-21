"""Stable comparison for seeded PostgreSQL results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return round(float(value), 6)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 6)
    return value


def normalize_rows(rows: list[dict[str, Any]], *, ordered: bool = True) -> list[dict[str, Any]]:
    normalized = [
        {str(key).lower(): normalize_value(value) for key, value in row.items()} for row in rows
    ]
    if not ordered:
        normalized.sort(key=lambda item: repr(sorted(item.items())))
    return normalized


__all__ = ["normalize_rows", "normalize_value"]
