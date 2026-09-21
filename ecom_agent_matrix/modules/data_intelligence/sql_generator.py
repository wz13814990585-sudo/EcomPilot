"""Structured Text-to-SQL generation over a bounded linked schema."""

from __future__ import annotations

import json
import re

from ...core.llm import is_llm_configured
from ...core.llm.structured import llm_chat_structured
from ...platform.observability.context import trace_context
from .schemas import GeneratedSQL, SQLGenerationRequest


class SQLGenerationError(RuntimeError):
    pass


def _deterministic_sql(question: str) -> str | None:
    """High-confidence fast path for common metrics; not a general keyword router."""
    query = question.lower()
    current_month = "DATE_TRUNC('month', create_time) = DATE_TRUNC('month', CURRENT_DATE)"
    if re.search(r"(销售额|revenue|gmv)", query) and re.search(r"(本月|this month)", query):
        return (
            "SELECT COALESCE(SUM(total_amount), 0) AS revenue, COUNT(*) AS order_count "
            f"FROM ecom_order WHERE {current_month}"
        )
    if re.search(r"(销量最高|top\s*\d*.*product|销量排名)", query):
        match = re.search(r"(?:top\s*|最高的?\s*)(\d+)", query)
        limit = min(max(int(match.group(1)) if match else 5, 1), 50)
        return (
            "SELECT o.sku, g.title_zh, SUM(o.buy_num) AS units_sold "
            "FROM ecom_order AS o JOIN ecom_goods AS g ON g.sku = o.sku "
            "GROUP BY o.sku, g.title_zh ORDER BY units_sold DESC "
            f"LIMIT {limit}"
        )
    if re.search(r"(退款率|refund rate)", query):
        return (
            "SELECT DATE_TRUNC('month', create_time) AS month, COUNT(*) AS order_count, "
            "SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END) AS refund_count, "
            "ROUND(SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END)::numeric / "
            "NULLIF(COUNT(*), 0), 4) AS refund_rate FROM ecom_order "
            "GROUP BY DATE_TRUNC('month', create_time) ORDER BY month DESC LIMIT 12"
        )
    if re.search(r"(订单).*(数量|总数|有多少)|count.*orders?", query):
        return "SELECT COUNT(*) AS order_count FROM ecom_order"
    return None


class SQLGenerator:
    async def generate(self, request: SQLGenerationRequest) -> GeneratedSQL:
        deterministic = _deterministic_sql(request.question)
        if deterministic:
            return GeneratedSQL(sql=deterministic)
        if not is_llm_configured():
            raise SQLGenerationError("No deterministic template matched and LLM is unavailable")

        schema_context = {
            "tables": [
                {
                    "name": table.name,
                    "description": table.description or table.name.replace("_", " "),
                    "columns": [
                        {
                            "name": column.name,
                            "type": column.data_type,
                            "description": column.description or column.name.replace("_", " "),
                        }
                        for column in table.columns
                    ],
                }
                for table in request.tables
            ],
            "relations": [relation.model_dump() for relation in request.relations],
            "metrics": list(request.metric_definitions),
        }
        with trace_context(workflow="sql_generation"):
            response = await llm_chat_structured(
                response_model=GeneratedSQL,
                repair_attempts=1,
                system_prompt=(
                    "Generate one PostgreSQL read-only SELECT query. Use only the supplied tables, "
                    "columns and relations. Never emit DDL/DML, comments, multiple statements or "
                    "security predicates. Return JSON matching the requested schema."
                ),
                user_prompt=(
                    f"Question: {request.question}\nMaximum rows: {request.max_rows}\n"
                    f"Approved schema: {json.dumps(schema_context, ensure_ascii=False)}"
                ),
                temperature=0,
                max_tokens=700,
            )
        return response.value


__all__ = ["SQLGenerationError", "SQLGenerator"]
