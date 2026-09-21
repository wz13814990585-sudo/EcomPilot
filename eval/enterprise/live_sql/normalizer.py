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


def compare_rows(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    float_tolerance: float = 0.000001,
) -> bool:
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected, strict=True):
        if set(actual_row) != set(expected_row):
            return False
        for key, expected_value in expected_row.items():
            actual_value = actual_row[key]
            if isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)):
                if abs(float(actual_value) - float(expected_value)) > float_tolerance:
                    return False
            elif actual_value != expected_value:
                return False
    return True


__all__ = ["compare_rows", "normalize_rows", "normalize_value"]
