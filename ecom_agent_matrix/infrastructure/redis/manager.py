from ...db.redis_client import AsyncRedisClient


class RedisManager:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        await AsyncRedisClient.close()


__all__ = ["RedisManager"]
