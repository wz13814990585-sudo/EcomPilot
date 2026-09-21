"""Typed provider-neutral business API contracts."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class BusinessAPIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    operation: str
    resource_id: str
    found: bool
    fields: dict[str, Any] = Field(default_factory=dict)
    demo: bool = False


class BusinessAPIClient(Protocol):
    provider: str

    async def get_order(self, order_no: str) -> BusinessAPIResponse: ...

    async def get_inventory(self, sku: str) -> BusinessAPIResponse: ...

    async def get_refund_status(self, order_no: str) -> BusinessAPIResponse: ...

    async def get_campaign(self, campaign_id: str) -> BusinessAPIResponse: ...

    async def get_product(self, sku: str) -> BusinessAPIResponse: ...

    async def mark_order_risk(
        self, order_no: str, fields: dict[str, Any]
    ) -> BusinessAPIResponse: ...

    async def pause_campaign(
        self, campaign_id: str, fields: dict[str, Any]
    ) -> BusinessAPIResponse: ...


__all__ = ["BusinessAPIClient", "BusinessAPIResponse"]
