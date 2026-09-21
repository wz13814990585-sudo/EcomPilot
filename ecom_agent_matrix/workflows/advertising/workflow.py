"""Advertising optimization workflow."""

from __future__ import annotations

import time

from pydantic import ValidationError
from ...platform.observability.metrics import observed_workflow

from ...config.constants import AGENT_EXEC
from ...core.memory.long_vector_memory import AgentLongVectorMemory
from ...core.skill.skill_registry import exec_skill
from ...core.tasking import TaskContext, WorkflowResult, ensure_task_context
from ...core.tasking.result import (
    INVALID_REQUEST,
    PARTIAL_SUCCESS,
    SKILL_FAILED,
    UNSUPPORTED_PLATFORM,
)
from ...modules.parsers.ad import (
    IncompleteProfitInputs,
    UnsupportedAdPlatform,
    parse_ad_request,
)
from ...modules.skills.ad_optimize import SUPPORTED_AD_PLATFORMS
from ...core.errors import ErrorCode

_long_mem: AgentLongVectorMemory | None = None


def _mem() -> AgentLongVectorMemory:
    global _long_mem
    if _long_mem is None:
        _long_mem = AgentLongVectorMemory()
    return _long_mem


def _metadata(started: float, **extra) -> dict:
    return {
        "workflow": "ad",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        **extra,
    }


