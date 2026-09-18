"""Internal agent message envelope (this is not Model Context Protocol)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ecom_agent_matrix.config.constants import MSG_PRIORITY_NORMAL
from ecom_agent_matrix.core.security import ApprovalGrant, SecurityContext


class AgentMessage(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str
    target: str
    priority: int = MSG_PRIORITY_NORMAL
    content: dict
    security: SecurityContext | None = None
    approval: ApprovalGrant | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["AgentMessage"]
