"""Typed business requests carried by the common task envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BusinessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = ""


class GoodsSearchRequest(BusinessRequest):
    sku: str | None = None
    product_name: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class OrderQueryRequest(BusinessRequest):
    order_no: str


class CompetitorWatchRequest(BusinessRequest):
    sku: str
    competitor: str
    compete_price: float | None = Field(default=None, ge=0)


class CRMReplyRequest(BusinessRequest):
    session_id: str | None = None
    order_no: str | None = None
    lang: str = "zh"


class AdOptimizeRequest(BusinessRequest):
    campaign_id: str
    platform: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class RiskOperationRequest(BusinessRequest):
    order_no: str
    risk_type: str
    risk_desc: str


__all__ = [
    "AdOptimizeRequest",
    "BusinessRequest",
    "CRMReplyRequest",
    "CompetitorWatchRequest",
    "GoodsSearchRequest",
    "OrderQueryRequest",
    "RiskOperationRequest",
]
