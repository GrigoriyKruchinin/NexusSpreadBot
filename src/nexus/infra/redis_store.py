"""Redis-backed cooldowns and heartbeats."""

from __future__ import annotations

from redis.asyncio import Redis

from nexus.domain.clock import Clock
from nexus.interfaces.coordination import ICooldownStore, IHeartbeat

_PREFIX = "nexus:"


class RedisCooldownStore(ICooldownStore):
    """``SET key NX EX ttl``: atomic across processes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def acquire(self, key: str, ttl_s: int) -> bool:
        """Return True and start the cooldown if ``key`` is not cooling down."""
        if ttl_s <= 0:
            return True
        result = await self._redis.set(f"{_PREFIX}cooldown:{key}", "1", nx=True, ex=ttl_s)
        return bool(result)

    async def release(self, key: str) -> None:
        """End a cooldown early (e.g. when the alert could not be queued)."""
        await self._redis.delete(f"{_PREFIX}cooldown:{key}")


class RedisHeartbeat(IHeartbeat):
    """Stores the last beat time with an expiry."""

    def __init__(self, redis: Redis, clock: Clock) -> None:
        self._redis = redis
        self._clock = clock

    async def beat(self, service: str, ttl_s: int) -> None:
        """Record that ``service`` is alive (expires after ``ttl_s``)."""
        await self._redis.set(f"{_PREFIX}heartbeat:{service}", str(self._clock.now_ms()), ex=ttl_s)

    async def last_beat_ms(self, service: str) -> int | None:
        """Epoch ms of the last beat, or ``None`` if expired / never."""
        value = await self._redis.get(f"{_PREFIX}heartbeat:{service}")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
