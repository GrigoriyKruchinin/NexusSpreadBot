"""Redis-backed cooldowns, heartbeats and route quarantines."""

from __future__ import annotations

import json

import structlog
from redis.asyncio import Redis

from nexus.domain.clock import Clock
from nexus.domain.quarantine import QuarantineReason, RouteQuarantine
from nexus.interfaces.coordination import ICooldownStore, IHeartbeat, IQuarantineStore

log = structlog.get_logger(__name__)

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


class RedisQuarantineStore(IQuarantineStore):
    """One key per route (``SET NX PX``): expiry is enforced by Redis itself."""

    _KEY = f"{_PREFIX}quarantine:"

    def __init__(self, redis: Redis, clock: Clock) -> None:
        self._redis = redis
        self._clock = clock

    async def add(self, quarantine: RouteQuarantine) -> bool:
        """Start a quarantine unless the route already has one."""
        ttl_ms = quarantine.expires_at_ms - self._clock.now_ms()
        if ttl_ms <= 0:
            return False
        payload = json.dumps(
            {
                "symbol": quarantine.symbol,
                "buy_exchange": quarantine.buy_exchange,
                "sell_exchange": quarantine.sell_exchange,
                "reason": quarantine.reason.value,
                "started_at_ms": quarantine.started_at_ms,
                "expires_at_ms": quarantine.expires_at_ms,
                "note": quarantine.note[:300],
            }
        )
        key = f"{self._KEY}{quarantine.route_key}"
        return bool(await self._redis.set(key, payload, nx=True, px=ttl_ms))

    async def active(self) -> dict[str, RouteQuarantine]:
        """Unexpired quarantines by route key (malformed entries are dropped)."""
        keys = [key async for key in self._redis.scan_iter(match=f"{self._KEY}*", count=500)]
        if not keys:
            return {}
        result: dict[str, RouteQuarantine] = {}
        for key, raw in zip(keys, await self._redis.mget(keys), strict=True):
            if raw is None:
                continue  # expired between SCAN and MGET
            try:
                data = json.loads(raw)
                quarantine = RouteQuarantine(
                    symbol=str(data["symbol"]),
                    buy_exchange=str(data["buy_exchange"]),
                    sell_exchange=str(data["sell_exchange"]),
                    reason=QuarantineReason(data["reason"]),
                    started_at_ms=int(data["started_at_ms"]),
                    expires_at_ms=int(data["expires_at_ms"]),
                    note=str(data.get("note") or ""),
                )
            except (ValueError, KeyError, TypeError):
                log.warning("quarantine_entry_malformed", key=str(key)[:200])
                continue
            result[quarantine.route_key] = quarantine
        return result

    async def lift(self, route_key: str) -> bool:
        """End a quarantine early."""
        return bool(await self._redis.delete(f"{self._KEY}{route_key}"))
