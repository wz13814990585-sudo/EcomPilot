"""HTTP adapter for the agent application service."""

from __future__ import annotations

import uuid
import time
from typing import Any

from fastapi import HTTPException, status

from ..config.constants import AGENT_MASTER
from ..config.settings import settings
from ..core.llm.output_polish import polish_final_output
from ..core.errors import ErrorCode
from ..application import AgentApplicationService
from ..runtime.messaging.bus import message_bus
from ..runtime.messaging.registry import agent_registry
from ..core.security import SecurityContext
from ..core.security import ApprovalGrant
from ..platform.observability.context import get_trace_context, update_trace_context
from ..platform.observability.context import get_performance_summary

application_service = AgentApplicationService(
    message_bus=message_bus, agent_registry=agent_registry
)

_ERROR_HTTP_STATUS = {
    ErrorCode.AUTHENTICATION_REQUIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.PERMISSION_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.AGENT_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.AGENT_TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    ErrorCode.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.INVALID_REQUEST: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def set_application_service(service: AgentApplicationService) -> None:
    global application_service
    application_service = service


async def dispatch_and_wait(
    *,
    target: str,
    content: dict[str, Any],
    priority: int,
    timeout: float | None = None,
    security: SecurityContext | None = None,
    approval: ApprovalGrant | None = None,
) -> dict[str, Any]:
    """向目标 Agent 发任务并等待最终回传，并生成可读 summary。"""
    request_started = time.perf_counter()
    task_id = get_trace_context().task_id or str(uuid.uuid4())
    wait_timeout = float(timeout if timeout is not None else settings.API_REQUEST_TIMEOUT)
    response = await application_service.execute(
        target=target,
        priority=priority,
        content=content,
        security=security,
        approval=approval,
        timeout=wait_timeout,
        task_id=task_id,
    )
    update_trace_context(
        task_id=task_id,
        correlation_id=str(response.metadata.get("correlation_id") or ""),
    )
    mapped_status = _ERROR_HTTP_STATUS.get(response.error_code)
    if mapped_status is not None:
        raise HTTPException(
            status_code=mapped_status,
            detail={
                "error_code": response.error_code.value,
                "message": response.error_message,
            },
            headers={"X-Task-Id": task_id},
        )

    data = response.data
    success = response.success
    error_msg = response.error_message
    user_query = str(
        content.get("query") or content.get("user_query") or content.get("product_name") or ""
    )

    # Master 若已在 data.summary 写好，直接复用；否则统一整理
    if isinstance(data.get("summary"), str) and data["summary"].strip():
        summary = data["summary"].strip()
    else:
        summary = await polish_final_output(
            success=success,
            data=data,
            error_msg=error_msg,
            user_query=user_query,
            reply_from=response.reply_from or target,
        )

    return {
        "task_id": task_id,
        "target": target,
        "reply_from": response.reply_from,
        "success": success,
        "data": data,
        "error_msg": error_msg,
        "msg_type": response.msg_type,
        "error_code": response.error_code,
        "status": response.status,
        "summary": summary,
        "performance": {
            "latency_ms": round((time.perf_counter() - request_started) * 1000, 2),
            **get_performance_summary(),
        },
    }


async def dispatch_to_master(
    content: dict[str, Any],
    *,
    priority: int,
    timeout: float | None = None,
    security: SecurityContext | None = None,
    approval: ApprovalGrant | None = None,
) -> dict[str, Any]:
    return await dispatch_and_wait(
        target=AGENT_MASTER,
        content=content,
        priority=priority,
        timeout=timeout,
        security=security,
        approval=approval,
    )
