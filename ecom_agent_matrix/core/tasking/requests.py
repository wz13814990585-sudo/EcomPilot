"""Typed business requests carried by the common task envelope."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BusinessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    query: str = ""


class GoodsSearchRequest(BusinessRequest):
    sku: str | None = None
    product_name: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class OrderQueryRequest(BusinessRequest):
    order_no: str


class CompetitorWatchRequest(BusinessRequest):
    sku: str | None = None
    mode: Literal["single", "multi"] = "single"
    competitor: str | None = None
    compete_price: float | None = Field(default=None, gt=0)
    warn_threshold: float = Field(default=-10, le=0)
    platforms: list[str] = Field(default_factory=list)


class CRMReplyRequest(BusinessRequest):
    session_id: str | None = None
    order_no: str | None = None
    lang: str = "zh"


class ProfitInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    cost: float = Field(ge=0)
    shipping: float = Field(ge=0)
    commission_rate: float = Field(ge=0, lt=1)
    sell_price: float = Field(ge=0)


class AdOptimizeRequest(BusinessRequest):
    sku: str | None = None
    campaign_id: str | None = None
    platform: Literal["meta", "google", "tiktok", "amazon"] = "meta"
    spend: float = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)
    revenue: float = Field(default=0, ge=0)
    daily_budget: float | None = Field(default=None, gt=0)
    bid: float | None = Field(default=None, gt=0)
    target_roas: float = Field(default=2.0, gt=0)
    profit: ProfitInputs | None = None

    def skill_params(self) -> dict[str, Any]:
        return self.model_dump(exclude={"query", "profit"})


class RiskOperationRequest(BusinessRequest):
    order_no: str = Field(min_length=1)
    total_amount: float = Field(ge=0)
    buy_count: int = Field(ge=1)

    def skill_params(self) -> dict[str, Any]:
        return self.model_dump(exclude={"query"})


class DataCheckRequest(BusinessRequest):
    scope: Literal["goods", "order", "full"] = "full"
    sku: str | None = None
    order_no: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    custom_sql: str | None = None
    sql_params: list[Any] | dict[str, Any] = Field(default_factory=list)
    run_nl_sql: bool = False


__all__ = [
    "AdOptimizeRequest",
    "BusinessRequest",
    "CRMReplyRequest",
    "CompetitorWatchRequest",
    "DataCheckRequest",
    "GoodsSearchRequest",
    "OrderQueryRequest",
    "ProfitInputs",
    "RiskOperationRequest",
]
