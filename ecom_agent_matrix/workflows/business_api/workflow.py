"""Query-owned read-side business API workflow."""

from __future__ import annotations

import re

from ...core.errors import ErrorCode
from ...core.skill.skill_registry import exec_skill
from ...core.tasking import TaskContext, WorkflowResult, ensure_task_context
from ...platform.observability.metrics import observed_workflow


@observed_workflow("business_api_read")
async def run_business_api_read_workflow(task: dict | TaskContext) -> WorkflowResult:
    ctx = ensure_task_context(task)
    order_no = str(ctx.order_no or "").strip()
    if not order_no:
        match = re.search(r"\bORD[-_][A-Z0-9_-]+\b", ctx.query, re.I)
        order_no = match.group(0) if match else ""
    if not order_no:
        return WorkflowResult(
            success=False,
            error_code=ErrorCode.INVALID_REQUEST.value,
            error_msg="Order number is required",
            data={"query_kind": "business_api"},
        )
    result = await exec_skill(
        "business_api_read", {"operation": "get_order", "resource_id": order_no}
    )
    if not result.success:
        return WorkflowResult(
            success=False,
            error_code=str(result.error_code or ErrorCode.BUSINESS_API_UNAVAILABLE.value),
            error_msg=result.error_msg or "Business API read failed",
            data={"query_kind": "business_api"},
        )
    data = result.data
    summary = (
        f"订单 {order_no} 当前状态：{data['fields'].get('status', 'unknown')}"
        if data["found"]
        else f"演示业务 API 中未找到订单 {order_no}。"
    )
    return WorkflowResult(
        success=True,
        data={"query_kind": "business_api", "summary": summary, **data},
    )
