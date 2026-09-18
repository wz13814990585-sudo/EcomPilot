from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.runtime.container import AppRuntime
from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.runtime.messaging.bus import MessageBus, message_bus
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.registry import AgentRegistry
from ecom_agent_matrix.runtime.messaging.replies import gateway_replies, task_replies
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry


def test_message_bus_register_unregister_and_unavailable_are_deterministic():
    async def scenario():
        bus = MessageBus(queue_max=2)
        message = AgentMessage(sender="test", target="worker", content={})
        assert await bus.send(message) is False
        queue = bus.register("worker")
        assert await bus.send(message) is True
        assert await queue.get() is message
        queue.task_done()
        assert bus.unregister("worker", queue) is True
        assert bus.unregister("worker", queue) is False
        await bus.close()

    asyncio.run(scenario())


def test_message_bus_full_queue_returns_within_enqueue_timeout():
    async def scenario():
        bus = MessageBus(queue_max=1, enqueue_timeout=0.02)
        bus._persist = AsyncMock()
        bus.register("worker")
        first = AgentMessage(sender="test", target="worker", content={})
        second = AgentMessage(sender="test", target="worker", content={})
        assert await bus.send(first) is True
        started = time.perf_counter()
        assert await bus.send(second) is False
        elapsed = time.perf_counter() - started
        await bus.close()
        return elapsed

    assert asyncio.run(scenario()) < 0.2


def test_message_bus_close_drains_audit_and_rejects_new_messages():
    async def scenario():
        local_tasks = ReplyRegistry()
        local_gateway = ReplyRegistry()
        bus = MessageBus(
            queue_max=4,
            enqueue_timeout=0.2,
            task_reply_registry=local_tasks,
            gateway_reply_registry=local_gateway,
        )
        persisted = []

        async def persist(message):
            persisted.append(message.task_id)

        bus._persist = persist
        message = AgentMessage(task_id="audit-1", sender="test", target="missing", content={})
        assert await bus.send(message) is False
        pending = local_tasks.create("late")
        await bus.close()
        assert persisted == ["audit-1"]
        assert pending.cancelled()
        assert await bus.send(message) is False
        assert local_tasks.pending_count == 0

    asyncio.run(scenario())


def test_runtime_can_start_close_and_start_without_duplicate_consumers():
    async def scenario():
        starts = 0

        async def worker(queue):
            nonlocal starts
            starts += 1
            while True:
                await queue.get()
                queue.task_done()

        registry = AgentRegistry()
        registry.register("worker")(worker)
        bus = MessageBus(queue_max=2)
        db = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        redis = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        llm = SimpleNamespace(close=AsyncMock())
        runtime = AppRuntime(
            settings=SimpleNamespace(),
            db=db,
            redis=redis,
            message_bus=bus,
            agent_registry=registry,
            llm_gateway=llm,
            skill_executor=SimpleNamespace(),
            approval_service=SimpleNamespace(),
        )

        with patch(
            "ecom_agent_matrix.runtime.container.cancel_master_tasks", new=AsyncMock()
        ) as cancel_master:
            await runtime.start()
            await asyncio.sleep(0)
            assert runtime.agents_alive and set(bus.agent_subscribe) == {"worker"}
            await runtime.close()
            assert not runtime.agents_alive and bus.agent_subscribe == {}

            await runtime.start()
            await asyncio.sleep(0)
            assert runtime.agents_alive and set(bus.agent_subscribe) == {"worker"}
            await runtime.close()

        assert starts == 2
        assert db.start.await_count == 2 and db.close.await_count == 2
        assert redis.start.await_count == 2 and redis.close.await_count == 2
        assert llm.close.await_count == 2
        assert cancel_master.await_count == 2

    asyncio.run(scenario())


def test_runtime_close_cleans_pending_reply_futures():
    async def scenario():
        bus = MessageBus(queue_max=2)
        task_future = task_replies.create("task-pending")
        gateway_future = gateway_replies.create("gateway-pending")
        await bus.close()
        assert task_future.cancelled() and gateway_future.cancelled()
        assert task_replies.pending_count == 0
        assert gateway_replies.pending_count == 0

    asyncio.run(scenario())


def test_runtime_build_owns_bus_replies_orchestrator_and_application_service():
    registry = AgentRegistry()
    runtime = AppRuntime.build(settings, agent_registry=registry)

    assert runtime.message_bus is not message_bus
    assert runtime.message_bus.task_reply_registry is runtime.task_reply_registry
    assert runtime.message_bus.gateway_reply_registry is runtime.gateway_reply_registry
    assert runtime.master_orchestrator.message_bus is runtime.message_bus
    assert runtime.master_orchestrator.reply_registry is runtime.task_reply_registry
    assert runtime.application_service.message_bus is runtime.message_bus
    assert runtime.application_service.reply_registry is runtime.gateway_reply_registry
    assert runtime.skill_executor.approval_service is runtime.approval_service
