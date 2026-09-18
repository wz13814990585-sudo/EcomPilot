"""Stable business execution lifecycle states."""

from enum import StrEnum


class TaskStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    AWAITING_APPROVAL = "awaiting_approval"


__all__ = ["TaskStatus"]
