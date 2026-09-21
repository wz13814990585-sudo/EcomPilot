from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.config.constants import AGENT_QUERY
from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.core.skill.skill_registry import skill_execution_context
from ecom_agent_matrix.modules.skills.competitor_price import _latest_db_price
from ecom_agent_matrix.modules.skills.data_integrity_check import _check_orders
from ecom_agent_matrix.modules.skills.goods_sku_search import _literal_ilike_only
from ecom_agent_matrix.modules.skills.ops_report import _sales_stats, _stock_stats


def _security() -> SecurityContext:
    return SecurityContext(
        subject="scope-test",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        scopes=frozenset(),
        auth_type="jwt",
        authenticated=True,
    )


def test_business_reads_apply_explicit_tenant_and_store_predicates():
    async def scenario():
        with (
            skill_execution_context(AGENT_QUERY, security=_security()),
            patch(
                "ecom_agent_matrix.db.base.AsyncPGClient.execute_read",
                new=AsyncMock(),
            ) as execute,
        ):
            execute.return_value = [(0, 0, 0, 0)]
            await _sales_stats(7)
            sales_call = execute.await_args

            execute.return_value = [(0, 0, 0, 0)]
            await _stock_stats()
            stock_call = execute.await_args

            execute.return_value = []
            await _latest_db_price("BAG-001", "Temu")
            competitor_call = execute.await_args

            await _literal_ilike_only("背包", 5)
            goods_call = execute.await_args

            await _check_orders(limit=5)
            order_call = execute.await_args

        return sales_call, stock_call, competitor_call, goods_call, order_call

    for call in asyncio.run(scenario()):
        sql = " ".join(call.args[0].lower().split())
        params = call.args[1]
        assert "tenant_id = %s" in sql or "tenant_id=%s" in sql
        assert "store_id = %s" in sql or "store_id=%s" in sql
        assert "tenant-a" in params and "store-a" in params
        assert call.kwargs["scope"].usable is True


def test_recent_sales_excludes_future_dated_orders():
    async def scenario():
        with (
            skill_execution_context(AGENT_QUERY, security=_security()),
            patch(
                "ecom_agent_matrix.db.base.AsyncPGClient.execute_read",
                new=AsyncMock(return_value=[(0, 0, 0, 0)]),
            ) as execute,
        ):
            await _sales_stats(30)
            return execute.await_args.args[0]

    assert "create_time <= NOW()" in asyncio.run(scenario())
