from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from ecom_agent_matrix.config.constants import AGENT_EXEC, AGENT_MASTER, AGENT_QUERY
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.tasking import TaskStatus
from ecom_agent_matrix.orchestration.master.orchestrator import _process_complex_plan
from ecom_agent_matrix.orchestration.master.router import MasterRouteDecision
from ecom_agent_matrix.orchestration.master.schemas import MasterPlan, PlanStep
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply import build_reply
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry


def test_approval_required_exec_step_fails_composite_plan_without_retry():
    async def scenario():
        replies = ReplyRegistry()

        class Bus:
            def __init__(self):
                self.final = None
                self.exec_calls = 0

            async def send(self, message):
                if message.target == AGENT_QUERY:
                    replies.resolve(
                        message.correlation_id,
                        build_reply(
                            message,
                            sender=AGENT_QUERY,
                            success=True,
                            data={"order_no": "ORD-1"},
                        ),
                    )
                elif message.target == AGENT_EXEC:
                    self.exec_calls += 1
                    replies.resolve(
                        message.correlation_id,
                        build_reply(
                            message,
                            sender=AGENT_EXEC,
                            success=False,
                            error_msg="Human approval required",
                            status=TaskStatus.AWAITING_APPROVAL.value,
                            data={
                                "error_code": ErrorCode.APPROVAL_REQUIRED.value,
                                "approval_required": True,
                                "approval_id": "approval-1",
                            },
                        ),
                    )
                else:
                    self.final = message
                return True

        plan = MasterPlan(
            decision="execute",
            confidence=1,
            reason_code="EVAL_APPROVAL",
            planner_source="test",
            steps=[
                PlanStep(step_id="order", agent=AGENT_QUERY, task_type="order_query"),
                PlanStep(
                    step_id="risk_write",
                    agent=AGENT_EXEC,
                    task_type="risk_control",
                    depends_on=["order"],
                ),
            ],
        )
        bus = Bus()
        planner = AsyncMock()
        planner.plan.return_value = plan
        recovery = AsyncMock()
        recovery.run.return_value = None
        message = AgentMessage(
            task_id="root-approval",
            sender="api_gateway",
            target=AGENT_MASTER,
            content={"query": "check and record risk"},
        )
        completion = await _process_complex_plan(
            message,
            AsyncMock(),
            MasterRouteDecision(
                mode="planner",
                confidence=1,
                reason_code="test",
            ),
            dict(message.content),
            0,
            message_bus_instance=bus,
            reply_registry=replies,
            planner=planner,
            recovery=recovery,
        )
        return completion, bus

    completion, bus = asyncio.run(scenario())
    assert completion.success is False
    assert completion.error_code is ErrorCode.APPROVAL_REQUIRED
    assert completion.status is TaskStatus.AWAITING_APPROVAL
    assert bus.final.content["success"] is False
    assert bus.final.content["data"]["all_success"] is False
    assert bus.final.content["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert bus.exec_calls == 1
