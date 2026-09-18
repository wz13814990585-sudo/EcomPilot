"""Composition root for process-owned runtime resources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ecom_agent_matrix.config.settings import Settings
from ecom_agent_matrix.core.security.approval import ApprovalService, approval_service
from ecom_agent_matrix.core.skill.executor import SkillExecutor, skill_executor
from ecom_agent_matrix.infrastructure.database import DatabaseManager
from ecom_agent_matrix.infrastructure.llm import LLMGateway
from ecom_agent_matrix.infrastructure.redis import RedisManager
from ecom_agent_matrix.orchestration.master.orchestrator import cancel_master_tasks
from ecom_agent_matrix.runtime.messaging.bus import MessageBus
from ecom_agent_matrix.runtime.messaging.registry import AgentRegistry


@dataclass
class AppRuntime:
    settings: Settings
    db: DatabaseManager
    redis: RedisManager
    message_bus: MessageBus
    agent_registry: AgentRegistry
    llm_gateway: LLMGateway
    skill_executor: SkillExecutor
    approval_service: ApprovalService
    _agent_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    @classmethod
    def build(cls, settings: Settings, *, message_bus: MessageBus, agent_registry: AgentRegistry):
        return cls(
            settings=settings,
            db=DatabaseManager(settings),
            redis=RedisManager(),
            message_bus=message_bus,
            agent_registry=agent_registry,
            llm_gateway=LLMGateway(),
            skill_executor=skill_executor,
            approval_service=approval_service,
        )

    async def start(self) -> None:
        await self.db.start()
        await self.redis.start()
        if not self.agent_registry.definitions:
            raise RuntimeError("agent registry is empty")
        self._agent_task = asyncio.create_task(
            self.agent_registry.serve(self.message_bus), name="agent-runtime"
        )
        await asyncio.sleep(0)

    @property
    def agents_alive(self) -> bool:
        return bool(self._agent_task and not self._agent_task.done())

    async def close(self) -> None:
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()
            await asyncio.gather(self._agent_task, return_exceptions=True)
        await cancel_master_tasks()
        await self.message_bus.close()
        await self.llm_gateway.close()
        await self.redis.close()
        await self.db.close()
        self._agent_task = None


__all__ = ["AppRuntime"]
