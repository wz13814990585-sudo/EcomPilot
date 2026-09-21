"""Cached schema catalog and permission filtering."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from ...core.security import SecurityContext
from ...core.security.policy import effective_scopes
from ...db.base import AsyncPGClient
from .schemas import (
    ColumnAccess,
    SchemaCatalog,
    SchemaColumn,
    SchemaRelation,
    SchemaTable,
    Sensitivity,
)


def _column(name: str, data_type: str, description: str, *terms: str, **kwargs) -> SchemaColumn:
    return SchemaColumn(
        name=name,
        data_type=data_type,
        description=description,
        business_terms=tuple(terms),
        **kwargs,
    )


def default_catalog() -> SchemaCatalog:
    """Deterministic startup catalog for the repository's business schema."""
    tenant = _column("tenant_id", "varchar", "tenant isolation identifier", "tenant")
    store = _column("store_id", "varchar", "store isolation identifier", "store", "店铺")
    return SchemaCatalog(
        tables=(
            SchemaTable(
                name="ecom_order",
                description="orders, sales and refund facts",
                business_terms=("订单", "销售额", "退款率", "sales", "revenue", "refund"),
                allowed_scopes=frozenset({"commerce:read"}),
                columns=(
                    _column("id", "bigint", "order row identifier", primary_key=True),
                    tenant,
                    store,
                    _column("order_no", "varchar", "business order number", "订单号"),
                    _column("sku", "varchar", "ordered product SKU", "商品"),
                    _column("buy_num", "integer", "units purchased", "销量", "quantity", "sales"),
                    _column(
                        "total_amount", "decimal", "gross order amount", "销售额", "GMV", "revenue"
                    ),
                    _column(
                        "refund_flag",
                        "boolean",
                        "whether order was refunded",
                        "退款",
                        "refund rate",
                    ),
                    _column(
                        "create_time",
                        "timestamp",
                        "order creation time",
                        "时间",
                        "本月",
                        "月份",
                        "按月",
                        "month",
                        "date",
                    ),
                ),
            ),
            SchemaTable(
                name="ecom_goods",
                description="product catalog, price and inventory",
                business_terms=("商品", "库存", "品类", "product", "inventory", "category"),
                allowed_scopes=frozenset({"commerce:read"}),
                columns=(
                    _column("id", "bigint", "product row identifier", primary_key=True),
                    tenant,
                    store,
                    _column("sku", "varchar", "product SKU", "商品编码"),
                    _column("category", "varchar", "product category", "品类"),
                    _column("price", "decimal", "unit selling price", "价格", "value"),
                    _column("stock_num", "integer", "available inventory", "库存", "inventory"),
                    _column("title_zh", "text", "Chinese product title", "商品名"),
                    _column("title_en", "text", "English product title"),
                    _column("store_name", "varchar", "store display name", "店铺"),
                    _column(
                        "create_time", "timestamp", "product creation time", "时间", "本月", "month"
                    ),
                ),
            ),
            SchemaTable(
                name="competitor_price",
                description="competitor price observations",
                business_terms=("竞品", "比价", "competitor", "price comparison"),
                allowed_scopes=frozenset({"commerce:read"}),
                columns=(
                    _column("id", "bigint", "price observation identifier", primary_key=True),
                    tenant,
                    store,
                    _column("target_sku", "varchar", "our product SKU", "sku"),
                    _column("competitor_name", "varchar", "competitor name", "竞品"),
                    _column("compete_price", "decimal", "observed competitor price", "竞品价"),
                    _column("crawl_time", "timestamp", "observation time", "抓取时间", "history"),
                ),
            ),
            SchemaTable(
                name="risk_record",
                description="order risk flags and descriptions",
                business_terms=("风险", "异常订单", "risk"),
                allowed_scopes=frozenset({"system:read"}),
                columns=(
                    _column("id", "bigint", "risk record identifier", primary_key=True),
                    tenant,
                    store,
                    _column("order_no", "varchar", "business order number", "订单号"),
                    _column("risk_type", "varchar", "risk classification", "风险类型"),
                    _column("risk_desc", "text", "internal risk description", "风险说明"),
                    _column("create_time", "timestamp", "risk detection time"),
                ),
            ),
        ),
        relations=(
            SchemaRelation(
                from_table="ecom_order",
                from_column="sku",
                to_table="ecom_goods",
                to_column="sku",
                description="orders reference products by SKU within tenant/store RLS",
            ),
            SchemaRelation(
                from_table="competitor_price",
                from_column="target_sku",
                to_table="ecom_goods",
                to_column="sku",
                description="price observations reference catalog products",
            ),
            SchemaRelation(
                from_table="risk_record",
                from_column="order_no",
                to_table="ecom_order",
                to_column="order_no",
                description="risk records reference orders",
            ),
        ),
        version="business-schema-v1",
    )


