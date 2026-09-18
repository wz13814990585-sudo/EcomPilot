from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ecom_agent_matrix.config.constants import AGENT_MASTER
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.tasking import TaskStatus
from ecom_agent_matrix.orchestration.master import orchestrator
from ecom_agent_matrix.orchestration.master.orchestrator import MasterCompletion
from ecom_agent_matrix.orchestration.master.orchestrator import process_master_task
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply import build_reply
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry


@pytest.mark.parametrize(
    ("name", "completion", "expected_success"),
    [
        ("fast_path_success", MasterCompletion(success=True, status=TaskStatus.SUCCEEDED), True),
        (
            "agent_unavailable",
            MasterCompletion(
                success=False,
                status=TaskStatus.FAILED,
                error_code=ErrorCode.AGENT_UNAVAILABLE,
            ),
            False,
        ),
        (
            "timeout",
            MasterCompletion(
                success=False, status=TaskStatus.FAILED, error_code=ErrorCode.AGENT_TIMEOUT
            ),
            False,
        ),
        (
            "dag_partial",
            MasterCompletion(
                success=False, status=TaskStatus.PARTIAL, error_code=ErrorCode.AGENT_FAILED
            ),
            False,
        ),
        (
            "approval_required",
            MasterCompletion(
                success=False,
                status=TaskStatus.AWAITING_APPROVAL,
                error_code=ErrorCode.APPROVAL_REQUIRED,
            ),
            False,
        ),
    ],
)
def test_master_metric_uses_business_completion(name, completion, expected_success):
    async def scenario():
        message = AgentMessage(
            task_id=name,
            sender="api_gateway",
            target=AGENT_MASTER,
            content={"task_type": "goods_search"},
        )
        with (
            patch.object(
                orchestrator,
                "process_master_task",
                new=AsyncMock(return_value=completion),
            ),
            patch.object(orchestrator.metrics, "observe_agent") as observe,
        ):
            returned = await orchestrator.safe_process_master_task(message, AsyncMock())
        return returned, observe

    returned, observe = asyncio.run(scenario())
    assert returned == completion
    assert observe.call_args.args[0:2] == (AGENT_MASTER, expected_success)


def test_fast_path_partial_child_is_not_full_business_success():
    async def scenario():
        replies = ReplyRegistry()

        class Bus:
            final = None

            async def send(self, message):
                if message.target == "biz_exec":
                    replies.resolve(
                        message.correlation_id,
                        build_reply(
                            message,
                            sender="biz_exec",
                            success=True,
                            status=TaskStatus.PARTIAL.value,
                            data={"error_code": ErrorCode.PARTIAL_SUCCESS.value},
                        ),
                    )
                else:
                    self.final = message
                return True

        bus = Bus()
        completion = await process_master_task(
            AgentMessage(
                task_id="partial-fast",
                sender="api_gateway",
                target=AGENT_MASTER,
                content={"task_type": "social_marketing", "query": "generate copy"},
            ),
            AsyncMock(),
            message_bus_instance=bus,
            reply_registry=replies,
        )
        return completion, bus.final

    completion, final = asyncio.run(scenario())
    assert completion.success is False
    assert completion.status is TaskStatus.PARTIAL
    assert completion.error_code is ErrorCode.PARTIAL_SUCCESS
    assert final.content["success"] is False
    assert final.content["status"] == TaskStatus.PARTIAL.value
