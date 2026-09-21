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
                "items": [{"sku": "BAG-001", "quantity": 1}],
                "amount": 79.0,
            },
            "ORD-20260303-005": {
                "status": "refund_requested",
                "tracking_status": "delivered",
                "items": [{"sku": "TENT-001", "quantity": 1}],
                "amount": 189.0,
            },
            "ORD-DEMO-001": {
                "status": "shipped",
                "payment_status": "paid",
                "fulfillment": "fulfilled",
                "tracking_status": "in_transit",
                "shipping": "Australia Post / SYD-MEL",
                "refund_state": "none",
                "items": [{"sku": "BAG-001", "quantity": 1}],
                "amount": 79.0,
            },
            "ORD-DEMO-002": {
                "status": "processing",
                "payment_status": "paid",
                "fulfillment": "unfulfilled",
                "shipping": "label_pending",
                "refund_state": "none",
                "items": [{"sku": "LAMP-001", "quantity": 2}],
                "amount": 98.0,
            },
            "ORD-DEMO-REFUND": {
                "status": "refund_requested",
                "payment_status": "paid",
                "fulfillment": "fulfilled",
                "tracking_status": "delivered",
                "shipping": "delivered",
                "refund_state": "pending_review",
                "items": [{"sku": "BAG-002", "quantity": 1}],
                "amount": 99.0,
            },
            "ORD-DEMO-RISK": {
                "status": "manual_review",
                "payment_status": "paid",
                "fulfillment": "held",
                "shipping": "on_hold",
                "refund_state": "none",
                "items": [{"sku": "CHARGER-001", "quantity": 8}],
                "amount": 792.0,
                "risk_status": "review_required",
            },
        }
        self.inventory = {
            "BAG-001": {"available": 120},
            "BAG-002": {"available": 8},
            "SKU-BAG-001": {"available": 120},
            "SKU-TENT-005": {"available": 35},
        }
        self.campaigns = {
            "CMP-TIKTOK-BAG": {
                "name": "TikTok Backpack Launch",
                "platform": "tiktok",
                "status": "active",
                "daily_budget": 120.0,
                "spend": 1840.0,
                "impressions": 210000,
                "clicks": 4620,
                "conversions": 184,
                "revenue": 9200.0,
            },
            "CMP-GOOGLE-BRAND": {
                "name": "Google Brand Search",
                "platform": "google",
                "status": "active",
                "daily_budget": 80.0,
                "spend": 960.0,
                "impressions": 68000,
                "clicks": 2850,
                "conversions": 132,
                "revenue": 6600.0,
            },
            "CMP-META-RETARGET": {
                "name": "Meta Retargeting",
                "platform": "meta",
                "status": "active",
                "daily_budget": 95.0,
                "spend": 2140.0,
                "impressions": 310000,
                "clicks": 3280,
                "conversions": 41,
                "revenue": 2050.0,
            },
            "CMP-SUMMER-SALE": {
                "name": "Summer Outdoor Sale",
                "platform": "meta",
                "status": "active",
                "daily_budget": 140.0,
                "spend": 2760.0,
                "impressions": 405000,
                "clicks": 3900,
                "conversions": 18,
                "revenue": 990.0,
            },
        }
        for fields in self.campaigns.values():
            spend = float(fields["spend"])
            clicks = int(fields["clicks"])
            conversions = int(fields["conversions"])
            fields.update(
                {
                    "ctr": round(clicks / int(fields["impressions"]) * 100, 2),
                    "cpc": round(spend / clicks, 2),
                    "cpa": round(spend / conversions, 2),
                    "roas": round(float(fields["revenue"]) / spend, 2),
                }
            )

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

    async def list_campaigns(self, resource_id: str = "all") -> BusinessAPIResponse:
        campaigns = [
            {"campaign_id": campaign_id, **fields} for campaign_id, fields in self.campaigns.items()
        ]
        return BusinessAPIResponse(
            provider=self.provider,
            operation="list_campaigns",
            resource_id=resource_id,
            found=bool(campaigns),
            fields={"campaigns": campaigns, "count": len(campaigns)},
            demo=True,
        )

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
