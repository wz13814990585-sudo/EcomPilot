from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from ecom_agent_matrix.api.dispatch import dispatch_and_wait
from ecom_agent_matrix.api.schemas import ApiResult
from ecom_agent_matrix.application import AgentApplicationService, AgentResponse
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.tasking import TaskStatus
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry


def _response(code: ErrorCode | None, *, success: bool = False) -> AgentResponse:
    return AgentResponse(
        task_id="task-1",
        target="data_query",
        reply_from="data_query",
        success=success,
        data={"summary": "ok"} if success else {},
        error_code=code,
        error_message="failed" if code else "",
    )


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (ErrorCode.AUTHENTICATION_REQUIRED, 401),
        (ErrorCode.PERMISSION_DENIED, 403),
        (ErrorCode.AGENT_UNAVAILABLE, 503),
        (ErrorCode.AGENT_TIMEOUT, 504),
        (ErrorCode.RATE_LIMITED, 429),
        (ErrorCode.INVALID_REQUEST, 422),
    ],
)
def test_dispatch_maps_typed_error_codes_to_http_status(code, expected_status):
    service = AsyncMock()
    service.execute.return_value = _response(code)
    with patch("ecom_agent_matrix.api.dispatch.application_service", service):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(dispatch_and_wait(target="data_query", content={}, priority=1))

    assert raised.value.status_code == expected_status
    assert raised.value.detail["error_code"] == code.value
    assert raised.value.detail["title"]
    assert raised.value.detail["next_action"]
    assert raised.value.detail["task_id"]


def test_successful_api_result_has_none_error_code():
    service = AsyncMock()
    service.execute.return_value = _response(None, success=True)
    with patch("ecom_agent_matrix.api.dispatch.application_service", service):
        payload = asyncio.run(
            dispatch_and_wait(
                target="data_query", content={"task_type": "goods_search"}, priority=1
            )
        )

    result = ApiResult(**payload)
    assert result.success is True
    assert result.error_code is None


def test_unmapped_business_failure_preserves_error_code_in_api_result():
    service = AsyncMock()
    service.execute.return_value = _response(ErrorCode.APPROVAL_REQUIRED)
    with (
        patch("ecom_agent_matrix.api.dispatch.application_service", service),
        patch(
            "ecom_agent_matrix.api.dispatch.polish_final_output",
            new=AsyncMock(return_value="approval required"),
        ),
    ):
        payload = asyncio.run(dispatch_and_wait(target="biz_exec", content={}, priority=1))

    result = ApiResult(**payload)
    assert result.error_code is ErrorCode.APPROVAL_REQUIRED
    assert result.status is TaskStatus.AWAITING_APPROVAL


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"success": True, "error_code": "AGENT_TIMEOUT", "data": {}}, None),
        ({"success": False, "data": {}}, ErrorCode.AGENT_FAILED),
    ],
)
def test_application_service_normalizes_success_and_malformed_failure_codes(body, expected):
    async def scenario():
        replies = ReplyRegistry()

        async def send(message):
            replies.resolve(
                message.task_id,
                AgentMessage(
                    task_id=message.task_id,
                    sender="data_query",
                    target="api_gateway",
                    content=body,
                ),
            )
            return True

        service = AgentApplicationService(
            message_bus=SimpleNamespace(send=send),
            agent_registry=SimpleNamespace(definitions={"data_query": object()}),
            reply_registry=replies,
        )
        return await service.execute(target="data_query", content={}, priority=1)

    assert asyncio.run(scenario()).error_code is expected


def test_dispatch_preserves_safe_root_business_error_for_people():
    service = AsyncMock()
    service.execute.return_value = AgentResponse(
        task_id="task-1",
        target="master_planning",
        reply_from="master_planning",
        success=False,
        data={
            "sub_results": [
                {
                    "success": False,
                    "error_msg": "缺少投放数据，请提供广告活动或指标。",
                    "data": {"campaign_id": ""},
                }
            ]
        },
        error_code=ErrorCode.INVALID_REQUEST,
        error_message="任务未能完成。",
    )
    with patch("ecom_agent_matrix.api.dispatch.application_service", service):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                dispatch_and_wait(
                    target="master_planning",
                    content={"query": "优化广告"},
                    priority=1,
                )
            )
    assert raised.value.detail["message"] == "缺少投放数据，请提供广告活动或指标。"
    assert "子任务" not in raised.value.detail["message"]