def _granted(
    *,
    roles: frozenset[str],
    scopes: frozenset[str],
    allowed_roles: frozenset[str],
    allowed_scopes: frozenset[str],
) -> bool:
    return (not allowed_roles and not allowed_scopes) or bool(
        roles.intersection(allowed_roles) or scopes.intersection(allowed_scopes)
    )


def filter_catalog_for_security(catalog: SchemaCatalog, security: SecurityContext) -> SchemaCatalog:
    """Remove forbidden tables/columns before schema linking or generation."""
    if not security.authenticated:
        return SchemaCatalog(tables=(), relations=(), version=catalog.version)
    scopes = effective_scopes(security)
    tables: list[SchemaTable] = []
    for table in catalog.tables:
        if not _granted(
            roles=security.roles,
            scopes=scopes,
            allowed_roles=table.allowed_roles,
            allowed_scopes=table.allowed_scopes,
        ):
            continue
        columns = tuple(
            column
            for column in table.columns
            if column.access != ColumnAccess.DENY
            and _granted(
                roles=security.roles,
                scopes=scopes,
                allowed_roles=column.allowed_roles,
                allowed_scopes=column.allowed_scopes,
            )
            and not (
                column.sensitivity == Sensitivity.RESTRICTED
                and "data:sensitive" not in scopes
                and "admin" not in security.roles
            )
        )
        if columns:
            tables.append(table.model_copy(update={"columns": columns}))
    table_names = {table.name for table in tables}
    relations = tuple(
        relation
        for relation in catalog.relations
        if relation.from_table in table_names and relation.to_table in table_names
    )
    return SchemaCatalog(
        tables=tuple(tables),
        relations=relations,
        version=catalog.version,
        source=catalog.source,
    )


