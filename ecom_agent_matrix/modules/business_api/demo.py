"""Explicitly local/demo business API adapter; it is not a production connection."""

from __future__ import annotations

from typing import Any

from .contracts import BusinessAPIResponse


class DemoBusinessAPIClient:
    provider = "demo-business-api"

    def __init__(self) -> None:
        self.orders = {
            "ORD-20260301-001": {
                "status": "shipped",
                "tracking_status": "in_transit",
                "sku": "SKU-BAG-001",
            },
            "ORD-20260303-005": {
                "status": "refund_requested",
                "tracking_status": "delivered",
                "sku": "SKU-TENT-005",
            },
        }
        self.inventory = {"SKU-BAG-001": {"available": 120}, "SKU-TENT-005": {"available": 35}}
        self.campaigns = {"CMP-DEMO-001": {"status": "active", "daily_budget": 100.0}}

    def _read(self, operation: str, resource_id: str, source: dict) -> BusinessAPIResponse:
        fields = dict(source.get(resource_id) or {})
        return BusinessAPIResponse(
            provider=self.provider,
            operation=operation,
            resource_id=resource_id,
            found=bool(fields),
            fields=fields,
            demo=True,
        )

    async def get_order(self, order_no: str) -> BusinessAPIResponse:
        return self._read("get_order", order_no, self.orders)

    async def get_inventory(self, sku: str) -> BusinessAPIResponse:
        return self._read("get_inventory", sku, self.inventory)

    async def get_refund_status(self, order_no: str) -> BusinessAPIResponse:
        response = self._read("get_refund_status", order_no, self.orders)
        response.fields = {
            key: value
            for key, value in response.fields.items()
            if key in {"status", "tracking_status"}
        }
        return response

    async def get_campaign(self, campaign_id: str) -> BusinessAPIResponse:
        return self._read("get_campaign", campaign_id, self.campaigns)

    async def get_product(self, sku: str) -> BusinessAPIResponse:
        return self._read("get_product", sku, self.inventory)

    async def mark_order_risk(self, order_no: str, fields: dict[str, Any]) -> BusinessAPIResponse:
        current = self.orders.get(order_no)
        if current is None:
            return self._read("mark_order_risk", order_no, self.orders)
        current.update({"risk_status": fields.get("risk_status", "flagged")})
        return self._read("mark_order_risk", order_no, self.orders)

    async def pause_campaign(self, campaign_id: str, fields: dict[str, Any]) -> BusinessAPIResponse:
        current = self.campaigns.get(campaign_id)
        if current is None:
            return self._read("pause_campaign", campaign_id, self.campaigns)
        current["status"] = "paused"
        return self._read("pause_campaign", campaign_id, self.campaigns)


demo_business_api = DemoBusinessAPIClient()


__all__ = ["DemoBusinessAPIClient", "demo_business_api"]
