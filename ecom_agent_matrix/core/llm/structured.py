"""Validated structured-output boundary with bounded parsing repair."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ecom_agent_matrix.core.llm.router import llm_chat
from ecom_agent_matrix.core.llm.types import ChatResult

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredChatResult(Generic[T]):
    value: T
    response: ChatResult


def _json_object(text: str) -> dict:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    elif not raw.startswith("{"):
        candidate = re.search(r"\{.*\}", raw, re.DOTALL)
        if candidate:
            raw = candidate.group(0)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("structured output must be a JSON object")
    return value


async def llm_chat_structured(
    *,
    response_model: type[T],
    defaults: dict | None = None,
    repair_attempts: int = 0,
    **chat_kwargs,
) -> StructuredChatResult[T]:
    """One logical interface; repair is explicitly bounded to at most one call."""
    attempts = min(max(int(repair_attempts), 0), 1)
    response = await llm_chat(**chat_kwargs)
    for attempt in range(attempts + 1):
        try:
            payload = {**_json_object(response.content), **(defaults or {})}
            return StructuredChatResult(response_model.model_validate(payload), response)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            if attempt >= attempts:
                raise
            response = await llm_chat(
                user_prompt=(
                    "Return only one JSON object matching this JSON schema:\n"
                    f"{json.dumps(response_model.model_json_schema())}\n"
                    f"Invalid prior output:\n{response.content[:2000]}"
                ),
                system_prompt="Repair invalid structured output. Return JSON only.",
                temperature=0,
                max_tokens=chat_kwargs.get("max_tokens", 512),
                mode=chat_kwargs.get("mode"),
            )
    raise AssertionError("unreachable")


__all__ = ["StructuredChatResult", "llm_chat_structured"]
