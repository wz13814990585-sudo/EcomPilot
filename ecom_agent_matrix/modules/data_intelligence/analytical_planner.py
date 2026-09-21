"""Bounded deterministic decomposition for supported diagnostic questions."""

from __future__ import annotations

import re

from ...config.settings import settings
from .schemas import (
    AnalyticalQueryPlan,
    AnalyticalQueryStep,
    AnalyticalStepType,
    SchemaCatalog,
)


class AnalyticalQueryPlanner:
    def plan_if_supported(
        self, question: str, catalog: SchemaCatalog
    ) -> AnalyticalQueryPlan | None:
        query = question.lower()
        diagnostic = bool(
            re.search(r"为什么|原因|导致|why|explain|declin|increase|上涨|下降", query)
        )
        metric = (
            "refund_rate"
            if re.search(r"退款率|退款|refund\s*rate|refund", query)
            else "revenue"
            if re.search(r"销售额|revenue|gmv", query)
            else ""
        )
        if not diagnostic or not metric or catalog.table("ecom_order") is None:
            return None

        dated_period = re.search(r"(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月", query)
        month_period = re.search(r"(?<!\d)(1[0-2]|0?[1-9])\s*月", query)
        period_hint = ""
        if dated_period:
            period_hint = (
                f" period={int(dated_period.group(1)):04d}-{int(dated_period.group(2)):02d}"
            )
        elif month_period:
            period_hint = f" period_month={int(month_period.group(1))}"

        order = catalog.table("ecom_order")
        goods = catalog.table("ecom_goods")
        metric_columns = (
            ("refund_flag", "create_time")
            if metric == "refund_rate"
            else ("total_amount", "create_time")
        )
        if any(order.column(name) is None for name in metric_columns):
            return None
        steps = [
            AnalyticalQueryStep(
                id="metric_trend",
                step_type=AnalyticalStepType.METRIC_TREND,
                question=f"ANALYSIS_STEP:METRIC_TREND metric={metric}",
                required_tables=("ecom_order",),
                required_columns=metric_columns,
            )
        ]
        relation_available = any(
            {relation.from_table, relation.to_table} == {"ecom_order", "ecom_goods"}
            for relation in catalog.relations
        )
        if goods and goods.column("category") and relation_available:
            steps.append(
                AnalyticalQueryStep(
                    id="category_breakdown",
                    step_type=AnalyticalStepType.CATEGORY_BREAKDOWN,
                    question=(
                        f"ANALYSIS_STEP:CATEGORY_BREAKDOWN metric={metric} category product orders"
                        f"{period_hint}"
                    ),
                    required_tables=("ecom_order", "ecom_goods"),
                    required_columns=(*metric_columns, "sku", "category"),
                )
            )
        if order.column("sku"):
            steps.append(
                AnalyticalQueryStep(
                    id="sku_breakdown",
                    step_type=AnalyticalStepType.SKU_BREAKDOWN,
                    question=(
                        f"ANALYSIS_STEP:SKU_BREAKDOWN metric={metric} sku orders{period_hint}"
                    ),
                    required_tables=("ecom_order",),
                    required_columns=(*metric_columns, "sku"),
                )
            )
        bounded = tuple(steps[: max(1, int(settings.ANALYSIS_MAX_SUBQUERIES))])
        return AnalyticalQueryPlan(
            question=question,
            metric=metric,
            steps=bounded,
            warnings=("REGION_SKIPPED_DIMENSION_UNAVAILABLE",)
            if catalog.table("region") is None
            else (),
        )


__all__ = ["AnalyticalQueryPlanner"]
