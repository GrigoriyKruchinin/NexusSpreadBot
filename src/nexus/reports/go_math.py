"""GO report math (pure): windows, equity, P&L split, stability and concentration inputs.

No database, no clock, no I/O: the DB query layer (:mod:`nexus.reports.go_repository`) builds
:class:`SetData` and everything here is a function of it. Spec:
``docs/quant/b15-review-and-report-spec.md`` Part B (B1-B7) and the Round 2 amendments.
All money is ``Decimal``; times are epoch milliseconds (UTC).
"""

from __future__ import annotations

import itertools
import statistics
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from nexus.simulation.portfolio import CONVERSION_NETWORK, USD_QUOTE

ZERO = Decimal(0)
HUNDRED = Decimal(100)
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
DAYS_PER_MONTH = Decimal("30.4375")
"""Average month length used for monthly scaling (spec B3)."""
GO_BAR_PCT = Decimal(2)
"""GO bar: net return per month on fixed capital, after income tax."""
TAX_RATES = (Decimal("0.15"), Decimal("0.35"))
GO_TAX_RATE = Decimal("0.35")
"""The GO verdict is judged on the worse rate (user decision 2026-10-23)."""
MIN_TUNING_DAYS = 7
MIN_HOLDOUT_DAYS = 14
MIN_PERIOD_DAYS = 7
MAX_PERIODS = 4
MIN_PERIODS = 2
RUN_START_TRIM_MS = 10 * 60_000
"""Rows in the first 10 minutes after a run that replaced another one are dropped (N13)."""
DEFAULT_LIQ_COST_PCT = Decimal("0.3")
"""Exit cost of non-USDT inventory (taker fee + half spread), flat; same as the paper conversion
cost (N11). Tickers are not stored, so the venue-specific value cannot be rebuilt (disclosed)."""
TOP_N = 2


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True, slots=True)
class HoldingPoint:
    """One (venue, asset) balance inside a snapshot set."""

    exchange: str
    asset: str
    amount: Decimal
    price: Decimal | None
    """USD price at snapshot time (``None`` = unpriced; USDT is always 1)."""
    seeded_value: Decimal
    """Seed amount x seed price (0 when the balance is not a seeded slot)."""


@dataclass(frozen=True, slots=True)
class SnapshotSet:
    """All holdings of one portfolio at one instant."""

    at_ms: int
    holdings: tuple[HoldingPoint, ...]


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """An executed paper trade."""

    at_ms: int
    symbol: str
    base: str
    buy_exchange: str
    sell_exchange: str
    net_usd: Decimal
    notional_usd: Decimal
    """Quote spent on the buy leg."""

    @property
    def route(self) -> str:
        """Route key ``symbol|buy>sell``."""
        return f"{self.symbol}|{self.buy_exchange}>{self.sell_exchange}"


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """A trade that was not executed."""

    at_ms: int
    reason: str


@dataclass(frozen=True, slots=True)
class RebalanceRecord:
    """A virtual transfer or an idle-slot conversion."""

    started_ms: int
    arrives_ms: int
    asset: str
    from_exchange: str
    to_exchange: str
    amount: Decimal
    fee: Decimal
    fee_usd: Decimal
    network: str | None
    status: str

    @property
    def is_conversion(self) -> bool:
        """Idle coin slot sold back to USDT (``network = 'conversion'``)."""
        return self.network == CONVERSION_NETWORK

    @property
    def is_blocked(self) -> bool:
        """A transfer that was refused (never costs anything)."""
        return self.status == "blocked"


@dataclass(frozen=True, slots=True)
class CapHour:
    """Hourly cap/heartbeat counters of a set (``paper_cap_stats``)."""

    hour_ms: int
    sweeps: int
    sweeps_cap_bound: int
    dropped_routes: int
    alerts_cap_excluded: int


@dataclass(frozen=True, slots=True)
class RunInfo:
    """One run of a set from the registry."""

    run_id: int
    started_ms: int
    venues: tuple[str, ...]
    capital_usd: Decimal
    config_hash: str


