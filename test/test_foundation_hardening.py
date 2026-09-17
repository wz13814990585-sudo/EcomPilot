"""Core runtime contracts introduced by the foundation hardening pass."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.config.constants import AGENT_MASTER, AGENT_QUERY
from ecom_agent_matrix.core.mcp.bus import MCPMessageBus
from ecom_agent_matrix.core.mcp.message import MCPMessage
from ecom_agent_matrix.modules.agent_cluster.master.executor import (
    AGENT_UNAVAILABLE,
    MasterPlanExecutor,
)
from ecom_agent_matrix.modules.agent_cluster.master.schemas import MasterPlan, PlanStep


def test_message_create_time_uses_unix_epoch_seconds():
    before = time.time()
    message = MCPMessage(sender="a", target="b", content={})
    after = time.time()
    assert before <= message.create_time <= after


def test_message_bus_can_unregister_exact_subscription():
    bus = MCPMessageBus()
    first = bus.register_agent("worker")
    second = bus.register_agent("worker")

    assert bus.unregister_agent("worker", first) == 1
    assert bus.agent_subscribe["worker"] == [second]
    assert bus.unregister_agent("worker") == 1
    assert "worker" not in bus.agent_subscribe
    assert bus.unregister_agent("worker") == 0


def test_plan_executor_fails_fast_when_agent_has_no_subscriber():
    async def scenario():
        plan = MasterPlan(
            decision="execute",
            confidence=1.0,
            reason_code="TEST",
            planner_source="test",
            steps=[
                PlanStep(
                    step_id="lookup",
                    agent=AGENT_QUERY,
                    task_type="goods_search",
                )
            ],
        )
        request = MCPMessage(
            task_id="root",
            sender=AGENT_MASTER,
            target=AGENT_MASTER,
            content={"query": "test"},
        )
        executor = MasterPlanExecutor(timeout=60)
        with patch(
            "ecom_agent_matrix.modules.agent_cluster.master.executor.mcp_bus.send_msg",
            new=AsyncMock(return_value=False),
        ), patch(
            "ecom_agent_matrix.modules.agent_cluster.master.executor.TaskReplyWaiter.wait",
            new=AsyncMock(),
        ) as wait:
            result = await executor.execute(plan, request)
        wait.assert_not_awaited()
        return result

    result = asyncio.run(scenario())
    step = result.step_results["lookup"]
    assert step.status == "FAILED"
    assert step.error_code == AGENT_UNAVAILABLE
    assert result.timed_out is False
