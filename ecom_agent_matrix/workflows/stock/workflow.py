"""Stock analysis workflow."""

from __future__ import annotations

import time

from pydantic import ValidationError
from ...platform.observability.metrics import observed_workflow

from ...config.settings import settings
from ...core.skill.skill_registry import exec_skill
from ...core.tasking import TaskContext, WorkflowResult, ensure_task_context
from ...core.tasking.result import INVALID_REQUEST, MISSING_SKU, SKILL_FAILED
from ...modules.parsers.stock import parse_stock_request
from ...modules.utils.llm_explain import llm_explain


def _metadata(started: float, **extra) -> dict:
    return {
        "workflow": "stock",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        **extra,
    }


@observed_workflow("stock")
async def run_stock_workflow(task: dict | TaskContext) -> WorkflowResult:
    started = time.perf_counter()
    ctx = ensure_task_context(task)
    try:
        request = parse_stock_request(ctx)
    except (ValidationError, TypeError, ValueError) as exc:
        return WorkflowResult(
            success=False,
            error_code=INVALID_REQUEST,
            error_msg=f"库存预测请求参数不合法：{exc}",
            data={"query_kind": "stock"},
            metadata=_metadata(started),
        )

    if not request.sku:
        overview = await exec_skill(
            "inventory_risk_list",
            {"threshold": int(ctx.params.get("stock_threshold", 25)), "limit": 20},
        )
        if overview.success:
            items = (overview.data or {}).get("items") or []
            summary = (
                f"发现 {len(items)} 个低库存商品，其中 "
                f"{sum(1 for item in items if item.get('risk_level') == 'high')} 个为高风险。"
            )
            return WorkflowResult(
                success=True,
                data={
                    "query_kind": "stock",
                    "summary": summary,
                    "items": items,
                    "count": len(items),
                    "predict_days": request.predict_days,
                },
                metadata=_metadata(started),
            )
        return WorkflowResult(
            success=False,
            error_code=MISSING_SKU,
            error_msg=overview.error_msg or "无法读取库存概览",
            data={"query_kind": "stock", "sku": "", "items": []},
            metadata=_metadata(started),
        )

    skill_result = await exec_skill(
        "stock_predict",
        {"sku": request.sku, "predict_days": request.predict_days},
    )
    if not skill_result.success:
        return WorkflowResult(
            success=False,
            error_code=SKILL_FAILED,
            error_msg=skill_result.error_msg or "stock_predict 执行失败",
            data={
                "query_kind": "stock",
                "sku": request.sku,
                "predict_days": request.predict_days,
                "history_hits": 0,
                "history_preview": [],
                "stock_predict_result": skill_result.data or {},
            },
            metadata=_metadata(started, skill_error_code=skill_result.error_code),
        )

    prediction = skill_result.data or {}
    candidates = (ctx.params.get("_goods") or {}).get("candidates") or []
    product = next(
        (item for item in candidates if str(item.get("sku") or "") == request.sku),
        candidates[0] if candidates else {},
    )
    if not product and prediction.get("current_stock") is not None:
        product = {
            "sku": request.sku,
            "title_zh": prediction.get("product_title") or request.sku,
            "stock_num": prediction.get("current_stock"),
            "reorder_level": prediction.get("reorder_level"),
        }
    suggestion = prediction.get("suggest_stock_amount")
    daily = prediction.get("daily_avg_sales")
    stock_prefix = (
        f"当前库存 {product.get('stock_num')} 件；" if product.get("stock_num") is not None else ""
    )
    fallback = (
        f"SKU {request.sku} {stock_prefix}近30日日均销量约 {daily}，"
        f"{request.predict_days} 天建议备货量 {suggestion}（含安全库存系数）。"
        "请结合在途库存与促销计划调整。"
    )
    advice, advice_source, advice_error = await llm_explain(
        system_prompt=(
            "你是跨境电商补货顾问。根据预测数字写简短中文说明："
            "风险点与补货建议。不要改写数字，不要编造未提供的供应商交期。"
        ),
        user_prompt=(
            f"sku={request.sku}\npredict_days={request.predict_days}\nprediction={prediction}"
        ),
        fallback=fallback,
        max_tokens=int(getattr(settings, "AGENT_LLM_EXPLAIN_MAX_TOKENS", 450) or 450),
    )
    return WorkflowResult(
        success=True,
        data={
            "query_kind": "stock",
            "sku": request.sku,
            "predict_days": request.predict_days,
            "history_hits": 0,
            "history_preview": [],
            "stock_predict_result": prediction,
            "product": product,
            "advice": advice,
            "advice_source": advice_source,
            "advice_error": advice_error or None,
        },
        metadata=_metadata(started),
    )


async def handle_stock(task: dict | TaskContext) -> tuple[bool, str, dict]:
    return (await run_stock_workflow(task)).as_legacy_tuple()