@dataclass(frozen=True, slots=True)
class SetData:
    """Everything the report reads for one set (rows of its latest run only)."""

    name: str
    run: RunInfo
    previous_runs: tuple[RunInfo, ...] = ()
    snapshots: tuple[SnapshotSet, ...] = ()
    trades: tuple[TradeRecord, ...] = ()
    skips: tuple[SkipRecord, ...] = ()
    rebalances: tuple[RebalanceRecord, ...] = ()
    caps: tuple[CapHour, ...] = ()

    @property
    def capital(self) -> Decimal:
        """Fixed capital of the run."""
        return self.run.capital_usd

    @property
    def window_start_ms(self) -> int:
        """First instant that counts: the run start, trimmed after a replaced run (N13)."""
        trim = RUN_START_TRIM_MS if self.previous_runs else 0
        return self.run.started_ms + trim


# --------------------------------------------------------------------------- formulas


def after_tax(total: Decimal, rate: Decimal | None) -> Decimal:
    """Income tax on a window total: a gain is taxed, a loss is NOT refunded (spec B3)."""
    if rate is None:
        return total
    return total - rate * max(total, ZERO)


def window_days(a_ms: int, b_ms: int) -> Decimal:
    """Length of ``[a, b)`` in (fractional) days; never negative."""
    return Decimal(max(b_ms - a_ms, 0)) / Decimal(DAY_MS)


def per_month(amount: Decimal, days: Decimal) -> Decimal:
    """Scale a window amount to a 30.4375-day month (0 for an empty window)."""
    return amount * DAYS_PER_MONTH / days if days > ZERO else ZERO


def pct_per_month(amount: Decimal, days: Decimal, capital: Decimal) -> Decimal:
    """Monthly return in percent of the fixed capital."""
    return per_month(amount, days) / capital * HUNDRED if capital > ZERO else ZERO


# --------------------------------------------------------------------------- equity


def snapshot_at(snapshots: Sequence[SnapshotSet], at_ms: int) -> SnapshotSet | None:
    """Last snapshot set at or before ``at_ms`` (``snapshots`` sorted by time)."""
    index = bisect_right([s.at_ms for s in snapshots], at_ms)
    return snapshots[index - 1] if index else None


def holding_price(holding: HoldingPoint) -> Decimal:
    """USD price of one unit (USDT = 1, unpriced = 0)."""
    if holding.asset == USD_QUOTE:
        return Decimal(1)
    return holding.price if holding.price is not None else ZERO


def _asset_prices(snap: SnapshotSet) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {USD_QUOTE: Decimal(1)}
    for h in snap.holdings:
        if h.asset not in prices and h.price is not None:
            prices[h.asset] = h.price
    return prices


@dataclass(frozen=True, slots=True)
class Valuation:
    """Portfolio value at one instant (USD)."""

    equity: Decimal
    """Holdings + in-flight transfers + unseeded capital (cash)."""
    non_usdt: Decimal
    """Value of non-USDT inventory (held + in flight): what a liquidation would sell."""
    seeded: Decimal
    unseeded_coin: Decimal
    """Non-USDT holdings that are not a seeded slot (stranded coin, N10)."""


def valuation_at(data: SetData, at_ms: int) -> Valuation:
    """Equity at ``at_ms`` from the last snapshot (spec B3).

    Capital that was never seeded counts as USDT cash, so equity starts exactly at the fixed
    capital. Transfers in flight AT THE SNAPSHOT (started, not yet arrived then, not blocked) are
    added at the snapshot price of their asset: the snapshot already deducted them at the source,
    and a late arrival commit must not make the funds vanish. Without a snapshot the portfolio
    is untouched capital.
    """
    snap = snapshot_at(data.snapshots, at_ms)
    if snap is None:
        return Valuation(data.capital, ZERO, ZERO, ZERO)
    prices = _asset_prices(snap)
    held = ZERO
    non_usdt = ZERO
    seeded = ZERO
    stranded = ZERO
    for h in snap.holdings:
        value = h.amount * holding_price(h)
        held += value
        seeded += h.seeded_value
        if h.asset != USD_QUOTE:
            non_usdt += value
            if h.seeded_value == ZERO:
                stranded += value
    for r in data.rebalances:
        if r.is_blocked or r.is_conversion or not r.started_ms <= snap.at_ms < r.arrives_ms:
            continue
        value = (r.amount - r.fee) * prices.get(r.asset, ZERO)
        held += value
        if r.asset != USD_QUOTE:
            non_usdt += value
    return Valuation(held + data.capital - seeded, non_usdt, seeded, stranded)


