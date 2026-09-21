from __future__ import annotations

import asyncio

import pytest

from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.security import SecurityContext, TenantScope
from ecom_agent_matrix.modules.data_intelligence import (
    ColumnAccess,
    HybridSchemaLinker,
    SQLGuardConfig,
    SQLSafetyValidator,
    SQLValidationError,
    SchemaCatalog,
    SchemaColumn,
    SchemaTable,
    Sensitivity,
    default_catalog,
    filter_catalog_for_security,
)


def _security(*, roles=("viewer",), scopes=()) -> SecurityContext:
    return SecurityContext(
        subject="subject",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset(roles),
        scopes=frozenset(scopes),
        auth_type="jwt",
        authenticated=True,
    )


def _scope() -> TenantScope:
    return TenantScope(tenant_id="tenant-a", store_id="store-a", identity_trusted=True)


def test_catalog_filters_before_linking_and_hides_restricted_columns():
    catalog = SchemaCatalog(
        tables=(
            SchemaTable(
                name="payments",
                description="payment records",
                allowed_scopes=frozenset({"finance:read"}),
                columns=(SchemaColumn(name="id"),),
            ),
            SchemaTable(
                name="customers",
                description="customer records",
                allowed_scopes=frozenset({"commerce:read"}),
                columns=(
                    SchemaColumn(name="id"),
                    SchemaColumn(
                        name="payment_token",
                        sensitivity=Sensitivity.RESTRICTED,
                        access=ColumnAccess.MASK,
                    ),
                ),
            ),
        )
    )
    filtered = filter_catalog_for_security(catalog, _security())
    assert [table.name for table in filtered.tables] == ["customers"]
    assert [column.name for column in filtered.tables[0].columns] == ["id"]


def test_schema_linking_is_inspectable_without_irrelevant_fk_expansion():
    result = asyncio.run(
        HybridSchemaLinker().link("为什么本月退款率上涨？", default_catalog(), top_k=1)
    )
    assert result.tables[0].name == "ecom_order"
    assert "EXACT_ALIAS_MATCH" in result.tables[0].reason_codes
    assert "refund_flag" in {column.name for column in result.tables[0].columns}
    assert result.table_names == ["ecom_order"]
    assert result.retrieval_mode == "lexical_only"
    assert result.candidate_count == 4
    assert result.latency_ms >= 0


def test_sql_validator_enforces_ast_permissions_and_limit():
    validator = SQLSafetyValidator(SQLGuardConfig(max_rows=25))
    validated = validator.validate(
        "SELECT order_no, total_amount FROM ecom_order ORDER BY create_time DESC LIMIT 999",
        catalog=default_catalog(),
        scope=_scope(),
    )
    assert validated.sql.endswith("LIMIT 25")
    assert validated.applied_limit == 25
    assert validated.referenced_tables == ("ecom_order",)
    assert "ecom_order.total_amount" in validated.referenced_columns


def test_sql_validator_does_not_change_single_row_aggregate_semantics():
    validated = SQLSafetyValidator().validate(
        "SELECT COUNT(*) AS order_count, SUM(total_amount) AS revenue FROM ecom_order",
        catalog=default_catalog(),
        scope=_scope(),
    )
    assert "LIMIT" not in validated.sql
    assert validated.applied_limit is None


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("DELETE FROM ecom_order", ErrorCode.UNSAFE_SQL.value),
        ("SELECT pg_sleep(10)", ErrorCode.UNSAFE_SQL.value),
        ("SELECT * FROM security_approval", ErrorCode.TABLE_NOT_ALLOWED.value),
        ("SELECT secret_value FROM ecom_order", ErrorCode.COLUMN_NOT_ALLOWED.value),
        ("SELECT * FROM ecom_order FOR UPDATE", ErrorCode.UNSAFE_SQL.value),
        ("SELECT 1; SELECT 2", ErrorCode.UNSAFE_SQL.value),
    ],
)
def test_sql_validator_rejects_unsafe_or_forbidden_sql(sql: str, code: str):
    with pytest.raises(SQLValidationError) as raised:
        SQLSafetyValidator().validate(sql, catalog=default_catalog(), scope=_scope())
    assert raised.value.code == code


def test_sql_validator_requires_trusted_scope_for_tenant_tables():
    with pytest.raises(SQLValidationError) as raised:
        SQLSafetyValidator().validate(
            "SELECT order_no FROM ecom_order",
            catalog=default_catalog(),
            scope=TenantScope(),
        )
    assert raised.value.code == ErrorCode.PERMISSION_DENIED.value


def test_sql_cost_guard_rejects_excessive_join_shape():
    with pytest.raises(SQLValidationError) as raised:
        SQLSafetyValidator(SQLGuardConfig(max_join_tables=0)).validate(
            "SELECT o.order_no FROM ecom_order o JOIN ecom_goods g ON g.sku=o.sku",
            catalog=default_catalog(),
            scope=_scope(),
        )
    assert raised.value.code == ErrorCode.QUERY_COST_EXCEEDED.value
