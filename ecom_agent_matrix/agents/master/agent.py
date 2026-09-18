"""Thin message adapter for the Master control plane."""

from __future__ import annotations

import asyncio

from ecom_agent_matrix.config.constants import AGENT_MASTER
from ecom_agent_matrix.core.logging_config import setup_logger
from ecom_agent_matrix.orchestration.master.orchestrator import MasterOrchestrator
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.registry import register_agent

logger = setup_logger("agent.master")


class MasterAgent:
    def __init__(self, orchestrator: MasterOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or MasterOrchestrator()

    async def handle(self, message: AgentMessage) -> None:
        if message.content.get("type") in {"agent_reply", "rag_retrieve_result", "sub_agent_reply"}:
            return
        self.orchestrator.submit(message)

    async def serve(self, queue: asyncio.Queue) -> None:
        logger.info(
            "master_agent_started", extra={"event": "master_agent_started", "agent": AGENT_MASTER}
        )
        while True:
            message: AgentMessage = await queue.get()
            try:
                await self.handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "master_adapter_failed",
                    extra={
                        "event": "master_adapter_failed",
                        "task_id": message.task_id,
                        "error_type": type(exc).__name__,
                    },
                )
            finally:
                queue.task_done()


@register_agent(AGENT_MASTER)
async def master_agent(queue: asyncio.Queue) -> None:
    await MasterAgent().serve(queue)


__all__ = ["MasterAgent", "master_agent"]
