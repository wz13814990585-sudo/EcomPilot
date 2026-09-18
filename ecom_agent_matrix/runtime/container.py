"""Composition root for process-owned runtime resources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ..application import AgentApplicationService
from ..agents.exec.agent import exec_agent
from ..agents.master.agent import MasterAgent
from ..agents.query.agent import query_agent
from ..agents.rag.agent import rag_agent
from ..config.constants import AGENT_EXEC, AGENT_MASTER, AGENT_QUERY, AGENT_RAG
from ..config.settings import Settings
from ..core.security.approval import ApprovalService
from ..core.skill.executor import SkillExecutor
from ..core.skill.skill_registry import skill_executor_context
from ..infrastructure.database import DatabaseManager
from ..infrastructure.llm import LLMGateway
from ..infrastructure.redis import RedisManager
from ..orchestration.master.orchestrator import (
    MasterOrchestrator,
    cancel_master_tasks,
)
from ..orchestration.master.planner import TypedMasterPlanner, typed_master_planner
from ..orchestration.master.recovery_controller import (
    RecoveryController,
    recovery_controller,
)
from .messaging.bus import MessageBus
from .messaging.message import AgentMessage
from .messaging.reply_registry import ReplyRegistry
from .messaging.registry import AgentRegistry


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
    task_reply_registry: ReplyRegistry[AgentMessage] | None = None
    gateway_reply_registry: ReplyRegistry[AgentMessage] | None = None
    planner: Any = None
    recovery_controller: Any = None
    master_orchestrator: MasterOrchestrator | None = None
    application_service: AgentApplicationService | None = None
    _agent_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.task_reply_registry = self.task_reply_registry or self.message_bus.task_reply_registry
        self.gateway_reply_registry = (
            self.gateway_reply_registry or self.message_bus.gateway_reply_registry
        )
        self.planner = self.planner or typed_master_planner
        self.recovery_controller = self.recovery_controller or recovery_controller
        self.master_orchestrator = self.master_orchestrator or MasterOrchestrator(
            message_bus_instance=self.message_bus,
            reply_registry=self.task_reply_registry,
            planner=self.planner,
            recovery=self.recovery_controller,
        )
        self.application_service = self.application_service or AgentApplicationService(
            message_bus=self.message_bus,
            agent_registry=self.agent_registry,
            reply_registry=self.gateway_reply_registry,
        )

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        agent_registry: AgentRegistry,
        message_bus: MessageBus | None = None,
    ):
        task_reply_registry: ReplyRegistry[AgentMessage] = (
            message_bus.task_reply_registry if message_bus is not None else ReplyRegistry()
        )
        gateway_reply_registry: ReplyRegistry[AgentMessage] = (
            message_bus.gateway_reply_registry if message_bus is not None else ReplyRegistry()
        )
        owned_bus = message_bus or MessageBus(
            queue_max=settings.MESSAGE_BUS_QUEUE_MAX_SIZE,
            enqueue_timeout=settings.MESSAGE_BUS_ENQUEUE_TIMEOUT,
            task_reply_registry=task_reply_registry,
            gateway_reply_registry=gateway_reply_registry,
        )
        owned_approval_service = ApprovalService()
        owned_skill_executor = SkillExecutor(
            approval_service_instance=owned_approval_service,
        )
        owned_planner = TypedMasterPlanner()
        owned_recovery_controller = RecoveryController()
        return cls(
            settings=settings,
            db=DatabaseManager(settings),
            redis=RedisManager(),
            message_bus=owned_bus,
            agent_registry=agent_registry,
            llm_gateway=LLMGateway(),
            skill_executor=owned_skill_executor,
            approval_service=owned_approval_service,
            task_reply_registry=task_reply_registry,
            gateway_reply_registry=gateway_reply_registry,
            planner=owned_planner,
            recovery_controller=owned_recovery_controller,
        )

    async def start(self) -> None:
        await self.db.start()
        await self.redis.start()
        if not self.agent_registry.definitions:
            raise RuntimeError("agent registry is empty")

        async def serve_query(queue):
            with skill_executor_context(self.skill_executor):
                await query_agent(queue, bus=self.message_bus)

        async def serve_exec(queue):
            with skill_executor_context(self.skill_executor):
                await exec_agent(queue, bus=self.message_bus)

        worker_overrides = {
            AGENT_MASTER: MasterAgent(self.master_orchestrator).serve,
            AGENT_QUERY: serve_query,
            AGENT_EXEC: serve_exec,
            AGENT_RAG: partial(rag_agent, bus=self.message_bus),
        }
        self._agent_task = asyncio.create_task(
            self.agent_registry.serve(
                self.message_bus,
                worker_overrides=worker_overrides,
            ),
            name="agent-runtime",
        )
        await asyncio.sleep(0)

    @property
    def agents_alive(self) -> bool:
        return bool(self._agent_task and not self._agent_task.done())

    async def close(self) -> None:
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()
            await asyncio.gather(self._agent_task, return_exceptions=True)
        if self.master_orchestrator is not None:
            await self.master_orchestrator.close()
        await cancel_master_tasks()
        await self.message_bus.close()
        await self.llm_gateway.close()
        await self.redis.close()
        await self.db.close()
        self._agent_task = None


__all__ = ["AppRuntime"]
