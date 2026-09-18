"""Small, explicit metric helpers for evaluation reports."""

from __future__ import annotations


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def case_totals(cases: list[dict]) -> dict[str, int]:
    return {
        status.lower(): sum(case.get("status") == status for case in cases)
        for status in ("PASS", "FAIL", "NOT_RUN", "DEGRADED")
    }


def section_status(cases: list[dict]) -> str:
    statuses = {case.get("status") for case in cases}
    if "FAIL" in statuses:
        return "FAIL"
    if statuses == {"NOT_RUN"} or not statuses:
        return "NOT_RUN"
    if "NOT_RUN" in statuses or "DEGRADED" in statuses:
        return "DEGRADED"
    return "PASS"


__all__ = ["case_totals", "rate", "section_status"]
