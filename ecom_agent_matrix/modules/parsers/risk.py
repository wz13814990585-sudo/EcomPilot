"""订单风控领域 TaskContext → RiskRequest 解析。"""

from __future__ import annotations

import re

from ...core.tasking import RiskOperationRequest, TaskContext

_ORDER_PATTERN = re.compile(r"\b(?:ORD[-_][A-Z0-9_-]+|\d{10,20})\b", re.IGNORECASE)


RiskRequest = RiskOperationRequest


def parse_risk_request(task: TaskContext) -> RiskRequest:
    order_no = task.order_no
    if not order_no:
        match = _ORDER_PATTERN.search(task.query)
        order_no = match.group(0) if match else ""
    params = task.params
    return RiskRequest(
        order_no=order_no,
        total_amount=params.get("total_amount"),
        buy_count=params.get("buy_count", params.get("buy_num")),
    )
