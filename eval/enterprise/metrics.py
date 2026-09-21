"""Diagnosable schema-linking and enterprise benchmark metrics."""

from __future__ import annotations


def precision_recall(actual: set[str], expected: set[str]) -> tuple[float, float]:
    true_positive = len(actual.intersection(expected))
    precision = true_positive / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else 1.0
    return round(precision, 6), round(recall, 6)


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


__all__ = ["mean", "precision_recall"]
