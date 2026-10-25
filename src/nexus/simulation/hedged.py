"""Hedged-transfer (HT) entry model: config, skip reasons, pre-checks a-f, sizing (spec 5, 6).

Pure Decimal logic, no I/O and no clock reads: everything arrives in :class:`EntryRequest`.
Nothing here can place an order or move funds; legs are priced by walking recorded books.

Check order per hedge candidate H: a (perp exists) -> b (hedge openable, 6 sub-checks) -> c
(``TRANSFER_BLOCKED``) -> d (B active and deep enough, ``SELL_THIN``) -> c (``BELOW_MIN_WITHDRAW``,
``METADATA_STALE``) -> B minimums (``SELL_THIN``) -> sizing (``UNFILLABLE``) -> e (profit) -> f
(capital, limits).
The first failing check wins; across candidates the most advanced failure is reported and the
best passing candidate (max expected net, ties -> earlier in the request order) is chosen.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Final

from nexus.domain.models import (
    ZERO,
    AssetTransferInfo,
    MarketInfo,
    NetworkInfo,
    OrderBook,
    PriceLevel,
)
from nexus.domain.perp import FundingInfo, MarkKline, PerpMarket, PerpTicker
from nexus.engine.depth import buy_base, floor_to_step, sell_base
from nexus.engine.transfer import list_transfer_routes, normalize_network
from nexus.simulation.basis import BasisBuffer, BasisStats, max_rise, sigma_1m
from nexus.simulation.transit import tau_quantiles

ONE: Final = Decimal(1)
HUNDRED: Final = Decimal(100)
MINUTE_MS: Final = 60_000
HOUR_MS: Final = 3_600_000
KLINE_WINDOW_MIN: Final = 1440
DEFAULT_FUNDING_INTERVAL_H: Final = Decimal(8)
FALLBACK_PERP_FEE: Final = Decimal("0.0006")


class SkipReason(StrEnum):
    """Why an alert did not become a position (spec 5, 6; persisted)."""

    NO_PERP = "NO_PERP"
    PERP_INACTIVE = "PERP_INACTIVE"
    PERP_DATA_STALE = "PERP_DATA_STALE"
    PERP_THIN = "PERP_THIN"
    LEVERAGE = "LEVERAGE"
    FUNDING = "FUNDING"
    PERP_HISTORY_MISSING = "PERP_HISTORY_MISSING"
    LIQ_RISK = "LIQ_RISK"
    TRANSFER_BLOCKED = "TRANSFER_BLOCKED"
    BELOW_MIN_WITHDRAW = "BELOW_MIN_WITHDRAW"
    METADATA_STALE = "METADATA_STALE"
    SELL_THIN = "SELL_THIN"
    UNFILLABLE = "UNFILLABLE"
    BASIS_WARMUP = "BASIS_WARMUP"
    BASIS_OUTLIER = "BASIS_OUTLIER"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    INSUFFICIENT_USDT = "INSUFFICIENT_USDT"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    MAX_POSITIONS = "MAX_POSITIONS"
    COIN_OPEN = "COIN_OPEN"
    RECENT_FILL = "RECENT_FILL"
    STALE_BOOK = "STALE_BOOK"
    SPREAD_GONE = "SPREAD_GONE"


_CHECK_ORDER: Final[tuple[SkipReason, ...]] = tuple(SkipReason)
"""Declaration order == check order (used to pick the most advanced failure)."""


@dataclass(frozen=True, slots=True)
class HedgedConfig:
    """Pre-registered parameters (spec 13). All of them belong to the run hash (S11)."""

    capital_usd: Decimal = Decimal(10_000)
    trade_notional_usd: Decimal = Decimal(1000)
    min_trade_usd: Decimal = Decimal(100)
    leverage: Decimal = Decimal(2)
    mmr_default: Decimal = Decimal("0.025")
    liq_min_distance: Decimal = Decimal("0.30")
    liq_sigma_k: Decimal = Decimal(5)
    max_slippage: Decimal = Decimal("0.005")
    perp_taker_fee: Mapping[str, Decimal] = field(
        default_factory=lambda: {
            "binance": Decimal("0.0005"),
            "okx": Decimal("0.0005"),
            "kucoin": Decimal("0.0006"),
        }
    )
    min_net_profit_pct: Decimal = Decimal("0.3")
    min_net_profit_usd: Decimal = Decimal(3)
    max_funding_cost: Decimal = Decimal("0.003")
    funding_negative_stress: Decimal = Decimal("1.5")
    basis_z_max: Decimal = Decimal("2.5")
    basis_std_floor: Decimal = Decimal("0.0001")
    basis_min_samples: int = 60
    basis_pair_tolerance_ms: int = 15_000
    kline_min_coverage: Decimal = Decimal("0.9")
    unpriced_grace_h: int = 6
    leg_risk_reserve: Decimal = Decimal("0.0005")
    max_open_positions: int = 4
    route_cooldown_ms: int = 60_000
    max_hold_h: int = 24
    latency_ms: int = 2000
    rebalance_retry_ms: int = 30 * MINUTE_MS
    exit_slippage_mult: Decimal = Decimal(2)
    refill_threshold_usd: Decimal = Decimal(1500)
    p_stuck: float = 0.01
    stuck_h: int = 6
    max_book_age_ms: int = 5000
    max_book_skew_ms: int = 3000
    max_perp_ticker_age_ms: int = 60_000
    max_funding_age_ms: int = 15 * MINUTE_MS
    max_transfer_meta_age_ms: int = 45 * MINUTE_MS

    def perp_fee_for(self, venue: str, market: PerpMarket | None = None) -> Decimal:
        """Configured taker fee, else the market's, else a conservative fallback."""
        if venue in self.perp_taker_fee:
            return self.perp_taker_fee[venue]
        if market is not None and market.taker_fee is not None:
            return market.taker_fee
        return FALLBACK_PERP_FEE


