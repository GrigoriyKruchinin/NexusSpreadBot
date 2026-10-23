"""B15: shadow portfolios fed by the same stream are independent (inventory, cap, failures)."""

from decimal import Decimal as D

from nexus.simulation.portfolio import SkipReason
from tests.unit.scanner.test_scanner import Harness, _settle

ALL = frozenset({"a", "b", "c"})
AB = frozenset({"a", "b"})


def _harness(*, max_candidates: int = 10) -> Harness:
    h = Harness(
        episodes=True,
        paper=True,
        paper_sets={"all": ALL, "ab": AB},
        max_candidates=max_candidates,
    )
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")  # ~0.8 % net: a > b
    return h


def _executed(h: Harness, portfolio: str) -> list[tuple[str, str, str]]:
    return [
        (t.symbol, t.buy_exchange, t.sell_exchange)
        for t, _ in h.paper_repo.data[portfolio].trades
        if t.executed
    ]


async def test_same_stream_two_sets_have_independent_inventories() -> None:
    h = _harness()
    h.c.quote("ABC/USDT", "100.05", "101.05")
    h.a.quote("DEF/USDT", "9.9", "10")
    h.c.quote("DEF/USDT", "10.4", "10.5")  # a > c only exists in the set that has c
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    book = h.scanner._paper
    assert book is not None
    full, narrow = book.trader("all").portfolio, book.trader("ab").portfolio
    # In `all` the DEF trade used up the USDT on venue a, so ABC (a > b) is skipped there; in
    # `ab` (which never saw DEF) the very same alert executes: no state leaks between sets.
    assert _executed(h, "all") == [("DEF/USDT", "a", "c")]
    skipped = [t.skip_reason for t, _ in h.paper_repo.data["all"].trades if t.symbol == "ABC/USDT"]
    assert skipped == [SkipReason.NO_REBALANCE_PATH]
    assert _executed(h, "ab") == [("ABC/USDT", "a", "b")]
    assert not any(ex == "c" for ex, _ in narrow.balances)
    assert any(ex == "c" for ex, _ in full.balances)
    assert full.balances != narrow.balances
    assert narrow.valuation().realized != full.valuation().realized


async def test_cap_binds_in_all_but_not_in_the_narrow_set() -> None:
    h = _harness(max_candidates=1)
    h.a.quote("DEF/USDT", "9.9", "10")
    h.c.quote("DEF/USDT", "10.6", "10.7")  # bigger net spread than ABC: takes the only slot in all
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    await _settle(h)
    assert result.candidates == 2  # union of the per-set top-1 lists
    assert _executed(h, "all") == [("DEF/USDT", "a", "c")]  # ABC crowded out of the cap in all
    assert _executed(h, "ab") == [("ABC/USDT", "a", "b")]  # but it is the narrow set's top-1


async def test_a_set_only_trades_its_own_candidates() -> None:
    h = _harness(max_candidates=1)
    h.a.quote("DEF/USDT", "9.9", "10")
    h.c.quote("DEF/USDT", "10.6", "10.7")
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    # ABC was evaluated (it is ab's candidate) but all's cap is full: no ABC trade row in all
    assert not [t for t, _ in h.paper_repo.data["all"].trades if t.symbol == "ABC/USDT"]


async def test_storage_failure_in_one_set_does_not_stop_the_other() -> None:
    h = _harness()
    h.paper_repo.fail_portfolios = {"all"}
    await h.scanner.refresh_metadata()
    assert (await h.scanner.sweep()).alerts == 1
    await _settle(h)
    assert _executed(h, "ab") == [("ABC/USDT", "a", "b")]
    assert h.paper_repo.data["all"].trades == []
    book = h.scanner._paper
    assert book is not None
    assert book.trader("all").portfolio.realized == 0  # rolled back
    assert book.trader("ab").portfolio.realized > 0
    assert book.trader("ab").portfolio.realized == book.trader("ab").portfolio.valuation().realized


async def test_cooldown_and_skip_reasons_are_per_set() -> None:
    h = _harness()
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    h.b.quote("ABC/USDT", "101.6", "101.7")  # re-alert after growth
    h.clock.now += 10_000
    await h.scanner.sweep()
    await _settle(h)
    for pid in ("all", "ab"):
        reasons = [t.skip_reason for t, _ in h.paper_repo.data[pid].trades]
        assert reasons == [None, SkipReason.RECENT_FILL], pid


async def test_each_set_resumes_from_its_own_state() -> None:
    h = _harness()
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    book = h.scanner._paper
    assert book is not None
    before = {pid: t.portfolio.balances.copy() for pid, t in book.traders.items()}
    for trader in book.traders.values():
        trader.portfolio.balances.clear()
    await book.start()
    assert {pid: t.portfolio.balances for pid, t in book.traders.items()} == before
    assert book.trader("ab").portfolio.venues == AB
    assert D(0) < book.trader("ab").portfolio.valuation().capital


async def test_a_new_set_starts_fresh_without_history() -> None:
    h = _harness()
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    assert await h.paper_repo.load_state("excl_new") is None
