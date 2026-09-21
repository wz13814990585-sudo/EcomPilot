"""Bounded, tenant-scoped short memory for the natural-language task console."""

from __future__ import annotations

import re
from typing import Any

from ..core.memory.short_memory import AgentShortMemory
from ..core.security import SecurityContext

_SKU = re.compile(r"\b(?:SKU[-_])?[A-Z][A-Z0-9]{1,15}[-_]\d{3}\b", re.I)
_FOLLOW_UP = re.compile(
    r"^(?:那|它|这个|这款|刚才那个|现在)?\s*"
    r"(?:多少钱|价格|售价|库存|库存怎么样|还有货吗|竞品价格|怎么样|呢|那呢)\s*(?:呢)?[？?]?$",
    re.I,
)


def _memory(session_id: str, security: SecurityContext, *, task_channel: bool) -> AgentShortMemory:
    suffix = ":tasks" if task_channel else ""
    return AgentShortMemory(
        session_id=f"{session_id}{suffix}",
        tenant_id=security.tenant_id,
        user_id=security.user_id,
    )


async def load_task_history(session_id: str, security: SecurityContext) -> list[dict[str, Any]]:
    try:
        return await _memory(session_id, security, task_channel=True).get_all()
    except Exception:
        return []


def remembered_context(query: str, history: list[dict[str, Any]]) -> dict[str, str]:
    """Resolve a short price/stock follow-up from the latest visible SKU."""
    if _SKU.search(query) or not _FOLLOW_UP.search(query.strip()):
        return {}
    for item in reversed(history):
        text = str(item.get("content") or "") if isinstance(item, dict) else ""
        match = _SKU.search(text)
        if match:
            return {"sku": match.group(0).upper()}
    return {}


async def remember_task_exchange(
    session_id: str,
    security: SecurityContext,
    *,
    query: str,
    answer: str,
) -> None:
    try:
        memory = _memory(session_id, security, task_channel=True)
        await memory.append("user", query[:2000])
        await memory.append("assistant", answer[:4000])
    except Exception:
        return


async def clear_conversation(session_id: str, security: SecurityContext) -> None:
    """Clear both general-task memory and the CRM memory sharing this session id."""
    for task_channel in (True, False):
        try:
            await _memory(session_id, security, task_channel=task_channel).clear()
        except Exception:
            continue


__all__ = [
    "clear_conversation",
    "load_task_history",
    "remember_task_exchange",
    "remembered_context",
]
