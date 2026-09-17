"""MCP 消息数据模型。"""
# core/mcp/message.py
import time
import uuid

from pydantic import BaseModel, Field

from ecom_agent_matrix.config.constants import MSG_PRIORITY_NORMAL
from ecom_agent_matrix.core.security import ApprovalGrant, SecurityContext


class MCPMessage(BaseModel):
    """MCP 全局统一消息数据模型，所有智能体通信强制使用该结构。"""

    # 自动生成唯一任务 ID，用于日志追溯、任务关联。
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # 单条消息/子任务的请求-响应关联 ID；task_id 始终保留为用户请求根 ID。
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str
    target: str
    priority: int = MSG_PRIORITY_NORMAL
    content: dict
    security: SecurityContext | None = None
    approval: ApprovalGrant | None = None
    # Unix epoch seconds。不要使用 uuid.uuid1().time：后者是 UUID v1 的
    # 100ns Gregorian epoch 计数，并不是可直接用于日志/排序的 Unix 时间戳。
    create_time: float = Field(default_factory=time.time)