def _value(row: Any, index: int, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else row[index]


class PostgresSchemaCatalogLoader:
    """Discover technical metadata once and merge it with the static business glossary."""

    def __init__(
        self,
        execute: Callable[[str, list | None], Awaitable[list[Any]]] | None = None,
        *,
        glossary: SchemaCatalog | None = None,
        schemas: tuple[str, ...] = ("public",),
    ) -> None:
        self.execute = execute or AsyncPGClient.execute_metadata
        self.glossary = glossary or default_catalog()
        self.schemas = schemas

    async def load(self) -> SchemaCatalog:
        placeholders = ", ".join(["%s"] * len(self.schemas))
        params = list(self.schemas)
        table_rows = await self.execute(
            "SELECT t.table_schema, t.table_name, obj_description(c.oid) AS comment "
            "FROM information_schema.tables t "
            "LEFT JOIN pg_catalog.pg_class c ON c.relname=t.table_name "
            f"WHERE t.table_type='BASE TABLE' AND t.table_schema IN ({placeholders}) "
            "ORDER BY t.table_schema, t.table_name",
            params,
        )
        column_rows = await self.execute(
            "SELECT c.table_schema, c.table_name, c.column_name, c.data_type, "
            "c.ordinal_position, pgd.description "
            "FROM information_schema.columns c "
            "LEFT JOIN pg_catalog.pg_class pc ON pc.relname=c.table_name "
            "LEFT JOIN pg_catalog.pg_attribute pa ON pa.attrelid=pc.oid "
            "AND pa.attname=c.column_name "
            "LEFT JOIN pg_catalog.pg_description pgd ON pgd.objoid=pc.oid "
            "AND pgd.objsubid=pa.attnum "
            f"WHERE c.table_schema IN ({placeholders}) "
            "ORDER BY c.table_schema, c.table_name, c.ordinal_position",
            params,
        )
        relation_rows = await self.execute(
            "SELECT tc.table_name, kcu.column_name, "
            "ccu.table_name AS foreign_table_name, "
            "ccu.column_name AS foreign_column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema "
            "WHERE tc.constraint_type='FOREIGN KEY' "
            f"AND tc.table_schema IN ({placeholders}) ORDER BY tc.constraint_name",
            params,
        )
        primary_rows = await self.execute(
            "SELECT tc.table_name, kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
            "WHERE tc.constraint_type='PRIMARY KEY' "
            f"AND tc.table_schema IN ({placeholders})",
            params,
        )
        if not table_rows:
            raise RuntimeError("postgres schema catalog is empty")

        primary_keys = {
            (str(_value(row, 0, "table_name")), str(_value(row, 1, "column_name")))
            for row in primary_rows
        }
        columns_by_table: dict[str, list[SchemaColumn]] = {}
        for row in column_rows:
            table_name = str(_value(row, 1, "table_name"))
            column_name = str(_value(row, 2, "column_name"))
            glossary_table = self.glossary.table(table_name)
            glossary_column = glossary_table.column(column_name) if glossary_table else None
            technical = SchemaColumn(
                name=column_name,
                data_type=str(_value(row, 3, "data_type")),
                description=str(_value(row, 5, "description") or ""),
                primary_key=(table_name, column_name) in primary_keys,
            )
            if glossary_column:
                technical = glossary_column.model_copy(
                    update={
                        "data_type": technical.data_type,
                        "description": technical.description or glossary_column.description,
                        "primary_key": technical.primary_key or glossary_column.primary_key,
                    }
                )
            columns_by_table.setdefault(table_name, []).append(technical)

        tables: list[SchemaTable] = []
        for row in table_rows:
            table_name = str(_value(row, 1, "table_name"))
            columns = tuple(columns_by_table.get(table_name, ()))
            if not columns:
                continue
            glossary_table = self.glossary.table(table_name)
            description = str(_value(row, 2, "comment") or "")
            if glossary_table:
                tables.append(
                    glossary_table.model_copy(
                        update={
                            "description": description or glossary_table.description,
                            "columns": columns,
                        }
                    )
                )
            else:
                tables.append(
                    SchemaTable(
                        name=table_name,
                        description=description,
                        columns=columns,
                        allowed_roles=frozenset({"admin"}),
                    )
                )
        relations = tuple(
            SchemaRelation(
                from_table=str(_value(row, 0, "table_name")),
                from_column=str(_value(row, 1, "column_name")),
                to_table=str(_value(row, 2, "foreign_table_name")),
                to_column=str(_value(row, 3, "foreign_column_name")),
            )
            for row in relation_rows
        )
        fingerprint = json.dumps(
            {
                "tables": [table.model_dump(mode="json") for table in tables],
                "relations": [relation.model_dump(mode="json") for relation in relations],
            },
            sort_keys=True,
        )
        version = "postgres-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
        return SchemaCatalog(
            tables=tuple(tables), relations=relations, version=version, source="postgres"
        )

    async def load_or_fallback(self) -> SchemaCatalog:
        try:
            return await self.load()
        except Exception:
            return self.glossary.model_copy(update={"source": "static_fallback"})


class SchemaCatalogProvider:
    """Process-local catalog loaded once and refreshed only on explicit request."""

    def __init__(self, catalog: SchemaCatalog | None = None) -> None:
        self._catalog = catalog or default_catalog()
        self._lock = asyncio.Lock()

    def get(self) -> SchemaCatalog:
        return self._catalog

    async def refresh(self, loader: Callable[[], Awaitable[SchemaCatalog]]) -> SchemaCatalog:
        async with self._lock:
            loaded = await loader()
            self._catalog = loaded
            return loaded

    async def refresh_from_postgres(
        self, loader: PostgresSchemaCatalogLoader | None = None
    ) -> SchemaCatalog:
        active_loader = loader or PostgresSchemaCatalogLoader()
        return await self.refresh(active_loader.load_or_fallback)


schema_catalog_provider = SchemaCatalogProvider()


__all__ = [
    "SchemaCatalogProvider",
    "PostgresSchemaCatalogLoader",
    "default_catalog",
    "filter_catalog_for_security",
    "schema_catalog_provider",
]
