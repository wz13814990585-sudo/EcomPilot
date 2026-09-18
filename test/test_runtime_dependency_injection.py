from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from ecom_agent_matrix.config.constants import AGENT_MASTER, AGENT_QUERY
from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.orchestration.master.orchestrator import MasterOrchestrator
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply import build_reply
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry


def _security() -> SecurityContext:
    return SecurityContext(
        subject="admin",
        user_id="admin",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"admin"}),
        scopes=frozenset(),
        auth_type="jwt",
        authenticated=True,
    )


def test_master_orchestrator_uses_injected_bus_and_reply_registry_end_to_end():
    async def scenario():
        replies = ReplyRegistry()
        sent = []

        class FakeBus:
            async def send(self, message):
                sent.append(message)
                if message.target == AGENT_QUERY:
                    replies.resolve(
                        message.correlation_id,
                        build_reply(
                            message,
                            sender=AGENT_QUERY,
                            success=True,
                            data={"answer": "found"},
                        ),
                    )
                return True

        bus = FakeBus()
        orchestrator = MasterOrchestrator(
            long_memory=AsyncMock(),
            message_bus_instance=bus,
            reply_registry=replies,
            planner=AsyncMock(),
            recovery=AsyncMock(),
        )
        root = AgentMessage(
            task_id="root-injected",
            sender=settings.API_SENDER,
            target=AGENT_MASTER,
            content={"task_type": "goods_search", "query": "find a bag"},
            security=_security(),
        )
        await orchestrator.run(root)
        await orchestrator.close()
        return sent, replies.pending_count

    sent, pending = asyncio.run(scenario())
    assert sent[0].target == AGENT_QUERY
    assert sent[-1].target == settings.API_SENDER
    assert sent[-1].content["success"] is True
    assert pending == 0
