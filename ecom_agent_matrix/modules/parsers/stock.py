"""库存领域 TaskContext → StockRequest 解析。"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from ...core.tasking import TaskContext

_SKU_PATTERN = re.compile(
    r"\b(?:SKU[-_])?(?:BAG|LAMP|BOTTLE|CHARGER|TENT|BEAUTY|HOME|ACC)[-_]\d{3}\b",
    re.IGNORECASE,
)


class StockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str | None = None
    predict_days: int = Field(default=7, ge=1, le=90)


def extract_stock_sku(task: TaskContext) -> str | None:
    """只提取 canonical/query SKU，不耦合库存预测参数校验。"""
    sku = task.sku
    if not sku:
        match = _SKU_PATTERN.search(task.query)
        sku = match.group(0).upper() if match else None
    return sku


def parse_stock_request(task: TaskContext) -> StockRequest:
    """只从 canonical sku 或 query 中明确的 SKU 格式读取标识。"""
    day_match = re.search(r"(?:未来)?\s*(\d{1,2})\s*天", task.query)
    predict_days = int(day_match.group(1)) if day_match else task.params.get("predict_days", 7)
    return StockRequest(
        sku=extract_stock_sku(task),
        predict_days=predict_days,
    )
