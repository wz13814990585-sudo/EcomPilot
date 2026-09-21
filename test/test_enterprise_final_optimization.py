from __future__ import annotations

import asyncio

import pytest

from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.security import SecurityContext, TenantScope
from ecom_agent_matrix.modules.data_intelligence import (
    AnalyticalQueryPlanner,
    DataAnalysisRequest,
    DataIntelligenceService,
    HybridSchemaLinker,
    PostgresSchemaCatalogLoader,
    SQLSafetyValidator,
    SQLValidationError,
    SafeSQLExecutor,
    SchemaCatalog,
    SchemaColumn,
    SchemaSemanticScorer,
    SchemaTable,
    default_catalog,
)


def _scope() -> TenantScope:
    return TenantScope(tenant_id="tenant-a", store_id="store-a", identity_trusted=True)


def _security() -> SecurityContext:
    return SecurityContext(
        subject="test",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        auth_type="system",
        authenticated=True,
    )


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.batch_calls = 0

    async def embed_text(self, text: str) -> list[float]:
        return [0.0, 1.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls += 1
        return [[1.0, 0.0], [0.0, 1.0]][: len(texts)]


def _semantic_catalog(version: str = "v1") -> SchemaCatalog:
    return SchemaCatalog(
        version=version,
        tables=(
            SchemaTable(name="alpha", columns=(SchemaColumn(name="a"),)),
            SchemaTable(name="beta", columns=(SchemaColumn(name="b"),)),
        ),
    )


def test_semantic_schema_score_selects_lexically_weak_candidate_and_caches_by_version():
    provider = FakeEmbeddingProvider()
    scorer = SchemaSemanticScorer(provider, model_version="fake-v1")
    linker = HybridSchemaLinker(scorer, absolute_threshold=0.1, relative_threshold=0.8)
    first = asyncio.run(linker.link("unseen concept", _semantic_catalog()))
    second = asyncio.run(linker.link("another unseen concept", _semantic_catalog()))
    assert first.table_names == ["beta"]
    assert first.retrieval_mode == "hybrid"
    assert second.retrieval_mode == "hybrid"
    assert provider.batch_calls == 1
    asyncio.run(linker.link("unseen concept", _semantic_catalog("v2")))
    assert provider.batch_calls == 2
    assert any(key.startswith("v2:") for key in scorer.cache_keys())


@pytest.mark.parametrize("semantic", [RuntimeError("offline"), [0.9]])
def test_semantic_failure_or_invalid_length_degrades_explicitly(semantic):
    async def score(question, texts):
        if isinstance(semantic, Exception):
            raise semantic
        return semantic

    result = asyncio.run(HybridSchemaLinker(score).link("orders", default_catalog()))
    assert result.retrieval_mode == "lexical_only"
    assert result.table_names


def test_postgres_catalog_loader_merges_business_terms_and_versions_catalog():
    async def execute(sql, params):
        if "table_type='BASE TABLE'" in sql:
            return [("public", "ecom_order", "live orders")]
        if "information_schema.columns" in sql:
            return [
                ("public", "ecom_order", "id", "bigint", 1, None),
                ("public", "ecom_order", "total_amount", "numeric", 2, None),
            ]
        if "FOREIGN KEY" in sql:
            return []
        return [("ecom_order", "id")]

    catalog = asyncio.run(PostgresSchemaCatalogLoader(execute).load())
    assert catalog.source == "postgres"
    assert catalog.version.startswith("postgres-")
    assert "销售额" in catalog.table("ecom_order").column("total_amount").business_terms
    assert catalog.table("ecom_order").column("id").primary_key is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*), SUM(total_amount), AVG(total_amount) FROM ecom_order",
        "SELECT DATE_TRUNC('month', create_time), EXTRACT(month FROM create_time) FROM ecom_order",
        "SELECT ROUND(total_amount / NULLIF(buy_num, 0), 2) FROM ecom_order",
        "SELECT CASE WHEN refund_flag THEN 1 ELSE 0 END FROM ecom_order",
    ],
)
def test_safe_function_and_construct_allowlist(sql: str):
    assert SQLSafetyValidator().validate(sql, catalog=default_catalog(), scope=_scope())


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(1)",
        "SELECT set_config('x', 'y', true)",
        "SELECT dblink('x', 'select 1')",
        "SELECT lo_import('/tmp/x')",
        "SELECT lo_export(1, '/tmp/x')",
        "SELECT query_to_xml('select 1', true, true, '')",
        "SELECT pg_advisory_lock(1)",
        "SELECT custom_func(total_amount) FROM ecom_order",
    ],
)
def test_unknown_or_dangerous_functions_fail_closed(sql: str):
    with pytest.raises(SQLValidationError) as raised:
        SQLSafetyValidator().validate(sql, catalog=default_catalog(), scope=_scope())
    assert raised.value.code == ErrorCode.UNSAFE_SQL.value


def test_analytical_plan_uses_only_available_dimensions_and_is_bounded():
    plan = AnalyticalQueryPlanner().plan_if_supported("为什么8月退款率上涨？", default_catalog())
    assert plan is not None
    assert {step.step_type.value for step in plan.steps} == {
        "metric_trend",
        "category_breakdown",
        "sku_breakdown",
    }
    assert len(plan.steps) <= 4
    assert "region_breakdown" not in {step.step_type.value for step in plan.steps}


def test_analytical_service_executes_every_subquery_through_safe_path():
    sql_calls: list[str] = []

    async def execute(sql, params, **kwargs):
        sql_calls.append(sql)
        return [("segment", 10, 2, 0.2)], False

    result = asyncio.run(
        DataIntelligenceService(executor=SafeSQLExecutor(execute)).analyze(
            DataAnalysisRequest(question="为什么8月退款率上涨？"), security=_security()
        )
    )
    assert result.success is True
    assert result.analytical is not None
    assert len(result.analytical.steps) == len(sql_calls) == 3
    assert all(step.lineage is not None for step in result.analytical.steps)
    assert len(result.evidence_records) == 3
