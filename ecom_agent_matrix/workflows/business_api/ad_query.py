"""Query-owned deterministic advertising metrics workflow."""

from __future__ import annotations

from ...core.errors import ErrorCode
from ...core.skill.skill_registry import exec_skill
from ...core.tasking import TaskContext, WorkflowResult, ensure_task_context
from ...platform.observability.metrics import observed_workflow


@observed_workflow("advertising_query")
async def run_ad_query_workflow(task: dict | TaskContext) -> WorkflowResult:
    ctx = ensure_task_context(task)
    campaign_id = str(ctx.campaign_id or ctx.params.get("campaign_id") or "").strip()
    operation = "get_campaign" if campaign_id else "list_campaigns"
    result = await exec_skill(
        "business_api_read", {"operation": operation, "resource_id": campaign_id or "all"}
    )
    if not result.success:
        return WorkflowResult(
            success=False,
            error_code=str(result.error_code or ErrorCode.BUSINESS_API_UNAVAILABLE.value),
            error_msg=result.error_msg or "Advertising data unavailable",
            data={"query_kind": "advertising"},
        )
    fields = result.data.get("fields") or {}
    campaigns = fields.get("campaigns") or (
        [{"campaign_id": campaign_id, **fields}] if result.data.get("found") else []
    )
    campaigns = sorted(campaigns, key=lambda item: float(item.get("roas") or 0))
    worst = campaigns[0] if campaigns else None
    summary = (
        f"ROAS 最低的广告是 {worst['name']}（{worst['campaign_id']}），ROAS {worst['roas']}。"
        if worst
        else "没有可用的广告活动数据。"
    )
    return WorkflowResult(
        success=True,
        data={
            "query_kind": "advertising",
            "summary": summary,
            "campaigns": campaigns,
            "worst_campaign": worst,
            "evidence": result.data.get("evidence"),
        },
    )


__all__ = ["run_ad_query_workflow"]
