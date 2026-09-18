"""Deprecated keyword routing for callers that omit an explicit task type."""

from __future__ import annotations

import warnings

from ..core.tasking import TaskContext, ensure_task_context
from ..modules.parsers.goods import is_catalog_query


def infer_query_kind(task: dict | TaskContext) -> str:
    warnings.warn(
        "infer_query_kind is deprecated; pass task_type",
        DeprecationWarning,
        stacklevel=2,
    )
    ctx = ensure_task_context(task)
    payload = ctx.to_payload()
    task_type = ctx.task_type or ctx.query_kind or ""
    aliases = {
        "goods_catalog": "goods",
        "goods_search": "goods",
        "stock_analysis": "stock",
        "stock": "stock",
        "competitor_watch": "competitor",
        "competitor": "competitor",
        "data_check": "data_check",
        "order_query": "data_check",
        "ad_query": "data_check",
    }
    if task_type in aliases:
        return aliases[task_type]
    text = " ".join(value for value in (ctx.query, ctx.product_name or "") if value)
    lower = text.lower()
    if is_catalog_query(text) or payload.get("mode") == "catalog":
        return "goods"
    if (
        any(k in text for k in ("竞品", "比价", "竞价对比", "价格对比", "跟价"))
        or "competitor" in lower
    ):
        return "competitor"
    if any(k in text for k in ("库存", "备货", "补货", "缺货")) or any(
        k in lower for k in ("stock", "inventory", "replenish")
    ):
        return "stock"
    if any(
        k in text
        for k in (
            "数据校验",
            "数据检查",
            "完整性",
            "脏数据",
            "主数据",
            "查库",
            "跑sql",
            "订单",
            "校验",
        )
    ) or any(k in lower for k in ("integrity", "sql", "order")):
        return "data_check"
    return "goods"


def infer_exec_kind(task: dict | TaskContext) -> str:
    warnings.warn(
        "infer_exec_kind is deprecated; pass task_type",
        DeprecationWarning,
        stacklevel=2,
    )
    ctx = ensure_task_context(task)
    payload = ctx.to_payload()
    task_type = ctx.task_type or ctx.exec_kind or ""
    aliases = {
        "ad_optimize": "ad",
        "ad": "ad",
        "ops_report": "report",
        "report": "report",
        "risk_control": "risk",
        "risk": "risk",
        "social_marketing": "social",
        "social": "social",
        "customer_service": "crm",
        "crm": "crm",
    }
    if task_type in aliases:
        return aliases[task_type]
    text = ctx.query
    lower = text.lower()
    if any(k in text for k in ("风控", "触发风险")) or "risk" in lower:
        return "risk"
    if any(k in text for k in ("报表", "日报", "周报", "运营报告")) or "report" in lower:
        return "report"
    if any(k in text for k in ("广告", "出价", "投放优化", "ppc")) or any(
        k in lower for k in ("ad", "campaign", "bid")
    ):
        return "ad"
    if any(k in text for k in ("社媒", "文案", "tiktok", "instagram")) or "caption" in lower:
        return "social"
    if payload.get("spend") is not None or payload.get("campaign_id"):
        return "ad"
    if payload.get("report_type"):
        return "report"
    if payload.get("run_risk_check") or payload.get("order_no"):
        return "risk"
    return "crm"


__all__ = ["infer_exec_kind", "infer_query_kind"]
