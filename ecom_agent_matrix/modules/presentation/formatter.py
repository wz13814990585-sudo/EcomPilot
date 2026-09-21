"""Deterministic result presentation; raw workflow data remains untouched."""

from __future__ import annotations

from typing import Any
import re


def _unwrap(data: dict[str, Any]) -> dict[str, Any]:
    """Pick the most useful successful leaf from a Master aggregation."""
    sub = data.get("sub_results")
    if isinstance(sub, list):
        leaves = [item.get("data", item) for item in sub if isinstance(item, dict)]
        analytical = next(
            (item for item in leaves if isinstance(item, dict) and item.get("analytical")), None
        )
        if analytical:
            return analytical
        answered = next(
            (
                item
                for item in leaves
                if isinstance(item, dict)
                and any(item.get(key) for key in ("answer", "summary", "query_kind", "exec_kind"))
            ),
            None,
        )
        if answered:
            return answered
    return data


def _analysis(leaf: dict[str, Any]) -> dict[str, Any]:
    analytical = leaf.get("analytical") or {}
    trend = analytical.get("metric_trend") or []
    contributions = analytical.get("segment_contributions") or {}
    rows = (leaf.get("result") or {}).get("rows") or []
    highlights: list[str] = []
    for row in trend[:4]:
        if isinstance(row, dict):
            highlights.append(" / ".join(f"{k}: {v}" for k, v in row.items()))
    for segment, values in contributions.items():
        if values:
            first = values[0]
            highlights.append(f"{segment}: " + " / ".join(f"{k}: {v}" for k, v in first.items()))
    if not highlights and rows:
        highlights = [" / ".join(f"{k}: {v}" for k, v in row.items()) for row in rows[:4]]
    status = analytical.get("status") or "FULL_SUCCESS"
    answer = "分析已完成。" if highlights else "查询已完成，但未找到匹配数据。"
    question = str(((analytical.get("plan") or {}).get("question") or ""))
    target = re.search(r"(20\d{2})年\s*(1[0-2]|0?[1-9])月", question)
    if target and trend and "退款" in question:
        year, month = int(target.group(1)), int(target.group(2))

        def period(row: dict[str, Any]) -> tuple[int, int]:
            match = re.match(r"(20\d{2})-(\d{2})", str(row.get("month") or ""))
            return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

        current = next((row for row in trend if period(row) == (year, month)), None)
        prior_period = (year - 1, 12) if month == 1 else (year, month - 1)
        prior = next((row for row in trend if period(row) == prior_period), None)
        if current:
            current_rate = float(current.get("refund_rate") or 0) * 100
            if prior:
                prior_rate = float(prior.get("refund_rate") or 0) * 100
                answer = (
                    f"{month} 月退款率从 {prior_period[1]} 月的 {prior_rate:.1f}% "
                    f"上升到 {current_rate:.1f}%。"
                )
            else:
                answer = f"{year} 年 {month} 月退款率为 {current_rate:.1f}%。"
    if highlights:
        if not target or "退款" not in question:
            answer = f"分析已完成（{status}）：{highlights[0]}"
    warnings = list(analytical.get("warnings") or [])
    if contributions:
        warnings.append("分项结果表示同期变化，不单独构成因果证明。")
    return {
        "category": "data_analysis",
        "answer": answer,
        "highlights": highlights,
        "recommendations": ["核查异常 SKU 的质量、物流与客诉记录。"] if contributions else [],
        "warnings": warnings,
        "evidence_summary": f"{len(leaf.get('evidence_records') or [])} 条 SQL 证据记录",
        "tables": [{"title": "查询结果", "rows": rows}] if rows else [],
    }


def build_presentation(
    *, success: bool, data: dict[str, Any] | None, error_msg: str = ""
) -> dict[str, Any]:
    payload = data if isinstance(data, dict) else {}
    leaf = _unwrap(payload)
    if leaf.get("analytical") is not None or leaf.get("query_kind") == "data_analysis":
        result = _analysis(leaf)
        composite = payload.get("analysis")
        if isinstance(composite, dict):
            document_claims = [
                claim.get("text")
                for claim in composite.get("claims") or []
                if isinstance(claim, dict)
                and claim.get("citation_ids")
                and claim.get("claim_type") == "fact"
            ]
            result["category"] = "data_analysis_composite"
            result["highlights"].extend(document_claims[:3])
            result["warnings"].extend(composite.get("uncertainties") or [])
            result["recommendations"] = (
                composite.get("recommended_next_steps") or result["recommendations"]
            )
            result["evidence_summary"] = (
                f"{len(payload.get('evidence') or [])} 组 SQL/文档证据，"
                f"{len(composite.get('citations') or [])} 个文档引用"
            )
        return result

    answer = next(
        (
            str(leaf[key]).strip()
            for key in ("answer", "readable_summary", "summary", "final_answer", "copy_draft")
            if isinstance(leaf.get(key), str) and str(leaf[key]).strip()
        ),
        "",
    )
    category = str(leaf.get("query_kind") or leaf.get("exec_kind") or "general")
    warnings: list[str] = []
    recommendations: list[str] = []
    tables: list[dict[str, Any]] = []

    if leaf.get("approval_required"):
        answer = "该操作需要人工审批。请确认目标与参数后批准，再重试任务。"
        warnings.append("高风险写操作尚未执行。")
    if not answer:
        if not success:
            answer = error_msg or "任务未完成。"
        elif leaf.get("fields"):
            fields = leaf["fields"]
            answer = "查询结果：" + "，".join(f"{k}={v}" for k, v in fields.items())
        else:
            answer = "任务已完成。"

    candidates = leaf.get("candidates") or leaf.get("items")
    if isinstance(candidates, list) and candidates:
        tables.append({"title": "结果", "rows": candidates})
    campaigns = leaf.get("campaigns")
    if isinstance(campaigns, list) and campaigns:
        tables.append({"title": "广告活动", "rows": campaigns})
    citations = leaf.get("citations") or []
    evidence_count = len(citations) or len(leaf.get("evidence_records") or [])
    return {
        "category": category,
        "answer": answer,
        "highlights": [],
        "recommendations": recommendations,
        "warnings": warnings,
        "evidence_summary": f"{evidence_count} 条来源/证据" if evidence_count else "",
        "tables": tables,
        "approval": {
            "required": bool(leaf.get("approval_required")),
            "approval_id": str(leaf.get("approval_id") or ""),
            "target": str(leaf.get("order_no") or leaf.get("campaign_id") or ""),
        },
    }
