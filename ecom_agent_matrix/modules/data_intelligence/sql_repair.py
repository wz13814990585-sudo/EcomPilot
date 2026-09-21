"""Bounded SQL repair for safe technical execution failures only."""

from __future__ import annotations

import json

from ...core.llm import is_llm_configured
from ...core.llm.structured import llm_chat_structured
from ...platform.observability.context import trace_context
from .schemas import GeneratedSQL, SQLGenerationRequest


class SQLRepairer:
    async def repair(
        self,
        generated: GeneratedSQL,
        request: SQLGenerationRequest,
        *,
        error_category: str,
    ) -> GeneratedSQL:
        if not is_llm_configured():
            raise RuntimeError("SQL repair LLM is unavailable")
        schema = {table.name: [column.name for column in table.columns] for table in request.tables}
        with trace_context(workflow="sql_repair"):
            response = await llm_chat_structured(
                response_model=GeneratedSQL,
                repair_attempts=1,
                system_prompt=(
                    "Repair one PostgreSQL SELECT after a technical execution error. Use only the "
                    "approved schema. Do not weaken permissions or emit DDL/DML. Return JSON only."
                ),
                user_prompt=(
                    f"Question: {request.question}\nPrior SQL: {generated.sql}\n"
                    f"Safe error category: {error_category}\nApproved schema: "
                    f"{json.dumps(schema, ensure_ascii=False)}"
                ),
                temperature=0,
                max_tokens=600,
            )
        return response.value


__all__ = ["SQLRepairer"]
