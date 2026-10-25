import pytest

from nexus.domain.errors import NotificationError
from nexus.notifications.rate_limit import SendRateLimiter, process_limiter
from tests.fakes import FakeClock


def _limiter(clock: FakeClock, **kwargs: float) -> SendRateLimiter:
    return SendRateLimiter(monotonic=clock.now, sleep=clock.sleep, **kwargs)  # type: ignore[arg-type]


async def test_min_interval_between_calls() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_s=1.0, max_per_minute=100)
    for _ in range(3):
        await limiter.acquire()
    assert clock.slept == [1.0, 1.0]  # the first call is immediate


async def test_twenty_per_minute_then_the_window_slides() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_s=0.0, max_per_minute=20, max_wait_s=100)
    start = clock.now()
    for _ in range(20):
        await limiter.acquire()
    assert clock.now() == start  # a burst up to the limit is not delayed
    await limiter.acquire()  # the 21st waits until the first one is 60 s old
    assert clock.now() == pytest.approx(start + 60)


async def test_far_slot_is_handed_back_to_the_task_retry() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_s=0.0, max_per_minute=2, max_wait_s=20)
    await limiter.acquire()
    await limiter.acquire()
    with pytest.raises(NotificationError) as exc_info:
        await limiter.acquire()  # next slot in 60 s > 20 s
    assert exc_info.value.retry_after_s == pytest.approx(60)
    assert clock.slept == []  # it did not sleep for it


async def test_block_for_delays_later_calls() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_s=0.0, max_per_minute=100, max_wait_s=100)
    limiter.block_for(12)
    await limiter.acquire()
    assert clock.slept == [12]


def test_process_limiter_is_shared() -> None:
    assert process_limiter(1.0, 20) is process_limiter(1.0, 20)
    assert process_limiter(1.0, 20) is not process_limiter(2.0, 20)
