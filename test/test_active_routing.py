from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.agents.exec.agent import execute_exec
from ecom_agent_matrix.agents.query.agent import execute_query
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.tasking import TaskContext, WorkflowResult


def test_query_missing_task_type_is_rejected_without_legacy_inference():
    with patch("ecom_agent_matrix.agents.query.agent.run_goods_workflow", new=AsyncMock()) as goods:
        result = asyncio.run(execute_query(TaskContext(query="find a bag")))
    assert result.error_code == ErrorCode.UNSUPPORTED_TASK.value
    goods.assert_not_awaited()


def test_exec_missing_task_type_is_rejected_without_legacy_inference():
    with patch("ecom_agent_matrix.agents.exec.agent.run_crm_workflow", new=AsyncMock()) as crm:
        result = asyncio.run(execute_exec(TaskContext(query="reply to customer")))
    assert result.error_code == ErrorCode.UNSUPPORTED_TASK.value
    crm.assert_not_awaited()


def test_explicit_query_and_exec_task_types_still_dispatch():
    async def scenario():
        with patch(
            "ecom_agent_matrix.agents.query.agent.run_goods_workflow",
            new=AsyncMock(return_value=WorkflowResult(success=True)),
        ) as goods:
            query = await execute_query(TaskContext(task_type="goods_search"))
        with patch(
            "ecom_agent_matrix.agents.exec.agent.run_crm_workflow",
            new=AsyncMock(return_value=WorkflowResult(success=True)),
        ) as crm:
            execution = await execute_exec(TaskContext(task_type="customer_service"))
        return query, execution, goods, crm

    query, execution, goods, crm = asyncio.run(scenario())
    assert query.success and execution.success
    goods.assert_awaited_once()
    crm.assert_awaited_once()


def test_competitor_task_without_query_never_falls_back_to_goods():
    async def scenario():
        result = WorkflowResult(success=True, data={"query_kind": "competitor"})
        with (
            patch(
                "ecom_agent_matrix.agents.query.agent.run_competitor_workflow",
                new=AsyncMock(return_value=result),
            ) as competitor,
            patch(
                "ecom_agent_matrix.agents.query.agent.run_goods_workflow", new=AsyncMock()
            ) as goods,
        ):
            actual = await execute_query(
                TaskContext(
                    task_type="competitor_watch",
                    sku="SKU-BAG-001",
                    competitor="Temu",
                )
            )
        return actual, competitor, goods

    result, competitor, goods = asyncio.run(scenario())
    assert result.success
    competitor.assert_awaited_once()
    goods.assert_not_awaited()
