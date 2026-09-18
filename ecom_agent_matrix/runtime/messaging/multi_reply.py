"""Explicit collector for the uncommon fan-in case."""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class MultiReplyCollector(Generic[T]):
    def __init__(self, expected: int) -> None:
        if expected < 1:
            raise ValueError("expected must be positive")
        self.expected = expected
        self._values: list[T] = []
        self._event = asyncio.Event()

    def add(self, value: T) -> bool:
        if self._event.is_set():
            return False
        self._values.append(value)
        if len(self._values) >= self.expected:
            self._event.set()
        return True

    async def wait(self, timeout: float) -> list[T]:
        try:
            await asyncio.wait_for(self._event.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        return list(self._values)


__all__ = ["MultiReplyCollector"]
