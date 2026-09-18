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
    _started: bool = field(default=False, init=False, repr=False)
    _db_started: bool = field(default=False, init=False, repr=False)
    _redis_started: bool = field(default=False, init=False, repr=False)
    _db_attempted: bool = field(default=False, init=False, repr=False)
    _redis_attempted: bool = field(default=False, init=False, repr=False)

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
        if self._started and self.agents_alive:
            return
        if self._started or self._db_attempted or self._redis_attempted or self._agent_task:
            await self._shutdown_resources()

        try:
            self._db_attempted = True
            await self.db.start()
            self._db_started = True
            self._redis_attempted = True
            await self.redis.start()
            self._redis_started = True
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
            ready_event = asyncio.Event()
            self._agent_task = asyncio.create_task(
                self.agent_registry.serve(
                    self.message_bus,
                    worker_overrides=worker_overrides,
                    ready_event=ready_event,
                ),
                name="agent-runtime",
            )
            ready_task = asyncio.create_task(ready_event.wait(), name="agent-runtime-ready")
            done, _ = await asyncio.wait(
                {self._agent_task, ready_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if self._agent_task in done:
                ready_task.cancel()
                await asyncio.gather(ready_task, return_exceptions=True)
                await self._agent_task
            await ready_task
            self._started = True
        except BaseException:
            await self._shutdown_resources()
            raise

    @property
    def agents_alive(self) -> bool:
        return bool(self._agent_task and not self._agent_task.done())

    async def close(self) -> None:
        if not any(
            (
                self._started,
                self._db_attempted,
                self._redis_attempted,
                self._agent_task is not None,
            )
        ):
            return
        await self._shutdown_resources()

    async def _shutdown_resources(self) -> None:
        """Best-effort reverse-order cleanup, safe after partial startup."""
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()
            await asyncio.gather(self._agent_task, return_exceptions=True)
        if self.master_orchestrator is not None:
            await asyncio.gather(self.master_orchestrator.close(), return_exceptions=True)
        await asyncio.gather(cancel_master_tasks(), return_exceptions=True)
        await asyncio.gather(self.message_bus.close(), return_exceptions=True)
        await asyncio.gather(self.llm_gateway.close(), return_exceptions=True)
        if self._redis_attempted:
            await asyncio.gather(self.redis.close(), return_exceptions=True)
        if self._db_attempted:
            await asyncio.gather(self.db.close(), return_exceptions=True)
        self._agent_task = None
        self._started = False
        self._db_started = False
        self._redis_started = False
        self._db_attempted = False
        self._redis_attempted = False


__all__ = ["AppRuntime"]
