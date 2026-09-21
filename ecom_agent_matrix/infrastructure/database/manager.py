"""Instance-owned database lifecycle over the existing aiopg adapter."""

from __future__ import annotations

from ...db.base import (
    AsyncPGClient,
    validate_database_runtime_roles,
    validate_database_security_configuration,
)


class DatabaseManager:
    def __init__(self, settings) -> None:
        self.settings = settings

    async def start(self) -> None:
        validate_database_security_configuration(self.settings)
        await validate_database_runtime_roles(self.settings)

    async def close(self) -> None:
        await AsyncPGClient.close()

    execute_read = AsyncPGClient.execute_read
    execute_write = AsyncPGClient.execute_write
    execute_system = AsyncPGClient.execute_system
    execute_health = AsyncPGClient.execute_health
    execute_metadata = AsyncPGClient.execute_metadata


__all__ = ["DatabaseManager"]
