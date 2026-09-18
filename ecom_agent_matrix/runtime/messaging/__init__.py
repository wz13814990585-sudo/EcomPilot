"""In-process agent messaging with explicit delivery and reply semantics."""

from ecom_agent_matrix.runtime.messaging.bus import MessageBus, message_bus
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry

__all__ = ["AgentMessage", "MessageBus", "ReplyRegistry", "message_bus"]