@observed_workflow("ad")
async def run_ad_workflow(task: dict | TaskContext) -> WorkflowResult:
    started = time.perf_counter()
    ctx = ensure_task_context(task)
    requested_pause = any(word in ctx.query.lower() for word in ("暂停", "停止", "pause"))
    fixture_campaign: dict = {}
    if requested_pause and not ctx.campaign_id:
        lookup = await exec_skill(
            "business_api_read", {"operation": "list_campaigns", "resource_id": "all"}
        )
        campaigns = ((lookup.data or {}).get("fields") or {}).get("campaigns") or []
        active = [item for item in campaigns if item.get("status") == "active"]
        if active:
            lowered = ctx.query.lower()
            named = next(
                (item for item in active if str(item.get("name") or "").lower() in lowered), None
            )
            fixture_campaign = named or min(active, key=lambda item: float(item.get("roas") or 0))
            enriched = dict(ctx.params)
            enriched.update(
                {
                    "campaign_id": fixture_campaign.get("campaign_id"),
                    "platform": fixture_campaign.get("platform"),
                    "spend": fixture_campaign.get("spend", 0),
                    "clicks": fixture_campaign.get("clicks", 0),
                    "conversions": fixture_campaign.get("conversions", 0),
                    "revenue": fixture_campaign.get("revenue", 0),
                    "daily_budget": fixture_campaign.get("daily_budget"),
                }
            )
            ctx = ctx.with_updates(params=enriched)
    try:
        request = parse_ad_request(ctx)
    except UnsupportedAdPlatform as exc:
        return WorkflowResult(
            success=False,
            error_code=UNSUPPORTED_PLATFORM,
            error_msg=(
                f"不支持的广告平台：{exc.platform}，"
                f"可选：{', '.join(sorted(SUPPORTED_AD_PLATFORMS))}"
            ),
            data={
                "exec_kind": "ad_optimize",
                "supported_platforms": sorted(SUPPORTED_AD_PLATFORMS),
            },
            metadata=_metadata(started),
        )
    except IncompleteProfitInputs as exc:
        return WorkflowResult(
            success=False,
            error_code=INVALID_REQUEST,
            error_msg=f"利润测算参数不完整，缺少：{', '.join(exc.missing)}",
            data={"exec_kind": "ad_optimize", "missing_profit_fields": exc.missing},
            metadata=_metadata(started),
        )
    except (ValidationError, TypeError, ValueError) as exc:
        return WorkflowResult(
            success=False,
            error_code=INVALID_REQUEST,
            error_msg=f"广告优化请求参数不合法：{exc}",
            data={"exec_kind": "ad_optimize"},
            metadata=_metadata(started),
        )

    has_signal = any(
        value > 0 for value in (request.spend, request.clicks, request.conversions, request.revenue)
    )
    if not has_signal and not request.campaign_id and not request.sku:
        return WorkflowResult(
            success=False,
            error_code=INVALID_REQUEST,
            error_msg="缺少投放数据：请提供 spend/clicks/conversions/revenue，或 sku / campaign_id",
            data={"exec_kind": "ad_optimize", "platform": request.platform},
            metadata=_metadata(started),
        )

    memory_errors: list[str] = []
    history_hits: list = []
    memory = _mem()
    if request.sku:
        try:
            history_hits = await memory.recall(
                query_text=f"sku:{request.sku} 广告优化 {request.platform}",
                agent_name=AGENT_EXEC,
                top_k=3,
                meta_filter={"sku": request.sku},
                context=ctx,
            )
        except Exception as exc:
            memory_errors.append(f"recall:{type(exc).__name__}")

    ad_result = await exec_skill("ad_optimize", request.skill_params())
    if not ad_result.success:
        return WorkflowResult(
            success=False,
            error_code=SKILL_FAILED,
            error_msg=ad_result.error_msg or "ad_optimize 失败",
            data={
                "exec_kind": "ad_optimize",
                "sku": request.sku or "",
                "platform": request.platform,
                "ad_optimize": ad_result.data or {},
                "profit": {},
            },
            metadata=_metadata(
                started,
                skill_error_code=ad_result.error_code,
                memory_errors=memory_errors,
            ),
        )

    profit_data: dict = {}
    skill_error_codes: dict[str, str] = {}
    errors: list[str] = []
    write_data: dict = {"skipped": True}
    if requested_pause and request.campaign_id:
        write_result = await exec_skill(
            "business_api_write",
            {
                "operation": "pause_campaign",
                "resource_id": request.campaign_id,
                "fields": {"status": "paused"},
            },
        )
        write_data = {
            "skipped": False,
            "success": write_result.success,
            "error_code": str(write_result.error_code or ""),
            "error_msg": write_result.error_msg,
            "data": write_result.data or {},
        }
        if not write_result.success:
            approval_required = write_result.error_code == ErrorCode.APPROVAL_REQUIRED
            return WorkflowResult(
                success=False,
                error_code=write_result.error_code or ErrorCode.SKILL_FAILED,
                error_msg="Human approval required"
                if approval_required
                else write_result.error_msg,
                data={
                    "exec_kind": "advertising",
                    "campaign_id": request.campaign_id,
                    "campaign": fixture_campaign,
                    "ad_optimize": ad_result.data or {},
                    "write": write_data,
                    "approval_required": approval_required,
                    "approval_id": str((write_result.data or {}).get("approval_id") or ""),
                },
                metadata=_metadata(started, skill_error_code=write_result.error_code),
            )
    if request.profit is not None:
        profit_result = await exec_skill("profit_calc", request.profit.model_dump())
        if profit_result.success:
            profit_data = profit_result.data or {}
        else:
            errors.append(f"profit_calc: {profit_result.error_msg or 'failed'}")
            skill_error_codes["profit_calc"] = profit_result.error_code or SKILL_FAILED

    plan = (ad_result.data or {}).get("plan") or {}
    action = str(plan.get("action") or "")
    if request.sku and action and action != "hold":
        try:
            memory_id = await memory.safe_save_memory(
                agent_name=AGENT_EXEC,
                content=(
                    f"广告优化 sku:{request.sku} platform:{request.platform} action:{action} "
                    f"bid:{plan.get('bid_adjust_pct')}% budget:{plan.get('budget_adjust_pct')}%"
                ),
                meta={
                    "sku": request.sku,
                    "platform": request.platform,
                    "action": action,
                    "bid_adjust_pct": plan.get("bid_adjust_pct"),
                    "budget_adjust_pct": plan.get("budget_adjust_pct"),
                    "target_roas": request.target_roas,
                    "metrics_snapshot": plan.get("metrics_snapshot") or {},
                    "success": True,
                    "confidence": 0.8,
                    "deprecated": False,
                },
                context=ctx,
            )
            if memory_id is None:
                memory_errors.append("save:unavailable")
        except Exception as exc:
            memory_errors.append(f"save:{type(exc).__name__}")

    partial = bool(errors or memory_errors)
    return WorkflowResult(
        success=True,
        partial_success=partial,
        error_code=PARTIAL_SUCCESS if partial else "",
        error_msg="; ".join(errors + memory_errors),
        data={
            "exec_kind": "ad_optimize",
            "sku": request.sku or "",
            "platform": request.platform,
            "campaign_id": request.campaign_id or "",
            "ad_optimize": ad_result.data or {},
            "profit": profit_data,
            "history_hits": len(history_hits),
            "history_preview": [
                {"id": hit.get("id"), "content": hit.get("content"), "meta": hit.get("meta")}
                for hit in history_hits[:3]
            ],
            "campaign": fixture_campaign,
            "write": write_data,
            "approval_required": False,
        },
        metadata=_metadata(
            started,
            skill_error_codes=skill_error_codes,
            memory_errors=memory_errors,
        ),
    )


async def handle_ad(task: dict | TaskContext) -> tuple[bool, str, dict]:
    return (await run_ad_workflow(task)).as_legacy_tuple()
