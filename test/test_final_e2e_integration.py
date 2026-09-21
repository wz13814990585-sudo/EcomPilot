from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.security import SecurityContext, TenantScope
from ecom_agent_matrix.modules.data_intelligence import (
    DataAnalysisRequest,
    DataIntelligenceService,
    SQLSafetyValidator,
    SafeSQLExecutor,
    SchemaCatalogProvider,
    default_catalog,
)
from ecom_agent_matrix.runtime.container import AppRuntime
from ecom_agent_matrix.runtime.messaging.bus import MessageBus
from ecom_agent_matrix.runtime.messaging.registry import AgentRegistry
from eval.enterprise.final_report import _git_sha
from eval.enterprise.live_sql import runner as gold_runner
from eval.enterprise.live_sql.runner import _evaluate_case, _print_failures


def _security() -> SecurityContext:
    return SecurityContext(
        subject="test",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        scopes=frozenset({"commerce:read"}),
        auth_type="system",
        authenticated=True,
    )


def test_boolean_operator_is_not_treated_as_an_executable_function():
    validated = SQLSafetyValidator().validate(
        "SELECT COUNT(*) FROM ecom_order WHERE refund_flag AND buy_num > 0",
        catalog=default_catalog(),
        scope=TenantScope(tenant_id="tenant-a", store_id="store-a", identity_trusted=True),
    )
    assert validated.referenced_tables == ("ecom_order",)


def test_gold_runner_separates_parse_and_safety_and_prints_case_details(capsys):
    connection = SimpleNamespace()
    malformed = {
        "id": "parse-case",
        "question": "bad parse",
        "sql": "SELECT ('",
        "expected": [],
    }
    unsafe = {
        "id": "safety-case",
        "question": "unsafe function",
        "sql": "SELECT pg_sleep(1)",
        "expected": [],
    }
    parse_result = _evaluate_case(connection, malformed)
    safety_result = _evaluate_case(connection, unsafe)
    assert parse_result["sql_parse_valid"] is False
    assert parse_result["sql_safety_pass"] is False
    assert safety_result["sql_parse_valid"] is True
    assert safety_result["sql_safety_pass"] is False
    _print_failures({"cases": [parse_result, safety_result]})
    output = capsys.readouterr().out
    assert "FAIL parse-case" in output
    assert "question: unsafe function" in output
    assert "stage: SAFETY" in output
    assert "expected:" in output


def _runtime(loader):
    async def worker(queue):
        while True:
            await queue.get()
            queue.task_done()

    registry = AgentRegistry()
    registry.register("worker")(worker)
    return AppRuntime(
        settings=SimpleNamespace(APP_ENV="test"),
        db=SimpleNamespace(start=AsyncMock(), close=AsyncMock()),
        redis=SimpleNamespace(start=AsyncMock(), close=AsyncMock()),
        message_bus=MessageBus(queue_max=2),
        agent_registry=registry,
        llm_gateway=SimpleNamespace(close=AsyncMock()),
        skill_executor=SimpleNamespace(),
        approval_service=SimpleNamespace(),
        schema_catalog_provider=SchemaCatalogProvider(),
        schema_catalog_loader=loader,
    )


def test_runtime_refreshes_postgres_catalog_and_exposes_source_and_version():
    class Loader:
        async def load_or_fallback(self):
            return default_catalog().model_copy(
                update={"source": "postgres", "version": "postgres-test-v2"}
            )

    async def scenario():
        runtime = _runtime(Loader())
        with patch("ecom_agent_matrix.runtime.container.cancel_master_tasks", new=AsyncMock()):
            await runtime.start()
            assert runtime.catalog_source == "postgres"
            assert runtime.schema_version == "postgres-test-v2"
            assert (
                runtime.data_intelligence_service.catalog_provider
                is runtime.schema_catalog_provider
            )
            await runtime.close()

    asyncio.run(scenario())


def test_runtime_catalog_failure_is_explicit_static_fallback():
    class Loader:
        async def load_or_fallback(self):
            return default_catalog().model_copy(update={"source": "static_fallback"})

    async def scenario():
        runtime = _runtime(Loader())
        with patch("ecom_agent_matrix.runtime.container.cancel_master_tasks", new=AsyncMock()):
            await runtime.start()
            assert runtime.catalog_source == "static_fallback"
            await runtime.close()

    asyncio.run(scenario())


def test_catalog_refresh_replaces_schema_version():
    async def scenario():
        provider = SchemaCatalogProvider()

        async def load():
            return default_catalog().model_copy(
                update={"source": "postgres", "version": "postgres-refresh-v3"}
            )

        before = provider.get().version
        after = await provider.refresh(load)
        assert before != after.version
        assert provider.get().version == "postgres-refresh-v3"

    asyncio.run(scenario())


def test_analytical_partial_status_and_concurrency_bound(monkeypatch):
    active = 0
    maximum = 0

    async def execute(sql, params, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        if "GROUP BY sku" in sql:
            raise RuntimeError("database error")
        return [("segment", 10, 2, 0.2)], False

    monkeypatch.setattr(settings, "ANALYSIS_MAX_CONCURRENT", 2)
    result = asyncio.run(
        DataIntelligenceService(executor=SafeSQLExecutor(execute)).analyze(
            DataAnalysisRequest(question="为什么8月退款率上涨？"), security=_security()
        )
    )
    assert result.success is False
    assert result.analytical.status == "PARTIAL"
    assert sum(step.success for step in result.analytical.steps) == 2
    assert len(result.evidence_records) == 2
    assert maximum == 2


def test_final_report_sha_is_read_from_current_checkout():
    assert len(_git_sha()) == 40


def test_gold_runner_writes_report_for_not_run_result(tmp_path):
    output = tmp_path / "gold.json"
    with patch.object(gold_runner, "run", return_value=gold_runner._not_run("offline")):
        assert gold_runner.main(["--output", str(output)]) == 0
    assert output.exists()
    assert '"status": "NOT_RUN"' in output.read_text()