def daily_times(a_ms: int, b_ms: int) -> list[int]:
    """Sample instants of the daily equity curve: start, each UTC midnight inside, end."""
    times = [a_ms]
    midnight = (a_ms // DAY_MS + 1) * DAY_MS
    while midnight < b_ms:
        times.append(midnight)
        midnight += DAY_MS
    if b_ms > a_ms:
        times.append(b_ms)
    return times


def max_drawdown_pct(equities: Sequence[Decimal], capital: Decimal) -> Decimal:
    """Largest peak-to-trough fall of the equity curve, in percent of the fixed capital."""
    if capital <= ZERO or not equities:
        return ZERO
    peak = equities[0]
    worst = ZERO
    for equity in equities:
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst / capital * HUNDRED


def _time_weighted(points: list[tuple[int, Decimal]], a_ms: int, b_ms: int) -> Decimal:
    """Average of a step function ``points`` (sorted ``(from_ms, value)``) over ``[a, b)``."""
    if b_ms <= a_ms:
        return ZERO
    current = ZERO
    index = 0
    while index < len(points) and points[index][0] <= a_ms:
        current = points[index][1]
        index += 1
    total = ZERO
    cursor = a_ms
    while index < len(points) and points[index][0] < b_ms:
        at, value = points[index]
        total += current * (at - cursor)
        cursor, current = at, value
        index += 1
    total += current * (b_ms - cursor)
    return total / (b_ms - a_ms)


def coin_mtm(data: SetData, a_ms: int, b_ms: int) -> dict[str, Decimal]:
    """Price effect per coin on the inventory held, summed over snapshot intervals.

    ``qty(t_i) x (price(t_{i+1}) - price(t_i))`` between consecutive snapshot instants inside
    ``[a, b]``: an approximation at snapshot granularity (hourly, daily for old data), used only
    for the ex-top-2-coins recompute. In-flight quantities are ignored (small, short).
    """
    inside = [s.at_ms for s in data.snapshots if a_ms < s.at_ms < b_ms]
    times = [a_ms, *inside, b_ms]
    result: dict[str, Decimal] = {}
    for start, end in itertools.pairwise(times):
        first, last = snapshot_at(data.snapshots, start), snapshot_at(data.snapshots, end)
        if first is None:
            continue
        prices_end = _asset_prices(last) if last is not None else {}
        prices_start = _asset_prices(first)
        quantities: dict[str, Decimal] = {}
        for h in first.holdings:
            if h.asset != USD_QUOTE:
                quantities[h.asset] = quantities.get(h.asset, ZERO) + h.amount
        for asset, qty in quantities.items():
            p0 = prices_start.get(asset)
            p1 = prices_end.get(asset, p0)
            if p0 is not None and p1 is not None:
                result[asset] = result.get(asset, ZERO) + qty * (p1 - p0)
    return result


# --------------------------------------------------------------------------- window stats


@dataclass(frozen=True, slots=True)
class WindowStats:
    """Spec B3/B4 numbers of one set over ``[a, b)``."""

    a_ms: int
    b_ms: int
    days: Decimal
    capital: Decimal
    trades_executed: int
    skips: tuple[tuple[str, int], ...]
    """``(skip_reason, count)`` sorted by reason."""
    avg_notional_usd: Decimal | None
    realized: Decimal
    rebal_transfer: Decimal
    rebal_conversion: Decimal
    conversions_count: int
    rebalances_blocked: int
    hedged: Decimal
    mtm: Decimal
    liq_cost: Decimal
    """Exit cost of the non-USDT inventory held at the window end (subtracted from the headline)."""
    total: Decimal
    total_liq: Decimal
    equity_start: Decimal
    equity_end: Decimal
    deployed_avg: Decimal
    idle_avg: Decimal
    mtm_share: Decimal | None
    max_drawdown_pct: Decimal
    daily_pnl_std_pct: Decimal
    sweeps: int
    sweeps_cap_bound: int
    dropped_routes: int
    alerts_cap_excluded: int
    unseeded_coin_value_usd: Decimal
    gap_hours: int
    window_hours: int
    gap_days: tuple[str, ...]

    @property
    def rebal_costs(self) -> Decimal:
        """Transfer + conversion fees."""
        return self.rebal_transfer + self.rebal_conversion

    @property
    def skipped_total(self) -> int:
        """All skipped attempts."""
        return sum(n for _, n in self.skips)

    @property
    def mtm_dominated(self) -> bool:
        """MTM is more than half of the result's magnitude (flag, N5)."""
        return self.mtm_share is not None and self.mtm_share > Decimal("0.5")

    @property
    def cap_bound_pct(self) -> Decimal | None:
        """Share of sweeps in which the set's top-N cap cut a route (``None`` = no sweeps)."""
        if self.sweeps == 0:
            return None
        return Decimal(self.sweeps_cap_bound) / Decimal(self.sweeps) * HUNDRED

    @property
    def exhausted_share(self) -> Decimal:
        """``coin_budget_exhausted`` / (executed + all skips) (spec B7.4)."""
        attempts = self.trades_executed + self.skipped_total
        if attempts == 0:
            return ZERO
        exhausted = dict(self.skips).get("coin_budget_exhausted", 0)
        return Decimal(exhausted) / Decimal(attempts)

    @property
    def gap_share(self) -> Decimal:
        """Hours without any sweep / hours in the window."""
        return Decimal(self.gap_hours) / Decimal(self.window_hours) if self.window_hours else ZERO

    def net_usd_month(self, rate: Decimal | None) -> Decimal:
        """Net USD per month on the liquidation-adjusted total, after tax at ``rate``."""
        return per_month(after_tax(self.total_liq, rate), self.days)

    def net_pct_month(self, rate: Decimal | None) -> Decimal:
        """Net % of fixed capital per month (the GO headline at ``GO_TAX_RATE``)."""
        return pct_per_month(after_tax(self.total_liq, rate), self.days, self.capital)


def _gaps(caps: Sequence[CapHour], a_ms: int, b_ms: int) -> tuple[int, int, tuple[str, ...]]:
    """Whole UTC hours of ``[a, b)`` without a sweep (per-set heartbeat, N12)."""
    first = -(-a_ms // HOUR_MS) * HOUR_MS
    last = (b_ms // HOUR_MS) * HOUR_MS
    present = {c.hour_ms for c in caps if c.sweeps > 0}
    hours = list(range(first, last, HOUR_MS))
    missing = [h for h in hours if h not in present]
    days = sorted({_day_label(h) for h in missing})
    return len(missing), len(hours), tuple(days)


def _day_label(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def window_stats(data: SetData, a_ms: int, b_ms: int, liq_cost_pct: Decimal) -> WindowStats:
    """Compute every per-window number of spec B3/B4 for ``[a, b)``."""
    capital = data.capital
    days = window_days(a_ms, b_ms)
    trades = [t for t in data.trades if a_ms <= t.at_ms < b_ms]
    realized = sum((t.net_usd for t in trades), ZERO)
    rebals = [r for r in data.rebalances if a_ms <= r.started_ms < b_ms]
    paid = [r for r in rebals if not r.is_blocked]
    conversion = sum((r.fee_usd for r in paid if r.is_conversion), ZERO)
    transfer = sum((r.fee_usd for r in paid if not r.is_conversion), ZERO)
    rebal = conversion + transfer
    start, end = valuation_at(data, a_ms), valuation_at(data, b_ms)
    total = end.equity - start.equity
    # spec B3: the window starts as if in cash and ends with a liquidation of what it holds
    liq_cost = end.non_usdt * liq_cost_pct / HUNDRED
    mtm = total - realized + rebal
    spread_part = abs(realized - rebal)
    magnitude = spread_part + abs(mtm)
    skip_counts: dict[str, int] = {}
    for s in data.skips:
        if a_ms <= s.at_ms < b_ms:
            skip_counts[s.reason] = skip_counts.get(s.reason, 0) + 1
    curve = [valuation_at(data, t).equity for t in daily_times(a_ms, b_ms)]
    steps = [curve[i + 1] - curve[i] for i in range(len(curve) - 1)]
    std = (
        statistics.stdev(step / capital * HUNDRED for step in steps)
        if len(steps) >= 2 and capital > ZERO
        else ZERO
    )
    seeded_points = [
        (s.at_ms, sum((h.seeded_value for h in s.holdings), ZERO)) for s in data.snapshots
    ]
    deployed = _time_weighted(seeded_points, a_ms, b_ms)
    caps = [c for c in data.caps if a_ms - HOUR_MS < c.hour_ms < b_ms]
    gap_hours, window_hours, gap_days = _gaps(data.caps, a_ms, b_ms)
    return WindowStats(
        a_ms=a_ms,
        b_ms=b_ms,
        days=days,
        capital=capital,
        trades_executed=len(trades),
        skips=tuple(sorted(skip_counts.items())),
        avg_notional_usd=(
            sum((t.notional_usd for t in trades), ZERO) / len(trades) if trades else None
        ),
        realized=realized,
        rebal_transfer=transfer,
        rebal_conversion=conversion,
        conversions_count=sum(1 for r in paid if r.is_conversion),
        rebalances_blocked=sum(1 for r in rebals if r.is_blocked),
        hedged=realized - rebal,
        mtm=mtm,
        liq_cost=liq_cost,
        total=total,
        total_liq=total - liq_cost,
        equity_start=start.equity,
        equity_end=end.equity,
        deployed_avg=deployed,
        idle_avg=capital - deployed,
        mtm_share=abs(mtm) / magnitude if magnitude > ZERO else None,
        max_drawdown_pct=max_drawdown_pct(curve, capital),
        daily_pnl_std_pct=std,
        sweeps=sum(c.sweeps for c in caps),
        sweeps_cap_bound=sum(c.sweeps_cap_bound for c in caps),
        dropped_routes=sum(c.dropped_routes for c in caps),
        alerts_cap_excluded=sum(c.alerts_cap_excluded for c in caps),
        unseeded_coin_value_usd=end.unseeded_coin,
        gap_hours=gap_hours,
        window_hours=window_hours,
        gap_days=gap_days,
    )


# --------------------------------------------------------------------------- windows (B2, B5)


@dataclass(frozen=True, slots=True)
class WindowSplit:
    """Chronological tuning / holdout split of one window (no shuffling)."""

    start_ms: int
    end_ms: int
    tuning_end_ms: int
    holdout_days: Decimal
    periods: tuple[tuple[int, int], ...]
    """Equal consecutive periods of the holdout (``k >= 2``), empty when insufficient."""

    @property
    def total_days(self) -> Decimal:
        """Window length in days."""
        return window_days(self.start_ms, self.end_ms)

    @property
    def sufficient(self) -> bool:
        """Holdout >= 14 days and at least two stability periods."""
        return self.holdout_days >= MIN_HOLDOUT_DAYS and len(self.periods) >= MIN_PERIODS

    @property
    def days_missing(self) -> Decimal:
        """Days of data still needed until the holdout reaches its 14-day minimum."""
        return max(Decimal(MIN_HOLDOUT_DAYS) - self.holdout_days, ZERO)


def split_window(start_ms: int, end_ms: int) -> WindowSplit:
    """Tuning = first third (min 7 days), holdout = rest (needs >= 14 days); spec B2/B5.

    The tuning end and the period edges are rounded up to UTC midnights: equity at a boundary
    is the last snapshot before it, which is the end-of-day state at midnight (a mid-day edge
    would be stale by up to the snapshot spacing and distort single periods).
    """
    total = max(end_ms - start_ms, 0)
    tuning = max(total // 3, MIN_TUNING_DAYS * DAY_MS)
    tuning_end = min(-(-(start_ms + tuning) // DAY_MS) * DAY_MS, end_ms)
    holdout_ms = max(end_ms - tuning_end, 0)
    k = min(MAX_PERIODS, holdout_ms // (MIN_PERIOD_DAYS * DAY_MS))
    periods: tuple[tuple[int, int], ...] = ()
    if holdout_ms >= MIN_HOLDOUT_DAYS * DAY_MS and k >= MIN_PERIODS:
        days = holdout_ms // DAY_MS
        edges = [tuning_end + days * i // k * DAY_MS for i in range(k)] + [end_ms]
        periods = tuple(itertools.pairwise(edges))
    return WindowSplit(
        start_ms=start_ms,
        end_ms=end_ms,
        tuning_end_ms=tuning_end,
        holdout_days=Decimal(holdout_ms) / Decimal(DAY_MS),
        periods=periods,
    )


# --------------------------------------------------------------------------- concentration (B6)


@dataclass(frozen=True, slots=True)
class Concentration:
    """Route and coin concentration on one window (holdout when available)."""

    route_net: tuple[tuple[str, Decimal], ...]
    """``(route, realized - attributed rebal)`` sorted descending."""
    coin_net: tuple[tuple[str, Decimal], ...]
    unattributed_rebal: Decimal
    top1_route_share: Decimal
    top2_route_share: Decimal
    top1_coin_share: Decimal
    top2_coin_share: Decimal
    hhi_routes: Decimal
    top_routes: tuple[str, ...]
    top_coins: tuple[str, ...]
    total_liq_ex_routes: Decimal
    """Window ``total_liq`` without the top-2 routes (their realized and attributed rebal)."""
    total_liq_ex_coins: Decimal
    """Window ``total_liq`` without the top-2 coins (realized, attributed rebal and MTM)."""
    mtm_of_top_coins: Decimal
    days: Decimal
    capital: Decimal

    def pct_ex_routes(self, rate: Decimal | None) -> Decimal:
        """Monthly % after tax without the top-2 routes."""
        return pct_per_month(after_tax(self.total_liq_ex_routes, rate), self.days, self.capital)

    def pct_ex_coins(self, rate: Decimal | None) -> Decimal:
        """Monthly % after tax without the top-2 coins."""
        return pct_per_month(after_tax(self.total_liq_ex_coins, rate), self.days, self.capital)


def _attribute_rebalances(
    trades: Sequence[TradeRecord], rebals: Sequence[RebalanceRecord]
) -> tuple[dict[str, Decimal], Decimal]:
    """Rebalance cost per route: by asset and destination venue, pro rata to trade notional.

    * conversion of coin X on venue V -> routes trading X that SELL on V;
    * transfer of coin X to venue V   -> routes trading X that sell on V (else any route of X);
    * transfer of USDT to venue V     -> routes that BUY on V.
    A cost that matches no trade stays unattributed (it is never removed by the ex-top-2 test).
    """
    per_route: dict[str, Decimal] = {}
    unattributed = ZERO
    for r in rebals:
        if r.is_blocked:
            continue
        if r.asset == USD_QUOTE:
            targets = [t for t in trades if t.buy_exchange == r.to_exchange]
        else:
            venue = r.from_exchange if r.is_conversion else r.to_exchange
            targets = [t for t in trades if t.base == r.asset and t.sell_exchange == venue]
            targets = targets or [t for t in trades if t.base == r.asset]
        if not targets:
            unattributed += r.fee_usd
            continue
        weight = sum((t.notional_usd for t in targets), ZERO)
        for t in targets:
            share = t.notional_usd / weight if weight > ZERO else Decimal(1) / len(targets)
            per_route[t.route] = per_route.get(t.route, ZERO) + r.fee_usd * share
    return per_route, unattributed


def _ranked(values: dict[str, Decimal]) -> list[tuple[str, Decimal]]:
    return sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))


def _shares(ranked: Sequence[tuple[str, Decimal]]) -> tuple[Decimal, Decimal, Decimal]:
    positive = sum((v for _, v in ranked if v > ZERO), ZERO)
    if positive <= ZERO:
        return ZERO, ZERO, ZERO
    parts = [max(v, ZERO) / positive for _, v in ranked]
    top1 = parts[0] if parts else ZERO
    top2 = sum(parts[:TOP_N], ZERO)
    return top1, top2, sum((p * p for p in parts), ZERO)


def concentration(data: SetData, a_ms: int, b_ms: int, liq_cost_pct: Decimal) -> Concentration:
    """Route/coin concentration and the strict ex-top-2 recomputes on ``[a, b)`` (spec B6).

    Top-2 is ranked on this window's ``realized - attributed rebal`` (positive entries only);
    the caller passes the holdout, so no ranking ever uses tuning data.
    """
    stats = window_stats(data, a_ms, b_ms, liq_cost_pct)
    trades = [t for t in data.trades if a_ms <= t.at_ms < b_ms]
    rebals = [r for r in data.rebalances if a_ms <= r.started_ms < b_ms]
    attributed, unattributed = _attribute_rebalances(trades, rebals)
    routes: dict[str, Decimal] = {}
    coins: dict[str, Decimal] = {}
    base_of = {t.route: t.base for t in trades}
    for t in trades:
        routes[t.route] = routes.get(t.route, ZERO) + t.net_usd
    for route, cost in attributed.items():
        routes[route] = routes.get(route, ZERO) - cost
    for route, net in routes.items():
        coins[base_of[route]] = coins.get(base_of[route], ZERO) + net
    ranked_routes, ranked_coins = _ranked(routes), _ranked(coins)
    top_routes = tuple(k for k, v in ranked_routes[:TOP_N] if v > ZERO)
    top_coins = tuple(k for k, v in ranked_coins[:TOP_N] if v > ZERO)
    mtm = coin_mtm(data, a_ms, b_ms)
    mtm_top = sum((mtm.get(c, ZERO) for c in top_coins), ZERO)
    r1, r2, hhi = _shares(ranked_routes)
    c1, c2, _ = _shares(ranked_coins)
    return Concentration(
        route_net=tuple(ranked_routes),
        coin_net=tuple(ranked_coins),
        unattributed_rebal=unattributed,
        top1_route_share=r1,
        top2_route_share=r2,
        top1_coin_share=c1,
        top2_coin_share=c2,
        hhi_routes=hhi,
        top_routes=top_routes,
        top_coins=top_coins,
        total_liq_ex_routes=stats.total_liq - sum((routes[k] for k in top_routes), ZERO),
        total_liq_ex_coins=(stats.total_liq - sum((coins[k] for k in top_coins), ZERO) - mtm_top),
        mtm_of_top_coins=mtm_top,
        days=stats.days,
        capital=stats.capital,
    )


# --------------------------------------------------------------------------- set analysis


@dataclass(frozen=True, slots=True)
class PeriodResult:
    """One stability period of the holdout."""

    a_ms: int
    b_ms: int
    stats: WindowStats


@dataclass(frozen=True, slots=True)
class SetAnalysis:
    """All numbers of one set (rate-independent); verdict logic reads this."""

    name: str
    data: SetData
    start_ms: int
    until_ms: int
    split: WindowSplit
    full: WindowStats
    tuning: WindowStats | None
    holdout: WindowStats | None
    periods: tuple[PeriodResult, ...]
    focus: WindowStats
    """Holdout when sufficient, else the full window (preview, in-sample)."""
    concentration: Concentration
    """Computed on the focus window."""
    focus_is_holdout: bool = field(default=False)

    @property
    def conversion_cost_share(self) -> Decimal | None:
        """Conversion fees / all rebalance costs on the focus window (N11)."""
        costs = self.focus.rebal_costs
        return self.focus.rebal_conversion / costs if costs > ZERO else None


def analyze_set(data: SetData, until_ms: int, liq_cost_pct: Decimal) -> SetAnalysis:
    """Windows, split, per-window stats, stability periods and concentration of one set."""
    start = data.window_start_ms
    split = split_window(start, until_ms)
    full = window_stats(data, start, until_ms, liq_cost_pct)
    tuning = holdout = None
    periods: tuple[PeriodResult, ...] = ()
    if split.sufficient:
        tuning = window_stats(data, start, split.tuning_end_ms, liq_cost_pct)
        holdout = window_stats(data, split.tuning_end_ms, until_ms, liq_cost_pct)
        periods = tuple(
            PeriodResult(a, b, window_stats(data, a, b, liq_cost_pct)) for a, b in split.periods
        )
    focus = holdout or full
    return SetAnalysis(
        name=data.name,
        data=data,
        start_ms=start,
        until_ms=until_ms,
        split=split,
        full=full,
        tuning=tuning,
        holdout=holdout,
        periods=periods,
        focus=focus,
        concentration=concentration(data, focus.a_ms, focus.b_ms, liq_cost_pct),
        focus_is_holdout=holdout is not None,
    )


@dataclass(frozen=True, slots=True)
class CommonWindow:
    """Comparison of sets on the window they all have (spec B1)."""

    start_ms: int
    until_ms: int
    basis: str
    """``holdout`` when the common window is long enough, else ``preview`` (in-sample)."""
    rows: tuple[tuple[str, WindowStats], ...]


def common_window(
    datas: Sequence[SetData], until_ms: int, liq_cost_pct: Decimal
) -> CommonWindow | None:
    """Stats of every set over ``[max(since), until)`` (holdout of it when long enough)."""
    if not datas:
        return None
    start = max(d.window_start_ms for d in datas)
    split = split_window(start, until_ms)
    a = split.tuning_end_ms if split.sufficient else start
    rows = tuple((d.name, window_stats(d, a, until_ms, liq_cost_pct)) for d in datas)
    return CommonWindow(a, until_ms, "holdout" if split.sufficient else "preview", rows)
