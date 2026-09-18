"""Application boundary hiding messages and reply registries from HTTP routes."""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.security import ApprovalGrant, SecurityContext
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.replies import gateway_replies


class AgentResponse(BaseModel):
    task_id: str
    target: str
    reply_from: str = ""
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: ErrorCode | None = None
    error_message: str = ""
    msg_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentApplicationService:
    def __init__(self, *, message_bus, agent_registry, reply_registry=gateway_replies) -> None:
        self.message_bus = message_bus
        self.agent_registry = agent_registry
        self.reply_registry = reply_registry

    async def execute(
        self,
        *,
        target: str,
        content: dict[str, Any],
        priority: int,
        timeout: float | None = None,
        security: SecurityContext | None = None,
        approval: ApprovalGrant | None = None,
        task_id: str | None = None,
    ) -> AgentResponse:
        started = time.perf_counter()
        request_id = task_id or str(uuid.uuid4())
        if target not in self.agent_registry.definitions:
            return AgentResponse(
                task_id=request_id,
                target=target,
                success=False,
                error_code=ErrorCode.AGENT_UNAVAILABLE,
                error_message=f"Agent unavailable: {target}",
            )
        self.reply_registry.create(request_id)
        message = AgentMessage(
            task_id=request_id,
            sender=settings.API_SENDER,
            target=target,
            priority=priority,
            content=content,
            security=security,
            approval=approval,
        )
        try:
            delivered = await self.message_bus.send(message)
            if not delivered:
                return AgentResponse(
                    task_id=request_id,
                    target=target,
                    success=False,
                    error_code=ErrorCode.AGENT_UNAVAILABLE,
                    error_message=f"Agent unavailable: {target}",
                )
            reply = await self.reply_registry.wait(
                request_id, float(timeout if timeout is not None else settings.API_REQUEST_TIMEOUT)
            )
        finally:
            self.reply_registry.discard(request_id)
        if reply is None:
            return AgentResponse(
                task_id=request_id,
                target=target,
                success=False,
                error_code=ErrorCode.AGENT_TIMEOUT,
                error_message=f"Agent timed out: {target}",
            )
        body = reply.content or {}
        data = body.get("data") or {}
        if not isinstance(data, dict):
            data = {"raw": data}
        raw_code = body.get("error_code") or data.get("error_code")
        success = bool(body.get("success"))
        if success:
            error_code = None
        else:
            try:
                error_code = ErrorCode(raw_code) if raw_code else ErrorCode.AGENT_FAILED
            except ValueError:
                error_code = ErrorCode.AGENT_FAILED
        return AgentResponse(
            task_id=request_id,
            target=target,
            reply_from=reply.sender,
            success=success,
            data=data,
            error_code=error_code,
            error_message=str(body.get("error_msg") or ""),
            msg_type=str(body.get("type") or ""),
            metadata={
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "correlation_id": message.correlation_id,
            },
        )


__all__ = ["AgentApplicationService", "AgentResponse"]
