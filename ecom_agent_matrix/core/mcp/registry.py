"""Agent 注册中心。"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from ecom_agent_matrix.core.mcp.bus import mcp_bus

# 全局 Agent 注册表：key=Agent 标识，value=Agent 异步执行函数。
agent_map: dict[str, Callable] = {}


def register_agent(agent_id: str):
    """装饰器：标记并注册任意 Agent 函数。"""

    def decorator(agent_func: Callable):
        if agent_id in agent_map:
            raise ValueError(f"Agent 重复注册：{agent_id}")
        agent_map[agent_id] = agent_func
        return agent_func

    return decorator


async def start_all_agents() -> None:
    """启动全部已注册 Agent，并在 runner 结束时对称清理消息订阅。"""
    registrations: list[tuple[str, asyncio.Queue, asyncio.Task]] = []
    try:
        for agent_id, agent_func in agent_map.items():
            agent_msg_queue = mcp_bus.register_agent(agent_id)
            task = asyncio.create_task(agent_func(agent_msg_queue), name=f"agent:{agent_id}")
            registrations.append((agent_id, agent_msg_queue, task))
        await asyncio.gather(*(task for _, _, task in registrations))
    finally:
        for _agent_id, _queue, task in registrations:
            if not task.done():
                task.cancel()
        if registrations:
            await asyncio.gather(
                *(task for _, _, task in registrations),
                return_exceptions=True,
            )
        for agent_id, queue, _task in registrations:
            mcp_bus.unregister_agent(agent_id, queue)
