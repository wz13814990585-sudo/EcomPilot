"""Agent definitions and worker lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from .bus import MessageBus, message_bus

AgentWorker = Callable[[asyncio.Queue], object]


class AgentRegistry:
    def __init__(self) -> None:
        self.definitions: dict[str, AgentWorker] = {}

    def register(self, agent_id: str):
        def decorator(worker: AgentWorker):
            if agent_id in self.definitions and self.definitions[agent_id] is not worker:
                raise ValueError(f"duplicate agent registration: {agent_id}")
            self.definitions[agent_id] = worker
            return worker

        return decorator

    async def serve(
        self,
        bus: MessageBus = message_bus,
        *,
        worker_overrides: dict[str, AgentWorker] | None = None,
    ) -> None:
        workers: list[tuple[str, asyncio.Queue, asyncio.Task]] = []
        try:
            for agent_id, worker in self.definitions.items():
                worker = (worker_overrides or {}).get(agent_id, worker)
                queue = bus.register(agent_id)
                task = asyncio.create_task(worker(queue), name=f"agent:{agent_id}")
                workers.append((agent_id, queue, task))
            await asyncio.gather(*(item[2] for item in workers))
        finally:
            for _agent_id, _queue, task in workers:
                if not task.done():
                    task.cancel()
            if workers:
                await asyncio.gather(*(item[2] for item in workers), return_exceptions=True)
            for agent_id, queue, _task in workers:
                bus.unregister(agent_id, queue)


agent_registry = AgentRegistry()
agent_map = agent_registry.definitions
register_agent = agent_registry.register


async def start_all_agents() -> None:
    await agent_registry.serve(message_bus)


__all__ = ["AgentRegistry", "agent_map", "agent_registry", "register_agent", "start_all_agents"]