@dataclass(frozen=True, slots=True)
class SpotLeg:
    """Spot market and its post-latency book."""

    market: MarketInfo
    book: OrderBook


@dataclass(frozen=True, slots=True)
class HedgeInputs:
    """Everything known about one hedge candidate H (``None`` = not available)."""

    market: PerpMarket | None
    ticker: PerpTicker | None
    funding: FundingInfo | None
    book: OrderBook | None
    klines: Sequence[MarkKline] = ()
    tiers_ready: bool = True
    """False when the venue publishes tiers (okx, kucoin) but they are not loaded (age <= 1 h)."""
    mmr: Decimal | None = None
    """Effective maintenance margin rate (tier table); default applies when ``None``."""
    basis: BasisBuffer | None = None


@dataclass(frozen=True, slots=True)
class EntryState:
    """Portfolio facts the checks need (read-only snapshot)."""

    pools: Mapping[str, Decimal]
    open_count: int
    open_coins: frozenset[str]
    last_fill_ms: Mapping[tuple[str, str, str], int]
    """``(coin, A, B)`` -> time of the last entry on that route."""
    pool_target: Decimal


@dataclass(frozen=True, slots=True)
class EntryRequest:
    """One alert evaluated on post-latency books."""

    now_ms: int
    coin: str
    a: SpotLeg
    b: SpotLeg
    src_info: AssetTransferInfo | None
    dst_info: AssetTransferInfo | None
    src_loaded_ms: int | None
    dst_loaded_ms: int | None
    hedges: Mapping[str, HedgeInputs]
    """Candidates in preference order (B first, then A, then others)."""
    usdt_fee_usd: Decimal = ONE


