"""Leak-free single-reply futures keyed by correlation identifier."""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class ReplyRegistry(Generic[T]):
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[T]] = {}

    def create(self, key: str) -> asyncio.Future[T]:
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            raise RuntimeError(f"reply already pending: {key}")
        future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        return future

    def resolve(self, key: str, value: T) -> bool:
        future = self._pending.get(key)
        if future is None or future.done():
            return False
        future.set_result(value)
        return True

    async def wait(self, key: str, timeout: float) -> T | None:
        future = self._pending.get(key)
        if future is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.discard(key)

    def discard(self, key: str) -> bool:
        future = self._pending.pop(key, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
        return True

    async def close(self) -> None:
        for key in list(self._pending):
            self.discard(key)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def contains(self, key: str) -> bool:
        return key in self._pending


__all__ = ["ReplyRegistry"]
