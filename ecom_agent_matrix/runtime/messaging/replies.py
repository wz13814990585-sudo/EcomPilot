"""Runtime-owned reply registries."""

from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry

task_replies: ReplyRegistry[AgentMessage] = ReplyRegistry()
gateway_replies: ReplyRegistry[AgentMessage] = ReplyRegistry()


def resolve_task_reply(message: AgentMessage) -> bool:
    """Resolve a Master subtask reply by its correlation identifier."""
    return task_replies.resolve(message.correlation_id, message)


__all__ = ["gateway_replies", "resolve_task_reply", "task_replies"]
