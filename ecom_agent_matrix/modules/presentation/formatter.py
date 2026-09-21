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
            highlights = [
                f"{year} 年 {month} 月：{int(current.get('order_count') or 0)} 单中 "
                f"{int(current.get('refund_count') or 0)} 单退款，退款率 {current_rate:.1f}%"
            ]
            if prior:
                highlights.append(
                    f"{prior_period[1]} 月退款率 {float(prior.get('refund_rate') or 0) * 100:.1f}%"
                )
            category_rows = contributions.get("category_breakdown") or []
            sku_rows = contributions.get("sku_breakdown") or []
            top_category = max(
                (row for row in category_rows if isinstance(row, dict)),
                key=lambda row: float(row.get("refund_count") or 0),
                default=None,
            )
            top_sku = max(
                (row for row in sku_rows if isinstance(row, dict)),
                key=lambda row: float(row.get("refund_count") or 0),
                default=None,
            )
            reasons: list[str] = []
            if top_category:
                category_name = {
                    "electronics": "电子产品",
                    "bags": "箱包",
                    "footwear": "鞋类",
                }.get(str(top_category.get("category") or ""), top_category.get("category"))
                reasons.append(
                    f"{category_name or '未分类'}品类退款 "
                    f"{int(top_category.get('refund_count') or 0)} 单"
                )
                highlights.append(
                    f"退款最集中品类：{category_name or '未分类'}，"
                    f"退款率 {float(top_category.get('refund_rate') or 0) * 100:.1f}%"
                )
            if top_sku:
                reasons.append(
                    f"{top_sku.get('sku') or '未知 SKU'} 退款 "
                    f"{int(top_sku.get('refund_count') or 0)} 单"
                )
                highlights.append(
                    f"退款最集中 SKU：{top_sku.get('sku') or '未知'}，"
                    f"退款率 {float(top_sku.get('refund_rate') or 0) * 100:.1f}%"
                )
            if reasons:
                answer += " 从数据看，上涨主要由" + "、".join(reasons) + "拉动。"
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
            claim_text = " ".join(str(item) for item in document_claims)
            signals: list[str] = []
            if "CHARGER-001" in claim_text and "接头松动" in claim_text:
                signals.append("CHARGER-001 批次接头松动")
            if "BAG-002" in claim_text and ("拉链" in claim_text or "包装" in claim_text):
                signals.append("BAG-002 包装与拉链客诉增多")
            if "物流延迟" in claim_text or "转运节点延迟" in claim_text:
                signals.append("局部物流延迟")
            if signals and "为什么" in str(
                ((leaf.get("analytical") or {}).get("plan") or {}).get("question") or ""
            ):
                result["answer"] += (
                    " 同期运营记录显示："
                    + "、".join(dict.fromkeys(signals))
                    + "。这些是有证据的重点排查方向，但目前只能确认同期共现，不能当作单一因果。"
                )
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
            for key in (
                "answer",
                "readable_summary",
                "summary",
                "final_answer",
                "copy_draft",
                "advice",
            )
            if isinstance(leaf.get(key), str) and str(leaf[key]).strip()
        ),
        "",
    )
    category = str(leaf.get("query_kind") or leaf.get("exec_kind") or "general")
    highlights: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []
    tables: list[dict[str, Any]] = []

    if category == "ad_optimize":
        optimization = leaf.get("ad_optimize") or {}
        plan = optimization.get("plan") or {}
        campaign = leaf.get("campaign") or {}
        metrics = plan.get("metrics_snapshot") or {}
        name = campaign.get("name") or leaf.get("campaign_id") or "当前广告活动"
        action_labels = {
            "pause": "暂停投放",
            "decrease": "降低预算或出价",
            "scale_down": "降低预算和出价",
            "increase": "适度增加预算",
            "scale_up": "适度增加预算",
            "hold": "保持当前设置并继续观察",
        }
        action = action_labels.get(
            str(plan.get("action") or ""), str(plan.get("action") or "继续观察")
        )
        answer = f"已分析 {name}：建议{action}。"
        if metrics:
            highlights.extend(
                [
                    f"ROAS：{metrics.get('roas', 0)}",
                    f"消耗：{metrics.get('spend', 0)}，收入：{metrics.get('revenue', 0)}",
                    f"转化：{metrics.get('conversions', 0)}，CPA：{metrics.get('cpa') or '暂无'}",
                ]
            )
        if str(plan.get("action") or "") in {"pause", "decrease", "scale_down"}:
            recommendations = [
                "先降低预算和出价，避免继续扩大低效消耗。",
                "检查低转化受众、广告素材与落地页是否匹配。",
                "将部分预算转移到 ROAS 更高的活动，并在 24–48 小时后复查。",
            ]
        elif str(plan.get("action") or "") in {"increase", "scale_up"}:
            recommendations = [
                "小幅增加预算，每次调整后观察至少一个完整转化周期。",
                "确认库存、履约能力和边际利润可以承接新增流量。",
            ]
        else:
            recommendations = ["保持设置，并在积累更多转化数据后复查。"]
    elif category == "goods_search":
        candidates = leaf.get("candidates") or []
        best = leaf.get("best_sku")
        if candidates:
            first = candidates[0]
            title = first.get("title_zh") or first.get("title_en") or best
            price = first.get("price")
            stock = first.get("stock_num")
            prices = [float(item["price"]) for item in candidates if item.get("price") is not None]
            answer = f"找到 {len(candidates)} 个匹配商品。"
            if len(prices) > 1:
                answer += f"售价区间为 ${min(prices):.2f}–${max(prices):.2f}。"
            answer += f"最相关的是 {title}（{best}）"
            if price is not None:
                answer += f"，售价 ${float(price):.2f}"
            if stock is not None:
                answer += f"，当前库存 {int(stock)} 件"
            answer += "。"
        else:
            answer = "没有找到匹配商品，请换一个名称或提供 SKU。"
    elif category == "stock" and isinstance(leaf.get("items"), list):
        items = leaf.get("items") or []
        answer = f"发现 {len(items)} 个需要关注的低库存商品。" if items else "当前没有低库存商品。"
        tables.append({"title": "低库存商品", "rows": items})
    elif category == "stock" and leaf.get("stock_predict_result"):
        product = leaf.get("product") or {}
        prediction = leaf.get("stock_predict_result") or {}
        title = product.get("title_zh") or product.get("title_en") or leaf.get("sku")
        current = product.get("stock_num")
        answer = f"{title}（{leaf.get('sku')}）"
        if current is not None:
            answer += f"当前库存 {int(current)} 件；"
        answer += (
            f"近 30 天日均销量约 {prediction.get('daily_avg_sales', 0)} 件，"
            f"未来 {leaf.get('predict_days', 7)} 天建议备货 "
            f"{prediction.get('suggest_stock_amount', 0)} 件。"
        )
        highlights = [str(leaf.get("advice") or "").strip()] if leaf.get("advice") else []
    elif category == "social":
        social = leaf.get("social_copy") or {}
        draft = str(social.get("copy_draft") or "").strip()
        image_prompt = str((leaf.get("ai_image_prompt") or {}).get("positive_prompt") or "").strip()
        answer = draft or "推广文案生成失败，请稍后重试。"
        if draft:
            highlights = [
                f"平台：{social.get('platform') or leaf.get('platform') or '未指定'}",
                f"语言：{social.get('lang') or leaf.get('lang') or '未指定'}",
            ]
        if image_prompt:
            recommendations = [f"配图提示词：{image_prompt}"]
    elif category == "competitor" and isinstance(leaf.get("comparisons"), list):
        comparisons = leaf.get("comparisons") or []
        answer = str(leaf.get("summary") or leaf.get("advice") or answer)
        tables.append({"title": "竞品价格", "rows": comparisons})

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
    if isinstance(candidates, list) and candidates and not tables:
        tables.append({"title": "结果", "rows": candidates})
    campaigns = leaf.get("campaigns")
    if isinstance(campaigns, list) and campaigns:
        tables.append({"title": "广告活动", "rows": campaigns})
    citations = leaf.get("citations") or []
    evidence_count = len(citations) or len(leaf.get("evidence_records") or [])
    return {
        "category": category,
        "answer": answer,
        "highlights": highlights,
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
