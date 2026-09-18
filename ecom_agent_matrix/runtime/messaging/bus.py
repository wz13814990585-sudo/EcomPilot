"""Bounded in-process message bus with one logical queue per agent."""

from __future__ import annotations

import asyncio
import json

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.logging_config import setup_logger
from ecom_agent_matrix.core.security import tenant_scope_from_security
from ecom_agent_matrix.db.base import AsyncPGClient
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.replies import gateway_replies, task_replies

logger = setup_logger("runtime.messaging")
_REPLY_TYPES = frozenset({"agent_reply", "rag_retrieve_result", "sub_agent_reply"})
_GATEWAY_TYPES = _REPLY_TYPES | {"master_task_result"}


class MessageBus:
    """At-most-once in-process dispatch to a single consumer queue per agent."""

    def __init__(self, *, queue_max: int | None = None) -> None:
        self.queue_max = int(queue_max or settings.MESSAGE_BUS_QUEUE_MAX_SIZE)
        self._consumers: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._audit_queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=self.queue_max)
        self._audit_task: asyncio.Task | None = None

    @property
    def agent_subscribe(self) -> dict[str, list[asyncio.Queue[AgentMessage]]]:
        """Deprecated inspection view for older diagnostics."""
        return {key: [value] for key, value in self._consumers.items()}

    @property
    def msg_queue(self) -> asyncio.Queue[AgentMessage]:
        return self._audit_queue

    def register(self, agent_id: str) -> asyncio.Queue[AgentMessage]:
        if agent_id in self._consumers:
            raise RuntimeError(f"agent already registered: {agent_id}")
        queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=self.queue_max)
        self._consumers[agent_id] = queue
        return queue

    def unregister(self, agent_id: str, queue: asyncio.Queue[AgentMessage] | None = None) -> bool:
        current = self._consumers.get(agent_id)
        if current is None or (queue is not None and queue is not current):
            return False
        del self._consumers[agent_id]
        return True

    register_agent = register
    unregister_agent = unregister

    async def send(self, message: AgentMessage) -> bool:
        """Dispatch first; enqueue ordinary trace persistence without blocking."""
        delivered = self._resolve_waiter(message)
        queue = self._consumers.get(message.target)
        if queue is not None:
            await queue.put(message)
            delivered = True
        self._enqueue_audit(message)
        if not delivered:
            logger.error(
                "message_no_consumer",
                extra={
                    "event": "message_no_consumer",
                    "task_id": message.task_id,
                    "target": message.target,
                    "sender": message.sender,
                },
            )
        return delivered

    async def send_msg(self, message: AgentMessage) -> bool:
        """Deprecated spelling retained at the migration boundary."""
        return await self.send(message)

    def _resolve_waiter(self, message: AgentMessage) -> bool:
        msg_type = str(message.content.get("type") or "")
        resolved = False
        if msg_type in _REPLY_TYPES:
            resolved = task_replies.resolve(message.correlation_id, message) or resolved
        if message.target == settings.API_SENDER and msg_type in _GATEWAY_TYPES:
            key = str(message.content.get("ref_task_id") or message.task_id)
            resolved = gateway_replies.resolve(key, message) or resolved
        return resolved

    def _enqueue_audit(self, message: AgentMessage) -> None:
        if self._audit_task is None or self._audit_task.done():
            self._audit_task = asyncio.create_task(
                self._audit_worker(), name="message-audit-writer"
            )
        try:
            self._audit_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                "message_audit_drop",
                extra={"event": "message_audit_drop", "task_id": message.task_id},
            )

    async def _audit_worker(self) -> None:
        while True:
            message = await self._audit_queue.get()
            try:
                await self._persist(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "message_persist_failed",
                    extra={
                        "event": "message_persist_failed",
                        "task_id": message.task_id,
                        "error_type": type(exc).__name__,
                    },
                )
            finally:
                self._audit_queue.task_done()

    async def _persist(self, message: AgentMessage) -> None:
        scope = tenant_scope_from_security(message.security)
        columns = "task_id, sender_agent, target_agent, priority, msg_content"
        values: list[object] = [
            message.task_id,
            message.sender,
            message.target,
            message.priority,
            json.dumps(message.content, ensure_ascii=False),
        ]
        placeholders = "%s, %s, %s, %s, %s::jsonb"
        if scope.usable:
            columns = "tenant_id, store_id, " + columns
            placeholders = "%s, %s, " + placeholders
            values = [scope.tenant_id, scope.store_id, *values]
        await AsyncPGClient.execute_write(
            f"INSERT INTO agent_message_log({columns}) VALUES ({placeholders})",
            values,
            scope=scope,
        )

    async def close(self) -> None:
        self._consumers.clear()
        await task_replies.close()
        await gateway_replies.close()
        if self._audit_task is not None and not self._audit_task.done():
            self._audit_task.cancel()
            await asyncio.gather(self._audit_task, return_exceptions=True)
        self._audit_task = None
        while not self._audit_queue.empty():
            self._audit_queue.get_nowait()
            self._audit_queue.task_done()


message_bus = MessageBus()

__all__ = ["MessageBus", "message_bus"]
