from __future__ import annotations

import asyncio

from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.modules.data_intelligence import (
    ColumnAccess,
    DataAnalysisRequest,
    DataIntelligenceService,
    GeneratedSQL,
    SafeSQLExecutor,
    SchemaCatalog,
    SchemaCatalogProvider,
    SchemaColumn,
    SchemaTable,
)


def _security() -> SecurityContext:
    return SecurityContext(
        subject="subject",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        scopes=frozenset(),
        auth_type="jwt",
        authenticated=True,
    )


def test_data_service_runs_deterministic_text_to_sql_with_lineage():
    calls = []

    async def execute(sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        return [(1234.5, 17)], False

    service = DataIntelligenceService(executor=SafeSQLExecutor(execute))
    result = asyncio.run(
        service.analyze(
            DataAnalysisRequest(question="本月销售额和订单数是多少？"),
            security=_security(),
        )
    )
    assert result.success is True
    assert result.repair_attempts == 0
    assert result.execution.rows == [{"revenue": 1234.5, "order_count": 17}]
    assert result.execution.lineage.tenant_id == "tenant-a"
    assert result.execution.lineage.store_id == "store-a"
    assert result.execution.lineage.referenced_tables == ("ecom_order",)
    assert "LIMIT" not in calls[0][0]
    assert calls[0][2]["scope"].identity_trusted is True


def test_data_service_repairs_once_then_revalidates_and_executes():
    execution_count = 0

    async def execute(sql, params, **kwargs):
        nonlocal execution_count
        execution_count += 1
        if execution_count == 1:
            raise RuntimeError("UndefinedColumn: valid legacy alias does not exist")
        return [(9,)], False

    class Repairer:
        calls = 0

        async def repair(self, generated, request, *, error_category):
            self.calls += 1
            assert error_category == "undefined_column"
            return GeneratedSQL(sql="SELECT COUNT(*) AS order_count FROM ecom_order")

    repairer = Repairer()
    service = DataIntelligenceService(
        executor=SafeSQLExecutor(execute),
        repairer=repairer,
    )
    result = asyncio.run(
        service.analyze(
            DataAnalysisRequest(
                question="查询订单数",
                sql="SELECT COUNT(total_amount) AS order_count FROM ecom_order",
            ),
            security=_security(),
        )
    )
    assert result.success is True
    assert execution_count == 2
    assert repairer.calls == 1
    assert result.repair_attempts == 1
    assert result.validated_sql.sql == "SELECT COUNT(*) AS order_count FROM ecom_order"


def test_data_service_never_repairs_permission_failures():
    async def execute(sql, params, **kwargs):
        raise PermissionError("permission denied by RLS")

    class Repairer:
        calls = 0

        async def repair(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("must not repair permission failures")

    repairer = Repairer()
    result = asyncio.run(
        DataIntelligenceService(executor=SafeSQLExecutor(execute), repairer=repairer).analyze(
            DataAnalysisRequest(
                question="查询订单",
                sql="SELECT order_no FROM ecom_order",
            ),
            security=_security(),
        )
    )
    assert result.success is False
    assert result.error_code == ErrorCode.SQL_EXECUTION_ERROR.value
    assert result.error_msg == "SQL execution failed: permission_denied"
    assert repairer.calls == 0


def test_unsafe_sql_is_blocked_before_execution_or_repair():
    calls = 0

    async def execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [], False

    result = asyncio.run(
        DataIntelligenceService(executor=SafeSQLExecutor(execute)).analyze(
            DataAnalysisRequest(question="删除所有退款记录", sql="DELETE FROM ecom_order"),
            security=_security(),
        )
    )
    assert result.success is False
    assert result.error_code == ErrorCode.UNSAFE_SQL.value
    assert calls == 0


def test_data_service_rejects_untrusted_identity():
    untrusted = _security().model_copy(update={"authenticated": False})
    result = asyncio.run(
        DataIntelligenceService().analyze(
            DataAnalysisRequest(question="本月销售额是多少？"),
            security=untrusted,
        )
    )
    assert result.error_code == ErrorCode.AUTHENTICATION_REQUIRED.value


def test_sensitive_output_policy_masks_permitted_internal_fields():
    async def execute(sql, params, **kwargs):
        return [{"contact": "alice@example.com"}], False

    catalog = SchemaCatalog(
        tables=(
            SchemaTable(
                name="customers",
                allowed_scopes=frozenset({"commerce:read"}),
                columns=(
                    SchemaColumn(name="email", access=ColumnAccess.MASK),
                    SchemaColumn(name="tenant_id"),
                    SchemaColumn(name="store_id"),
                ),
            ),
        )
    )
    result = asyncio.run(
        DataIntelligenceService(
            catalog_provider=SchemaCatalogProvider(catalog),
            executor=SafeSQLExecutor(execute),
        ).analyze(
            DataAnalysisRequest(
                question="customer email", sql="SELECT email AS contact FROM customers"
            ),
            security=_security(),
        )
    )
    assert result.success is True
    assert result.execution.rows == [{"contact": "a***@example.com"}]
