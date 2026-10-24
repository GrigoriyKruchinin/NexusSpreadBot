import fakeredis

from nexus.domain.quarantine import QuarantineReason, RouteQuarantine
from nexus.infra.redis_store import RedisCooldownStore, RedisHeartbeat, RedisQuarantineStore
from tests.fakes import ManualClock


async def test_cooldown_is_atomic_per_key() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisCooldownStore(redis)
    assert await store.acquire("route-1", 60)
    assert not await store.acquire("route-1", 60)
    assert await store.acquire("route-2", 60)
    assert await store.acquire("route-1", 0)  # zero TTL disables the cooldown
    assert 0 < await redis.ttl("nexus:cooldown:route-1") <= 60


async def test_heartbeat_roundtrip() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    heartbeat = RedisHeartbeat(redis, ManualClock(1234))
    assert await heartbeat.last_beat_ms("scanner") is None
    await heartbeat.beat("scanner", 30)
    assert await heartbeat.last_beat_ms("scanner") == 1234
    assert 0 < await redis.ttl("nexus:heartbeat:scanner") <= 30


def _quarantine(start: int = 1_000, ttl: int = 60_000) -> RouteQuarantine:
    return RouteQuarantine(
        symbol="ZIL/USDT",
        buy_exchange="binance",
        sell_exchange="okx",
        reason=QuarantineReason.UNVERIFIED_PERSISTENT,
        started_at_ms=start,
        expires_at_ms=start + ttl,
        note="episode open 15 min",
    )


async def test_quarantine_store_add_once_list_and_lift() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisQuarantineStore(redis, ManualClock(1_000))
    quarantine = _quarantine()
    assert await store.add(quarantine)
    assert not await store.add(quarantine)  # one quarantine (and one event) per route
    assert await store.active() == {"ZIL/USDT|binance>okx": quarantine}
    ttl = await redis.pttl("nexus:quarantine:ZIL/USDT|binance>okx")
    assert 0 < ttl <= 60_000
    assert await store.lift("ZIL/USDT|binance>okx")
    assert not await store.lift("ZIL/USDT|binance>okx")
    assert await store.active() == {}


async def test_quarantine_store_skips_expired_and_malformed() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisQuarantineStore(redis, ManualClock(500_000))
    assert not await store.add(_quarantine())  # already expired by the clock
    await redis.set("nexus:quarantine:bad", "{not json")
    await redis.set("nexus:quarantine:bad2", '{"symbol": "X"}')
    assert await store.active() == {}


async def test_watchdog_state_roundtrip_and_clear() -> None:
    from nexus.infra.redis_store import RedisWatchdogState
    from nexus.interfaces.watchdog import WatchdogState

    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisWatchdogState(redis)
    assert await store.get("scanner") == WatchdogState()
    state = WatchdogState(firing=True, since_ms=123, reason="scanner_stale")
    await store.save("scanner", state)
    assert await store.get("scanner") == state
    assert await redis.ttl("nexus:watchdog:scanner") == -1  # incidents can last for days
    await store.save("scanner", WatchdogState())
    assert await redis.get("nexus:watchdog:scanner") is None


async def test_watchdog_state_ignores_garbage() -> None:
    from nexus.infra.redis_store import RedisWatchdogState
    from nexus.interfaces.watchdog import WatchdogState

    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisWatchdogState(redis)
    for raw in ("not json", "[]", '{"firing": true, "since_ms": "x", "reason": 5}'):
        await redis.set("nexus:watchdog:backup", raw)
        state = await store.get("backup")
        assert state.since_ms is None
        assert state.reason is None
    await redis.set("nexus:watchdog:backup", "not json")
    assert await store.get("backup") == WatchdogState()
