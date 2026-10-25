"""Shared builders for the hedged-transfer (HT) tests: one clean scenario passing every check."""

from dataclasses import replace
from decimal import Decimal as D

from nexus.domain.models import (
    AssetTransferInfo,
    MarketInfo,
    NetworkInfo,
    OrderBook,
    PriceLevel,
)
from nexus.domain.perp import FundingInfo, MarkKline, PerpMarket, PerpTicker
from nexus.simulation.basis import BasisBuffer
from nexus.simulation.hedged import (
    EntryRequest,
    EntryState,
    HedgedConfig,
    HedgeInputs,
    SpotLeg,
)

NOW = 1_800_000_000_000
COIN = "ABC"
SPOT = "ABC/USDT"
PERP = "ABC/USDT:USDT"
POOL = D(3000)


def levels(*pairs: tuple[str, str]) -> tuple[PriceLevel, ...]:
    return tuple(PriceLevel(D(p), D(a)) for p, a in pairs)


def book(
    exchange: str,
    symbol: str,
    bids: tuple[PriceLevel, ...],
    asks: tuple[PriceLevel, ...],
    age_ms: int = 1000,
) -> OrderBook:
    return OrderBook(exchange, symbol, bids, asks, NOW - age_ms, NOW - age_ms)


def spot_market(exchange: str, **kw: object) -> MarketInfo:
    base = MarketInfo(
        exchange=exchange,
        symbol=SPOT,
        base=COIN,
        quote="USDT",
        taker_fee=D("0.001"),
        amount_step=D("0.01"),
        min_amount=D("0.1"),
        min_cost=D(5),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def perp_market(exchange: str, **kw: object) -> PerpMarket:
    base = PerpMarket(
        exchange=exchange,
        symbol=PERP,
        base=COIN,
        contract_size=D(1),
        amount_step=D("0.01"),
        min_qty=D("0.01"),
        max_leverage=D(10),
        taker_fee=D("0.0006"),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def klines(now_ms: int = NOW, minutes: int = 1440, price: str = "100.7") -> list[MarkKline]:
    out = []
    start = now_ms - now_ms % 60_000 - (minutes - 1) * 60_000
    for i in range(minutes):
        p = D(price) + (D("0.01") if i % 2 else D(0))
        out.append(MarkKline(start + i * 60_000, p, p + D("0.02"), p - D("0.02"), p))
    return out


def basis_history(
    x_now: D, samples: int = 130, now_ms: int = NOW, step: int = 30_000
) -> BasisBuffer:
    buf = BasisBuffer()
    for i in range(samples):
        t = now_ms - (samples - 1 - i) * step
        buf.add(t, x_now + (D("0.00002") if i % 2 else D("-0.00002")))
    return buf


A_BOOK = {
    "bids": levels(("99.9", "100")),
    "asks": levels(("100.0", "30"), ("100.1", "50"), ("100.2", "100")),
}
B_BOOK = {
    "bids": levels(("101.5", "30"), ("101.4", "50"), ("101.3", "100")),
    "asks": levels(("101.6", "100")),
}
H_BOOK = {
    "bids": levels(("101.3", "20"), ("101.2", "50"), ("101.1", "100")),
    "asks": levels(("101.35", "100")),
}


def hedge_inputs(exchange: str, **kw: object) -> HedgeInputs:
    pbook = book(exchange, PERP, H_BOOK["bids"], H_BOOK["asks"])
    mid = D("101.325")
    x_now = (D("101.5") - D("101.3")) / mid
    base = HedgeInputs(
        market=perp_market(exchange),
        ticker=PerpTicker(exchange, PERP, D("101.3"), D("101.35"), D("101.32"), NOW - 10_000),
        funding=FundingInfo(
            exchange,
            PERP,
            D("0.0001"),
            NOW + 3 * 3_600_000,
            D(8),
            D("101.32"),
            D("101.3"),
            NOW - 60_000,
        ),
        book=pbook,
        klines=klines(),
        tiers_ready=True,
        mmr=D("0.025"),
        basis=basis_history(x_now),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def net(name: str, **kw: object) -> NetworkInfo:
    base = NetworkInfo(
        network=name,
        withdraw_enabled=True,
        deposit_enabled=True,
        withdraw_fee=D("0.01"),
        withdraw_min=D(1),
        deposit_min=D(1),
        deposit_confirmations=20,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def transfer_info(exchange: str, *networks: NetworkInfo) -> AssetTransferInfo:
    return AssetTransferInfo(exchange=exchange, asset=COIN, networks=networks or (net("TRC20"),))


def request(**kw: object) -> EntryRequest:
    """A -> B = okx -> kucoin, hedge candidates kucoin (B) then okx (A)."""
    a = SpotLeg(spot_market("okx"), book("okx", SPOT, A_BOOK["bids"], A_BOOK["asks"]))
    b = SpotLeg(spot_market("kucoin"), book("kucoin", SPOT, B_BOOK["bids"], B_BOOK["asks"]))
    base = EntryRequest(
        now_ms=NOW,
        coin=COIN,
        a=a,
        b=b,
        src_info=transfer_info("okx"),
        dst_info=transfer_info("kucoin"),
        src_loaded_ms=NOW - 60_000,
        dst_loaded_ms=NOW - 60_000,
        hedges={"kucoin": hedge_inputs("kucoin")},
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def state(**kw: object) -> EntryState:
    base = EntryState(
        pools={"okx": POOL, "kucoin": POOL, "binance": POOL},
        open_count=0,
        open_coins=frozenset(),
        last_fill_ms={},
        pool_target=D(3000),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def config(**kw: object) -> HedgedConfig:
    return replace(HedgedConfig(), **kw)  # type: ignore[arg-type]
