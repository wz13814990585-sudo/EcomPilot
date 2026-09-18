"""Workflow 层统一结果模型。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from ..errors import ErrorCode
from .status import TaskStatus

INVALID_REQUEST = ErrorCode.INVALID_REQUEST.value
MISSING_PRODUCT = ErrorCode.MISSING_PRODUCT.value
UNSUPPORTED_PLATFORM = ErrorCode.UNSUPPORTED_PLATFORM.value
SKILL_FAILED = ErrorCode.SKILL_FAILED.value
WORKFLOW_TIMEOUT = ErrorCode.WORKFLOW_TIMEOUT.value
PARTIAL_SUCCESS = ErrorCode.PARTIAL_SUCCESS.value
MISSING_SKU = ErrorCode.MISSING_SKU.value
MISSING_COMPETITOR = ErrorCode.MISSING_COMPETITOR.value
PRICE_UNAVAILABLE = ErrorCode.PRICE_UNAVAILABLE.value
UNSUPPORTED_REPORT_TYPE = ErrorCode.UNSUPPORTED_REPORT_TYPE.value


class WorkflowResult(BaseModel):
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: ErrorCode | None = None
    error_msg: str = ""
    partial_success: bool = False
    status: TaskStatus | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("error_code", mode="before")
    @classmethod
    def empty_error_is_none(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def derive_status(self):
        if self.status is None:
            if self.success and self.partial_success:
                self.status = TaskStatus.PARTIAL
            elif self.success:
                self.status = TaskStatus.SUCCEEDED
            elif self.error_code == ErrorCode.APPROVAL_REQUIRED:
                self.status = TaskStatus.AWAITING_APPROVAL
            else:
                self.status = TaskStatus.FAILED
        return self

    def to_legacy_data(self) -> dict[str, Any]:
        """保留 tuple 形状，同时携带 typed workflow 状态。"""
        data = deepcopy(self.data)
        data["_workflow"] = {
            "error_code": self.error_code,
            "partial_success": self.partial_success,
            "status": self.status,
            "metadata": deepcopy(self.metadata),
        }
        return data

    def as_legacy_tuple(self) -> tuple[bool, str, dict]:
        """兼容现有 Handler 的 ``(ok, error_msg, data)`` 返回值。"""
        return self.success, self.error_msg, self.to_legacy_data()
