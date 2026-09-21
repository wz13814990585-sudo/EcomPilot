"""Query-owned enterprise data-analysis workflow."""

from __future__ import annotations

import time

from ...core.errors import ErrorCode
from ...core.security import SecurityContext
from ...core.tasking import TaskContext, WorkflowResult, ensure_task_context
from ...modules.data_intelligence import (
    DataAnalysisRequest,
    DataIntelligenceService,
    data_intelligence_service,
)
from ...platform.observability.metrics import observed_workflow


@observed_workflow("data_analysis")
async def run_data_analysis_workflow(
    task: dict | TaskContext,
    *,
    security: SecurityContext | None,
    service: DataIntelligenceService | None = None,
) -> WorkflowResult:
    started = time.perf_counter()
    ctx = ensure_task_context(task)
    if security is None or not security.authenticated:
        return WorkflowResult(
            success=False,
            error_code=ErrorCode.AUTHENTICATION_REQUIRED.value,
            error_msg="Trusted SecurityContext is required for analytical SQL",
            data={"query_kind": "data_analysis"},
        )
    raw_limit = ctx.params.get("max_rows", ctx.params.get("limit", 200))
    try:
        request = DataAnalysisRequest(
            question=ctx.query,
            task_type="data_analysis",
            max_rows=int(raw_limit),
            dialect=str(ctx.params.get("dialect") or "postgres"),
            sql=ctx.params.get("sql") or ctx.params.get("custom_sql"),
            params=ctx.params.get("sql_params") or [],
        )
    except (TypeError, ValueError) as exc:
        return WorkflowResult(
            success=False,
            error_code=ErrorCode.INVALID_REQUEST.value,
            error_msg=f"Invalid data-analysis request: {exc}",
            data={"query_kind": "data_analysis"},
        )
    active_service = service or data_intelligence_service
    result = await active_service.analyze(request, security=security)
    if not result.success:
        return WorkflowResult(
            success=False,
            error_code=result.error_code or ErrorCode.SQL_EXECUTION_ERROR.value,
            error_msg=result.error_msg,
            data={
                "query_kind": "data_analysis",
                "catalog_source": result.catalog_source,
                "schema_version": result.schema_version,
                "schema_link": result.schema_link.model_dump(mode="json")
                if result.schema_link
                else None,
            },
            metadata={"latency_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
    execution = result.execution
    assert execution is not None
    summary = (
        "查询成功但未返回数据。"
        if not execution.rows
        else f"查询完成，返回 {execution.row_count} 行可追溯结果。"
    )
    return WorkflowResult(
        success=True,
        data={
            "query_kind": "data_analysis",
            "summary": summary,
            "schema_link": result.schema_link.model_dump(mode="json"),
            "generated_sql": result.generated_sql.model_dump(mode="json"),
            "validated_sql": result.validated_sql.model_dump(mode="json"),
            "result": execution.model_dump(mode="json"),
            "evidence": result.evidence,
            "repair_attempts": result.repair_attempts,
            "catalog_source": result.catalog_source,
            "schema_version": result.schema_version,
        },
        metadata={"latency_ms": round((time.perf_counter() - started) * 1000, 2)},
    )