@dataclass(frozen=True, slots=True)
class EntryPlan:
    """A priced, sized, accepted entry (all amounts in base units / USDT)."""

    hedge_venue: str
    network: str
    withdraw_fee: Decimal
    q_buy: Decimal
    q: Decimal
    """Coin amount sold on B (after base-side fee and withdrawal fee, floored to B's step)."""
    q_h: Decimal
    cost: Decimal
    a_vwap: Decimal
    b0: Decimal
    f0: Decimal
    phi_a: Decimal
    phi_b: Decimal
    phi_h: Decimal
    margin: Decimal
    entry_fee: Decimal
    p_liq: Decimal
    mmr: Decimal
    leg_reserve: Decimal
    rb_reserve: Decimal
    tau_p50_min: Decimal
    tau_p95_min: Decimal
    s_usd: Decimal
    e_net: Decimal
    p_net: Decimal
    funding_rate: Decimal
    funding_interval_h: Decimal
    next_funding_ms: int | None
    mark: Decimal
    perp_lot_base: Decimal
    """Smallest perp size in base units (exit rounding)."""
    deposit_confirmations: int | None
    est_arrival_min: Decimal | None


@dataclass(frozen=True, slots=True)
class EntryDecision:
    """Either a plan or a skip reason (never both)."""

    plan: EntryPlan | None = None
    reason: SkipReason | None = None
    detail: str = ""
    hedge_venue: str = ""

    @property
    def accepted(self) -> bool:
        """True when a position may be opened."""
        return self.plan is not None


