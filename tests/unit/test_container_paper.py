"""B15: the container builds one equal-capital shadow portfolio per venue set."""

from decimal import Decimal as D
from typing import Any

import pytest

from nexus.config import ScannerRoleSettings
from nexus.container import build_paper_book
from tests.fakes import ManualClock


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> ScannerRoleSettings:
    monkeypatch.setenv("POSTGRES_PASSWORD", "x" * 16)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return ScannerRoleSettings.load()


def test_every_set_gets_the_same_fixed_capital(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, PAPER_VENUE_SETS="all;excl_conditional;ex=-gateio")
    book = build_paper_book(settings, None, ManualClock())  # type: ignore[arg-type]
    assert book is not None
    assert list(book.traders) == ["all", "excl_conditional", "ex"]
    for trader in book.traders.values():
        config = trader.portfolio.config
        assert trader.venues is not None
        assert config.coin_budget_per_venue_usd is not None
        deployed_at_most = len(trader.venues) * (
            config.usdt_per_exchange + config.coin_budget_per_venue_usd
        )
        # PAPER_CAPITAL_USD default, whatever the set size (Decimal division dust only)
        assert abs(deployed_at_most - D(10_000)) < D("1e-20")


def test_capital_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, PAPER_CAPITAL_USD="5000", PAPER_USDT_SHARE_PCT="40")
    book = build_paper_book(settings, None, ManualClock())  # type: ignore[arg-type]
    assert book is not None
    config = book.trader("all").portfolio.config
    assert config.usdt_per_exchange == D(5000) / 5 * D("0.4")


def test_paper_disabled_builds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, PAPER_ENABLED="false")
    sessions: Any = None
    assert build_paper_book(settings, sessions, ManualClock()) is None


def test_default_sets_are_all_and_excl_conditional(monkeypatch: pytest.MonkeyPatch) -> None:
    book = build_paper_book(_settings(monkeypatch), None, ManualClock())  # type: ignore[arg-type]
    assert book is not None
    assert list(book.traders) == ["all", "excl_conditional"]
    assert book.trader("excl_conditional").venues == frozenset({"binance", "kucoin", "okx"})
    assert book.members("binance", "okx") == ["all", "excl_conditional"]
    assert book.members("binance", "bybit") == ["all"]


@pytest.mark.parametrize(
    "env",
    [
        {"SPREAD_MIN_NET_PROFIT_PCT": "0.9"},
        {"SPREAD_DEFAULT_TAKER_FEE_PCT": "0.1"},
        {"SPREAD_ALERT_COOLDOWN_S": "60"},
        {"SCANNER_MAX_CANDIDATES_PER_SWEEP": "60"},
        {"PAPER_LATENCY_MS": "100"},
    ],
)
def test_strategy_settings_change_the_run_hash(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    base = build_paper_book(_settings(monkeypatch), None, ManualClock())  # type: ignore[arg-type]
    other = build_paper_book(_settings(monkeypatch, **env), None, ManualClock())  # type: ignore[arg-type]
    assert base is not None
    assert other is not None
    assert (
        base.trader("all").definition().config_hash != other.trader("all").definition().config_hash
    )
