from decimal import Decimal as D

from nexus.domain.models import Ticker
from nexus.engine.candidates import CandidateFilter, CandidateFinder, RouteQuote
from tests.unit.engine.conftest import market


def _t(
    ex: str, bid: str | None, ask: str | None, vol: str | None = "1000000", sym: str = "ABC/USDT"
) -> Ticker:
    return Ticker(
        exchange=ex,
        symbol=sym,
        bid=D(bid) if bid else None,
        ask=D(ask) if ask else None,
        quote_volume_24h=D(vol) if vol else None,
        timestamp_ms=0,
    )


FINDER = CandidateFinder(
    CandidateFilter(
        min_net_profit_pct=D("0.3"), max_gross_spread_pct=D(20), min_quote_volume_usd=D(50_000)
    )
)
MARKETS = {ex: {"ABC/USDT": market(ex), "XYZ/USDT": market(ex, symbol="XYZ/USDT")} for ex in "abc"}


def test_rank_routes_both_directions_and_ordering() -> None:
    tickers = {
        "a": {"ABC/USDT": _t("a", "99", "100")},
        "b": {"ABC/USDT": _t("b", "101", "101.2")},
        "c": {"ABC/USDT": _t("c", "102", "102.5")},
    }
    routes = FINDER.rank_routes(tickers, MARKETS)
    keys = [(r.buy_exchange, r.sell_exchange) for r in routes]
    assert keys == [("a", "c"), ("a", "b"), ("b", "c")]
    best = routes[0]
    assert best.gross_spread_pct == D(2)
    assert best.fee_bound_net_pct == D("1.8")  # minus 0.1 % + 0.1 %


def test_illiquid_and_inactive_venues_excluded() -> None:
    markets = {**MARKETS, "c": {"ABC/USDT": market("c", active=False)}}
    tickers = {
        "a": {"ABC/USDT": _t("a", "99", "100")},
        "b": {"ABC/USDT": _t("b", "105", "106", vol="10")},  # illiquid
        "c": {"ABC/USDT": _t("c", "105", "106")},  # inactive market
    }
    assert FINDER.rank_routes(tickers, markets) == []


def test_unknown_volume_excluded_and_missing_market_skipped() -> None:
    tickers = {
        "a": {"ABC/USDT": _t("a", "99", "100"), "NEW/USDT": _t("a", "1", "1.1", sym="NEW/USDT")},
        "b": {"ABC/USDT": _t("b", "105", "106", vol=None)},
    }
    assert FINDER.rank_routes(tickers, MARKETS) == []


def test_select_applies_fee_bound_and_sanity_limit() -> None:
    tickers = {
        "a": {"ABC/USDT": _t("a", "99", "100"), "XYZ/USDT": _t("a", "9", "10", sym="XYZ/USDT")},
        "b": {"ABC/USDT": _t("b", "100.4", "101"), "XYZ/USDT": _t("b", "13", "14", sym="XYZ/USDT")},
        "c": {"ABC/USDT": _t("c", "100.6", "101")},
    }
    routes = FINDER.rank_routes(tickers, MARKETS)
    selected = FINDER.select(routes, limit=10)
    # XYZ gross 30 % -> suspicious, dropped; a>b 0.4-0.2=0.2 < 0.3 dropped; a>c 0.6-0.2 = 0.4 kept
    assert [(r.symbol, r.buy_exchange, r.sell_exchange) for r in selected] == [
        ("ABC/USDT", "a", "c")
    ]


def test_select_limit() -> None:
    tickers = {
        "a": {"ABC/USDT": _t("a", "99", "100")},
        "b": {"ABC/USDT": _t("b", "102", "103")},
        "c": {"ABC/USDT": _t("c", "104", "105")},
    }
    assert len(FINDER.select(FINDER.rank_routes(tickers, MARKETS), limit=1)) == 1


# ------------------------------------------------------------------ per-set cap (B15)


def _route(sym: str, buy: str, sell: str, net: str) -> RouteQuote:
    return RouteQuote(sym, buy, sell, D(1), D(2), D(net) + D("0.2"), D(net))
