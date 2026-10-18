import fakeredis

from nexus.infra.redis_store import RedisCooldownStore, RedisHeartbeat
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