class _FailError(Exception):
    """Internal: a check failed (never escapes :func:`evaluate_entry`)."""

    def __init__(self, reason: SkipReason, detail: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.detail = detail


# ------------------------------------------------------------------ helpers


def _need(value: Decimal | None) -> Decimal:
    """A price/fee that must exist; a missing one means the book or metadata is unusable."""
    if value is None:
        raise _FailError(SkipReason.STALE_BOOK, "missing book side or fee")
    return value


def depth_within(
    levels: Sequence[PriceLevel], reference: Decimal, slip: Decimal, *, buy: bool
) -> Decimal:
    """Base amount on ``levels`` priced within ``slip`` of ``reference`` (ask side if ``buy``)."""
    limit = reference * (ONE + slip) if buy else reference * (ONE - slip)
    total = ZERO
    for level in levels:
        price = level.price
        if (buy and price > limit) or (not buy and price < limit):
            break
        total += level.amount
    return total


def funding_events(
    start_ms: int, end_ms: int, next_funding_ms: int | None, interval_h: Decimal | None
) -> int:
    """Number of funding times in ``[start, end]``.

    Without a known next funding time the count is ``ceil(window / interval)`` (pessimistic).
    """
    interval_ms = int((interval_h or DEFAULT_FUNDING_INTERVAL_H) * HOUR_MS)
    if end_ms < start_ms:
        return 0
    if next_funding_ms is None:
        return math.ceil((end_ms - start_ms) / interval_ms)
    first = next_funding_ms
    if first < start_ms:
        first += -(-(start_ms - first) // interval_ms) * interval_ms
    return 0 if first > end_ms else (end_ms - first) // interval_ms + 1


def funding_cost_fraction(rate: Decimal, events: int, stress: Decimal) -> Decimal:
    """Expected funding paid by the short as a fraction of notional (income counted as 0)."""
    return max(ZERO, -rate) * stress * events


def kline_coverage(klines: Sequence[MarkKline], now_ms: int) -> Decimal:
    """Share of the last 1,440 one-minute candles that exist."""
    start = now_ms - KLINE_WINDOW_MIN * MINUTE_MS
    minutes = {k.open_ms // MINUTE_MS for k in klines if start <= k.open_ms <= now_ms}
    return Decimal(len(minutes)) / KLINE_WINDOW_MIN


def liq_price(f0: Decimal, leverage: Decimal, mmr: Decimal) -> Decimal:
    """Conservative linear-short liquidation price ``f0 * (1 + 1/L - mmr)``."""
    return f0 * (ONE + ONE / leverage - mmr)


# ------------------------------------------------------------------ evaluation


def evaluate_entry(cfg: HedgedConfig, req: EntryRequest, state: EntryState) -> EntryDecision:
    """Run the pre-checks for every hedge candidate and pick the best passing one."""
    best: EntryDecision | None = None
    worst: tuple[int, EntryDecision] | None = None
    for venue, hedge in req.hedges.items():
        try:
            plan = _evaluate_candidate(cfg, req, state, venue, hedge)
        except _FailError as fail:
            rank = _CHECK_ORDER.index(fail.reason)
            decision = EntryDecision(reason=fail.reason, detail=fail.detail, hedge_venue=venue)
            if worst is None or rank > worst[0]:
                worst = (rank, decision)
            continue
        if best is None or best.plan is None or plan.e_net > best.plan.e_net:
            best = EntryDecision(plan=plan, hedge_venue=venue)
    if best is not None:
        return best
    if worst is None:
        return EntryDecision(reason=SkipReason.NO_PERP, detail="no hedge candidates")
    return worst[1]


def _evaluate_candidate(
    cfg: HedgedConfig, req: EntryRequest, state: EntryState, venue: str, hedge: HedgeInputs
) -> EntryPlan:
    # (a) perp exists and is tradable
    market, ticker, funding, pbook = _check_a(req, hedge)
    ask_a = req.a.book.best_ask
    bid_b = req.b.book.best_bid
    bid_h, ask_h = pbook.best_bid, pbook.best_ask
    if ask_a is None or bid_b is None or bid_h is None or ask_h is None:
        raise _FailError(SkipReason.STALE_BOOK, "empty book side")
    phi_h = cfg.perp_fee_for(venue, market)
    mmr = hedge.mmr if hedge.mmr is not None else cfg.mmr_default
    mark = funding.mark_price or ticker.mark or (bid_h + ask_h) / 2
    q_min = cfg.min_trade_usd / ask_a  # smallest acceptable trade, in coin

    routes = _routes(cfg, req)  # unsorted candidates, may be empty
    tau_ref = _tau_for_checks(req, routes)

    # (b) hedge openable
    _check_b(
        cfg, req, hedge, market, ticker, funding, pbook, q_min, mmr, tau_ref[1], now=req.now_ms
    )

    # (c) transfer, (d) sellable, sizing
    plan = _choose_route_and_size(
        cfg, req, state, venue, routes, market, funding, pbook, mark, phi_h, mmr
    )
    # (e) profit, (f) capital and limits
    return _check_e(cfg, req, state, hedge, plan, pbook, funding, mark)


def _check_a(
    req: EntryRequest, hedge: HedgeInputs
) -> tuple[PerpMarket, PerpTicker, FundingInfo, OrderBook]:
    market = hedge.market
    if market is None:
        raise _FailError(SkipReason.NO_PERP)
    if not market.active or market.delisting:
        raise _FailError(
            SkipReason.PERP_INACTIVE, "delisting" if market.delisting else "not trading"
        )
    if market.base != req.coin:
        raise _FailError(SkipReason.NO_PERP, "perp base differs from spot base")
    if hedge.ticker is None or hedge.funding is None or hedge.book is None:
        raise _FailError(SkipReason.PERP_DATA_STALE, "ticker, funding or book missing")
    return market, hedge.ticker, hedge.funding, hedge.book


def _routes(cfg: HedgedConfig, req: EntryRequest) -> list[tuple[str, NetworkInfo, NetworkInfo]]:
    del cfg
    return [
        (code, out, into)
        for code, out, into in list_transfer_routes(req.src_info, req.dst_info)
        if out.busy is not True and into.busy is not True
    ]


def _tau_for_checks(
    req: EntryRequest, routes: list[tuple[str, NetworkInfo, NetworkInfo]]
) -> tuple[Decimal, Decimal]:
    """``(p50, p95)`` of the cheapest route (unknown confirmations when there is none)."""
    if routes:
        code, _, into = routes[0]  # list_transfer_routes is sorted by fee
        return tau_quantiles(
            req.a.market.exchange,
            req.b.market.exchange,
            code,
            into.deposit_confirmations,
            into.est_arrival_min,
        )
    return tau_quantiles(req.a.market.exchange, req.b.market.exchange, "", None)


def _check_b(
    cfg: HedgedConfig,
    req: EntryRequest,
    hedge: HedgeInputs,
    market: PerpMarket,
    ticker: PerpTicker,
    funding: FundingInfo,
    pbook: OrderBook,
    q_min: Decimal,
    mmr: Decimal,
    tau_p95_min: Decimal,
    *,
    now: int,
) -> None:
    if (
        now - ticker.received_at_ms > cfg.max_perp_ticker_age_ms
        or now - funding.received_at_ms > cfg.max_funding_age_ms
    ):
        raise _FailError(SkipReason.PERP_DATA_STALE, "perp ticker or funding too old")
    bid_h = _need(pbook.best_bid)
    if depth_within(pbook.bids, bid_h, cfg.max_slippage, buy=False) < q_min:
        raise _FailError(SkipReason.PERP_THIN, "perp bids within slippage below the minimum trade")
    if market.max_leverage is not None and market.max_leverage < cfg.leverage:
        raise _FailError(SkipReason.LEVERAGE, f"max leverage {market.max_leverage}")
    interval = funding.interval_h
    events = funding_events(
        req.now_ms,
        req.now_ms + int(tau_p95_min * MINUTE_MS),
        funding.next_funding_ms,
        interval,
    )
    pess = funding_cost_fraction(funding.rate, events, cfg.funding_negative_stress)
    if pess > cfg.max_funding_cost:
        raise _FailError(SkipReason.FUNDING, f"pessimistic funding {pess}")
    if kline_coverage(hedge.klines, req.now_ms) < cfg.kline_min_coverage or not hedge.tiers_ready:
        raise _FailError(SkipReason.PERP_HISTORY_MISSING, "klines coverage or tiers")
    sigma = sigma_1m(hedge.klines)
    rise = max_rise(hedge.klines, math.ceil(tau_p95_min))
    if sigma is None or rise is None:
        raise _FailError(SkipReason.PERP_HISTORY_MISSING, "no usable klines")
    need = max(
        cfg.liq_min_distance,
        cfg.liq_sigma_k * sigma * tau_p95_min.sqrt(),
        Decimal("1.5") * rise,
    )
    if ONE / cfg.leverage - mmr < need:
        raise _FailError(SkipReason.LIQ_RISK, f"distance {ONE / cfg.leverage - mmr} < {need}")


def _choose_route_and_size(
    cfg: HedgedConfig,
    req: EntryRequest,
    state: EntryState,
    venue: str,
    routes: list[tuple[str, NetworkInfo, NetworkInfo]],
    market: PerpMarket,
    funding: FundingInfo,
    pbook: OrderBook,
    mark: Decimal,
    phi_h: Decimal,
    mmr: Decimal,
) -> EntryPlan:
    # (c) transfer
    if not routes:
        raise _FailError(SkipReason.TRANSFER_BLOCKED, "no verified open shared network")
    # (d) sellable on B: market active and bids within slippage absorb the minimum trade. Runs
    # before the per-route minimum checks so a thin B book is not reported as a size problem.
    if not req.b.market.active:
        raise _FailError(SkipReason.SELL_THIN, "B market inactive")
    ask_ref = _need(req.a.book.best_ask)
    bid_ref = _need(req.b.book.best_bid)
    if depth_within(req.b.book.bids, bid_ref, cfg.max_slippage, buy=False) < (
        cfg.min_trade_usd / ask_ref
    ):
        raise _FailError(SkipReason.SELL_THIN, "B bids within slippage below the minimum trade")
    options: list[
        tuple[Decimal, str, _Sized, tuple[Decimal, Decimal], NetworkInfo, NetworkInfo]
    ] = []
    below_min = False
    for code, out, into in routes:
        fee = _need(out.withdraw_fee)
        sized = _size(cfg, req, state, venue, fee, market, pbook, phi_h, pools=False)
        if sized is None:
            continue
        if (out.withdraw_min is not None and sized.q_buy < out.withdraw_min) or (
            into.deposit_min is not None and sized.q < into.deposit_min
        ):
            below_min = True
            continue
        tau = tau_quantiles(
            req.a.market.exchange,
            req.b.market.exchange,
            code,
            into.deposit_confirmations,
            into.est_arrival_min,
        )
        events = funding_events(
            req.now_ms,
            req.now_ms + int(tau[0] * MINUTE_MS),
            funding.next_funding_ms,
            funding.interval_h,
        )
        f_cost = (
            funding_cost_fraction(funding.rate, events, cfg.funding_negative_stress)
            * sized.q_h
            * mark
        )
        ask_a = _need(req.a.book.best_ask)
        options.append((fee * ask_a + f_cost, code, sized, tau, out, into))
    if not options:
        if below_min:
            raise _FailError(SkipReason.BELOW_MIN_WITHDRAW, "size below min withdraw/deposit")
        raise _FailError(SkipReason.UNFILLABLE, "sizing failed on every network")
    old = _stale_meta(cfg, req)
    if old:
        raise _FailError(SkipReason.METADATA_STALE, old)
    options.sort(key=lambda o: (o[0], o[1]))
    _, code, sized, tau, out, into = options[0]
    # (d) B minimum amount/cost (the depth and active checks ran above)
    bid_b = _need(req.b.book.best_bid)
    if not _meets_min(req.b.market, sized.q, sized.q * bid_b):
        raise _FailError(SkipReason.SELL_THIN, "B minimum amount/cost not met")
    # sizing with pools (f is reported after e; use the pool-cut size when it is tradable)
    pooled = _size(
        cfg, req, state, venue, _need(out.withdraw_fee), market, pbook, phi_h, pools=True
    )
    final = pooled if pooled is not None and pooled.cost >= cfg.min_trade_usd else sized
    if final.cost < cfg.min_trade_usd:
        raise _FailError(SkipReason.UNFILLABLE, "below the minimum trade")
    return _build_plan(
        cfg, req, state, venue, code, out, into, market, final, tau, funding, mark, phi_h, mmr
    )


def _stale_meta(cfg: HedgedConfig, req: EntryRequest) -> str:
    for label, loaded in (("A", req.src_loaded_ms), ("B", req.dst_loaded_ms)):
        if loaded is None or req.now_ms - loaded > cfg.max_transfer_meta_age_ms:
            return f"transfer metadata of {label} older than the limit"
    return ""


@dataclass(frozen=True, slots=True)
class _Sized:
    q_buy: Decimal
    q: Decimal
    q_h: Decimal
    cost: Decimal
    a_vwap: Decimal
    b0: Decimal
    f0: Decimal


def _meets_min(market: MarketInfo, amount: Decimal, cost: Decimal) -> bool:
    if market.min_amount is not None and amount < market.min_amount:
        return False
    return not (market.min_cost is not None and cost < market.min_cost)


def _size(
    cfg: HedgedConfig,
    req: EntryRequest,
    state: EntryState,
    venue: str,
    w: Decimal,
    market: PerpMarket,
    pbook: OrderBook,
    phi_h: Decimal,
    *,
    pools: bool,
) -> _Sized | None:
    """Equal-leg size from depth, notional and (optionally) pools; ``None`` when untradable."""
    a_book, b_book = req.a.book, req.b.book
    ask0, bid_b, bid_h = _need(a_book.best_ask), _need(b_book.best_bid), _need(pbook.best_bid)
    phi_a = req.a.market.taker_fee
    slip = cfg.max_slippage
    caps = [
        cfg.trade_notional_usd / ask0,
        depth_within(a_book.asks, ask0, slip, buy=True) * (ONE - phi_a) - w,
        depth_within(b_book.bids, bid_b, slip, buy=False),
        depth_within(pbook.bids, bid_h, slip, buy=False),
    ]
    if pools:
        a_pool = state.pools.get(req.a.market.exchange, ZERO)
        h_pool = state.pools.get(venue, ZERO)
        worst_ask = ask0 * (ONE + slip)
        per_coin_a = worst_ask * (ONE + cfg.leg_risk_reserve + req.usdt_fee_usd / state.pool_target)
        per_coin_h = bid_h * (ONE / cfg.leverage + phi_h)
        if venue == req.a.market.exchange:
            caps.append(a_pool / (per_coin_a + per_coin_h))
        else:
            caps.extend([a_pool / per_coin_a, h_pool / per_coin_h])
    q_cap = min(caps)
    if q_cap <= ZERO:
        return None
    q_buy = floor_to_step((q_cap + w) / (ONE - phi_a), req.a.market.amount_step)
    q = floor_to_step(q_buy * (ONE - phi_a) - w, req.b.market.amount_step)
    q_h_contracts = floor_to_step(q / market.contract_size, market.amount_step)
    q_h = q_h_contracts * market.contract_size
    if q <= ZERO or q_h <= ZERO or q_h_contracts < market.min_qty:
        return None
    buy = buy_base(a_book.asks, q_buy)
    sell_b = sell_base(b_book.bids, q)
    sell_h = sell_base(pbook.bids, q_h)
    if buy is None or sell_b is None or sell_h is None:
        return None
    if not _meets_min(req.a.market, q_buy, buy.quote_amount):
        return None
    return _Sized(q_buy, q, q_h, buy.quote_amount, buy.vwap, sell_b.vwap, sell_h.vwap)


def _build_plan(
    cfg: HedgedConfig,
    req: EntryRequest,
    state: EntryState,
    venue: str,
    code: str,
    out: NetworkInfo,
    into: NetworkInfo,
    market: PerpMarket,
    sized: _Sized,
    tau: tuple[Decimal, Decimal],
    funding: FundingInfo,
    mark: Decimal,
    phi_h: Decimal,
    mmr: Decimal,
) -> EntryPlan:
    phi_a, phi_b = req.a.market.taker_fee, req.b.market.taker_fee
    f0 = sized.f0
    return EntryPlan(
        hedge_venue=venue,
        network=normalize_network(code),
        withdraw_fee=_need(out.withdraw_fee),
        q_buy=sized.q_buy,
        q=sized.q,
        q_h=sized.q_h,
        cost=sized.cost,
        a_vwap=sized.a_vwap,
        b0=sized.b0,
        f0=f0,
        phi_a=phi_a,
        phi_b=phi_b,
        phi_h=phi_h,
        margin=sized.q_h * f0 / cfg.leverage,
        entry_fee=phi_h * sized.q_h * f0,
        p_liq=liq_price(f0, cfg.leverage, mmr),
        mmr=mmr,
        leg_reserve=cfg.leg_risk_reserve * sized.cost,
        rb_reserve=req.usdt_fee_usd * sized.cost / state.pool_target,
        tau_p50_min=tau[0],
        tau_p95_min=tau[1],
        s_usd=sized.q * sized.b0 * (ONE - phi_b) - sized.cost,
        e_net=ZERO,
        p_net=ZERO,
        funding_rate=funding.rate,
        funding_interval_h=funding.interval_h or DEFAULT_FUNDING_INTERVAL_H,
        next_funding_ms=funding.next_funding_ms,
        mark=mark,
        perp_lot_base=market.lot_base,
        deposit_confirmations=into.deposit_confirmations,
        est_arrival_min=into.est_arrival_min,
    )


def _check_e(
    cfg: HedgedConfig,
    req: EntryRequest,
    state: EntryState,
    hedge: HedgeInputs,
    p: EntryPlan,
    pbook: OrderBook,
    funding: FundingInfo,
    mark: Decimal,
) -> EntryPlan:
    bid_h, ask_h = _need(pbook.best_bid), _need(pbook.best_ask)
    bid_b = _need(req.b.book.best_bid)
    mid_h = (bid_h + ask_h) / 2
    lag_ms = int(p.tau_p50_min * MINUTE_MS)
    stats = (
        hedge.basis.stats(
            req.now_ms,
            lag_ms,
            min_samples=cfg.basis_min_samples,
            pair_tolerance_ms=cfg.basis_pair_tolerance_ms,
        )
        if hedge.basis is not None
        else None
    )
    if stats is None or stats.warmup:
        raise _FailError(SkipReason.BASIS_WARMUP, _warmup_detail(stats))
    x_now = (bid_b - bid_h) / mid_h
    z = stats.zscore(x_now, cfg.basis_std_floor)
    if abs(z) > cfg.basis_z_max:
        raise _FailError(SkipReason.BASIS_OUTLIER, f"z={z}")
    p_exp = 2 * p.phi_h * p.q_h * p.f0 + p.q_h * (ask_h - bid_h)
    ev50 = funding_events(
        req.now_ms, req.now_ms + lag_ms, funding.next_funding_ms, funding.interval_h
    )
    ev95 = funding_events(
        req.now_ms,
        req.now_ms + int(p.tau_p95_min * MINUTE_MS),
        funding.next_funding_ms,
        funding.interval_h,
    )
    notional_h = p.q_h * mark
    f_exp = funding_cost_fraction(funding.rate, ev50, cfg.funding_negative_stress) * notional_h
    f_pess = funding_cost_fraction(funding.rate, ev95, cfg.funding_negative_stress) * notional_h
    e_r = p.q_h * mid_h * (stats.median - x_now)
    sigma_r = p.q_h * mid_h * (stats.lag_std or ZERO)
    common = p.s_usd - p_exp + min(ZERO, e_r) - p.leg_reserve - p.rb_reserve
    e_net = common - f_exp
    p_net = common - f_pess - sigma_r
    threshold = max(cfg.min_net_profit_pct / HUNDRED * p.cost, cfg.min_net_profit_usd)
    if e_net < threshold or p_net < ZERO:
        raise _FailError(
            SkipReason.BELOW_THRESHOLD, f"E_net={e_net} P_net={p_net} need {threshold}"
        )
    plan = replace(p, e_net=e_net, p_net=p_net)
    _check_f(cfg, req, state, plan)
    return plan


def _warmup_detail(stats: BasisStats | None) -> str:
    if stats is None:
        return "no basis samples"
    return f"samples={stats.samples} pairs={stats.pairs}"


def _check_f(cfg: HedgedConfig, req: EntryRequest, state: EntryState, plan: EntryPlan) -> None:
    a_ex, b_ex = req.a.market.exchange, req.b.market.exchange
    venue = plan.hedge_venue
    a_pool = state.pools.get(a_ex, ZERO)
    h_pool = state.pools.get(venue, ZERO)
    outflow_a = plan.cost + plan.leg_reserve + plan.rb_reserve
    margin_need = plan.margin + plan.entry_fee
    if venue == a_ex:
        if a_pool < outflow_a:
            raise _FailError(SkipReason.INSUFFICIENT_USDT, "A pool below cost")
        if a_pool < outflow_a + margin_need:
            raise _FailError(SkipReason.INSUFFICIENT_MARGIN, "shared pool below cost + margin")
    else:
        if a_pool < outflow_a:
            raise _FailError(SkipReason.INSUFFICIENT_USDT, "A pool below cost")
        if h_pool < margin_need:
            raise _FailError(SkipReason.INSUFFICIENT_MARGIN, "hedge pool below margin + fee")
    if state.open_count >= cfg.max_open_positions:
        raise _FailError(SkipReason.MAX_POSITIONS)
    if req.coin in state.open_coins:
        raise _FailError(SkipReason.COIN_OPEN)
    last = state.last_fill_ms.get((req.coin, a_ex, b_ex))
    if last is not None and req.now_ms - last < cfg.route_cooldown_ms:
        raise _FailError(SkipReason.RECENT_FILL)
    _check_books(cfg, req, venue)
    if plan.s_usd <= ZERO:
        raise _FailError(SkipReason.SPREAD_GONE, "locked spread not positive")


def _check_books(cfg: HedgedConfig, req: EntryRequest, venue: str) -> None:
    hedge_book = req.hedges[venue].book
    if hedge_book is None:
        raise _FailError(SkipReason.STALE_BOOK, "hedge book missing")
    books = (req.a.book, req.b.book, hedge_book)
    if any(book.age_ms(req.now_ms) > cfg.max_book_age_ms for book in books):
        raise _FailError(SkipReason.STALE_BOOK, "book older than the limit")
    stamps = [book.timestamp_ms for book in books]
    if max(stamps) - min(stamps) > cfg.max_book_skew_ms:
        raise _FailError(SkipReason.STALE_BOOK, "book skew above the limit")
