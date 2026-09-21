"""Public enterprise Text-to-SQL analysis facade."""

from __future__ import annotations

import asyncio
import time

from ...config.settings import settings
from ...core.errors import ErrorCode
from ...core.security import SecurityContext, tenant_scope_from_security
from ...platform.observability.metrics import metrics
from ..evidence import SQLEvidence
from .analytical_planner import AnalyticalQueryPlanner
from .catalog import SchemaCatalogProvider, filter_catalog_for_security, schema_catalog_provider
from .schema_linker import HybridSchemaLinker
from .semantic_schema import default_schema_semantic_scorer
from .schemas import (
    AnalyticalAnalysisResult,
    DataAnalysisRequest,
    DataAnalysisResult,
    GeneratedSQL,
    AnalyticalStepResult,
    AnalyticalStepType,
    SQLGenerationRequest,
    SchemaCatalog,
)
from .sql_executor import SQLExecutionFailure, SafeSQLExecutor
from .sql_generator import SQLGenerationError, SQLGenerator
from .sql_repair import SQLRepairer
from .sql_validator import SQLGuardConfig, SQLSafetyValidator, SQLValidationError


class DataIntelligenceService:
    def __init__(
        self,
        *,
        catalog_provider: SchemaCatalogProvider | None = None,
        linker: HybridSchemaLinker | None = None,
        generator: SQLGenerator | None = None,
        validator: SQLSafetyValidator | None = None,
        executor: SafeSQLExecutor | None = None,
        repairer: SQLRepairer | None = None,
        analytical_planner: AnalyticalQueryPlanner | None = None,
    ) -> None:
        self.catalog_provider = catalog_provider or schema_catalog_provider
        self.linker = linker or HybridSchemaLinker(default_schema_semantic_scorer())
        self.generator = generator or SQLGenerator()
        self.validator = validator or SQLSafetyValidator(
            SQLGuardConfig(
                max_join_tables=settings.SQL_MAX_JOIN_TABLES,
                max_selected_columns=settings.SQL_MAX_SELECTED_COLUMNS,
                max_rows=settings.SQL_MAX_ROWS,
            )
        )
        self.executor = executor or SafeSQLExecutor()
        self.repairer = repairer or SQLRepairer()
        self.analytical_planner = analytical_planner or AnalyticalQueryPlanner()

    async def analyze(
        self,
        request: DataAnalysisRequest,
        *,
        security: SecurityContext,
    ) -> DataAnalysisResult:
        if security.authenticated and request.sql is None:
            allowed_catalog = filter_catalog_for_security(self.catalog_provider.get(), security)
            plan = self.analytical_planner.plan_if_supported(request.question, allowed_catalog)
            if plan is not None:
                return await self._analyze_plan(request, security=security, plan=plan)
        return await self._analyze_single(request, security=security)

    async def _analyze_plan(
        self,
        request: DataAnalysisRequest,
        *,
        security: SecurityContext,
        plan,
    ) -> DataAnalysisResult:
        semaphore = asyncio.Semaphore(max(1, int(settings.ANALYSIS_MAX_CONCURRENT)))

        async def run_step(step):
            async with semaphore:
                child = request.model_copy(update={"question": step.question, "sql": None})
                return step, await self._analyze_single(child, security=security)

        pairs = await asyncio.gather(*(run_step(step) for step in plan.steps))
        step_results: list[AnalyticalStepResult] = []
        evidence_records: list[dict] = []
        metric_trend: list[dict] = []
        contributions: dict[str, list[dict]] = {}
        warnings = list(plan.warnings)
        first_success: DataAnalysisResult | None = None
        for step, result in pairs:
            if result.success and result.execution is not None:
                first_success = first_success or result
                rows = result.execution.rows[:50]
                evidence_records.extend(result.evidence_records)
                if step.step_type == AnalyticalStepType.METRIC_TREND:
                    metric_trend = rows
                else:
                    contributions[step.step_type.value] = rows
                step_results.append(
                    AnalyticalStepResult(
                        step_id=step.id,
                        step_type=step.step_type,
                        success=True,
                        rows=rows,
                        evidence_id=str((result.evidence or {}).get("id") or ""),
                        lineage=result.execution.lineage,
                        warnings=result.execution.warnings,
                    )
                )
            else:
                warnings.append(f"{step.id}:{result.error_code or 'FAILED'}")
                step_results.append(
                    AnalyticalStepResult(
                        step_id=step.id,
                        step_type=step.step_type,
                        success=False,
                        error_code=result.error_code,
                        warnings=[result.error_msg] if result.error_msg else [],
                    )
                )
        metrics.observe_analytical_plan(len(plan.steps), sum(item.success for item in step_results))
        analytical = AnalyticalAnalysisResult(
            plan=plan,
            steps=step_results,
            metric_trend=metric_trend,
            segment_contributions=contributions,
            anomalies=[],
            evidence_ids=[record["id"] for record in evidence_records if record.get("id")],
            warnings=warnings,
        )
        all_success = bool(step_results) and all(item.success for item in step_results)
        return DataAnalysisResult(
            success=all_success,
            question=request.question,
            catalog_source=self.catalog_provider.get().source,
            schema_link=first_success.schema_link if first_success else None,
            generated_sql=first_success.generated_sql if first_success else None,
            validated_sql=first_success.validated_sql if first_success else None,
            execution=first_success.execution if first_success else None,
            evidence=evidence_records[0] if evidence_records else None,
            evidence_records=evidence_records,
            analytical=analytical,
            error_code="" if all_success else ErrorCode.SQL_EXECUTION_ERROR.value,
            error_msg="" if all_success else "One or more analytical subqueries failed",
        )

    async def _analyze_single(
        self,
        request: DataAnalysisRequest,
        *,
        security: SecurityContext,
    ) -> DataAnalysisResult:
        if not security.authenticated:
            return DataAnalysisResult(
                success=False,
                question=request.question,
                error_code=ErrorCode.AUTHENTICATION_REQUIRED.value,
                error_msg="Trusted SecurityContext is required",
            )
        allowed_catalog = filter_catalog_for_security(self.catalog_provider.get(), security)
        if not allowed_catalog.tables:
            return DataAnalysisResult(
                success=False,
                question=request.question,
                error_code=ErrorCode.PERMISSION_DENIED.value,
                error_msg="No schema is available for the current data scope",
            )
        try:
            phase = "schema_link"
            link = await self.linker.link(
                request.question,
                allowed_catalog,
                task_type=request.task_type,
                top_k=settings.SQL_SCHEMA_LINK_TOP_K,
            )
            metrics.observe_schema_link(
                link.candidate_count, link.latency_ms / 1000, link.retrieval_mode
            )
            linked_names = set(link.table_names)
            generation_catalog = SchemaCatalog(
                tables=tuple(
                    table for table in allowed_catalog.tables if table.name in linked_names
                ),
                relations=link.relations,
                version=allowed_catalog.version,
            )
            generation_request = SQLGenerationRequest(
                question=request.question,
                tables=generation_catalog.tables,
                relations=generation_catalog.relations,
                max_rows=min(request.max_rows, settings.SQL_MAX_ROWS),
                dialect=request.dialect,
            )
            phase = "sql_generation"
            generation_started = time.perf_counter()
            generated = (
                GeneratedSQL(sql=request.sql)
                if request.sql
                else await self.generator.generate(generation_request)
            )
            metrics.observe_sql_generation(time.perf_counter() - generation_started)
            phase = "sql_validation"
            validation_catalog = allowed_catalog if request.sql else generation_catalog
            validated = self.validator.validate(
                generated.sql,
                catalog=validation_catalog,
                scope=tenant_scope_from_security(security),
                max_rows=request.max_rows,
                dialect=request.dialect,
            )
            generated = generated.model_copy(
                update={
                    "referenced_tables": list(validated.referenced_tables),
                    "referenced_columns": list(validated.referenced_columns),
                }
            )
            phase = "sql_execution"
            execution = await self._execute_with_repair(
                generated,
                validated,
                generation_request,
                request,
                security,
                allowed_catalog,
                validation_catalog,
            )
            result, repairs, final_generated, final_validated = execution
            evidence = SQLEvidence(
                id=result.lineage.query_id,
                source_name="postgres-read-role",
                timestamp=result.lineage.timestamp,
                tenant_id=security.tenant_id,
                store_id=security.store_id,
                sql=result.lineage.generated_sql,
                tables=result.lineage.referenced_tables,
                columns=result.lineage.referenced_columns,
                rows=result.rows[:20],
                row_count=result.row_count,
                truncated=result.truncated,
                lineage=result.lineage.model_dump(mode="json"),
            ).model_dump(mode="json")
            return DataAnalysisResult(
                success=True,
                question=request.question,
                catalog_source=allowed_catalog.source,
                schema_link=link,
                generated_sql=final_generated,
                validated_sql=final_validated,
                execution=result,
                evidence=evidence,
                evidence_records=[evidence],
                repair_attempts=repairs,
            )
        except SQLValidationError as exc:
            metrics.observe_sql_validation(False, exc.code)
            return DataAnalysisResult(
                success=False,
                question=request.question,
                schema_link=locals().get("link"),
                generated_sql=locals().get("generated"),
                error_code=exc.code,
                error_msg=str(exc),
            )
        except SQLGenerationError as exc:
            return DataAnalysisResult(
                success=False,
                question=request.question,
                schema_link=locals().get("link"),
                error_code=ErrorCode.SQL_GENERATION_ERROR.value,
                error_msg=str(exc),
            )
        except SQLExecutionFailure as exc:
            return DataAnalysisResult(
                success=False,
                question=request.question,
                schema_link=locals().get("link"),
                generated_sql=locals().get("generated"),
                validated_sql=locals().get("validated"),
                error_code=(
                    ErrorCode.SQL_REPAIR_EXHAUSTED.value
                    if exc.repairable
                    else ErrorCode.SQL_EXECUTION_ERROR.value
                ),
                error_msg=f"SQL execution failed: {exc.category}",
            )
        except Exception:
            code = {
                "schema_link": ErrorCode.SCHEMA_LINK_ERROR.value,
                "sql_generation": ErrorCode.SQL_GENERATION_ERROR.value,
                "sql_validation": ErrorCode.SQL_PARSE_ERROR.value,
                "sql_execution": ErrorCode.SQL_EXECUTION_ERROR.value,
            }.get(locals().get("phase"), ErrorCode.INTERNAL_ERROR.value)
            return DataAnalysisResult(
                success=False,
                question=request.question,
                schema_link=locals().get("link"),
                generated_sql=locals().get("generated"),
                validated_sql=locals().get("validated"),
                error_code=code,
                error_msg=f"Data intelligence phase failed: {locals().get('phase', 'unknown')}",
            )

    async def _execute_with_repair(
        self,
        generated,
        validated,
        generation_request,
        request,
        security,
        output_catalog,
        validation_catalog,
    ):
        attempts = 0
        while True:
            try:
                metrics.observe_sql_validation(True, "accepted")
                result = await self.executor.execute(
                    validated,
                    params=request.params,
                    scope=tenant_scope_from_security(security),
                    catalog=output_catalog,
                    max_rows=min(request.max_rows, settings.SQL_MAX_ROWS),
                )
                metrics.observe_sql_execution(
                    result.row_count,
                    result.lineage.execution_latency_ms / 1000,
                    result.truncated,
                )
                return result, attempts, generated, validated
            except SQLExecutionFailure as exc:
                if not exc.repairable or attempts >= int(settings.SQL_REPAIR_MAX_ATTEMPTS):
                    raise
                attempts += 1
                metrics.observe_sql_repair(exc.category, False)
                try:
                    generated = await self.repairer.repair(
                        generated,
                        generation_request,
                        error_category=exc.category,
                    )
                except Exception as repair_exc:
                    raise SQLExecutionFailure(exc.category, repairable=True) from repair_exc
                validated = self.validator.validate(
                    generated.sql,
                    catalog=validation_catalog,
                    scope=tenant_scope_from_security(security),
                    max_rows=request.max_rows,
                    dialect=request.dialect,
                )
                metrics.observe_sql_repair(exc.category, True)


data_intelligence_service = DataIntelligenceService()


__all__ = ["DataIntelligenceService", "data_intelligence_service"]
