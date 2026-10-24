"""Paper inventory, trades and **virtual** rebalancing.

Pure Decimal model without I/O. Nothing here can move funds: rebalancing is a bookkeeping
simulation that charges the real (metadata) withdrawal fee and locks the amount for a delay.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum

from nexus.domain.models import ZERO
from nexus.domain.spread import SpreadBreakdown, TransferQuote, TransferStatus

HUNDRED = Decimal(100)
USD_QUOTE = "USDT"
"""Quote asset of the paper inventory. Accepted simplification: every USD stablecoin quote
(USDT/USDC) is booked as USDT 1:1 - depeg and cross-stable conversion costs are ignored."""

CONVERSION_NETWORK = "conversion"
"""``network`` marker of a bookkeeping conversion of an idle coin slot back to USDT."""

DEFAULT_PORTFOLIO_ID = "all"
"""The primary shadow portfolio (every enabled venue); rows written before B15 belong to it."""

Venue = tuple[str, str]
"""``(exchange, asset)``."""


class SkipReason(StrEnum):
    """Why a paper trade was not executed."""

    INSUFFICIENT_USDT = "insufficient_usdt"
    INSUFFICIENT_COIN = "insufficient_coin"
    REBALANCE_IN_FLIGHT = "rebalance_in_flight"
    NO_REBALANCE_PATH = "no_rebalance_path"
    SPREAD_GONE = "spread_gone"
    """Not profitable any more on the books taken after the latency."""
    BOOKS_UNAVAILABLE = "books_unavailable"
    UNFILLABLE = "unfillable"
    """The estimator rejected the books (stale, too thin, below exchange minimums, ...)."""
    NO_PRICE = "no_price"
    """The coin has no usable market price yet, so its inventory cannot be seeded."""
    RECENT_FILL = "recent_fill"
    """The route was paper-traded moments ago: the same book depth is not captured twice."""
    COIN_BUDGET_EXHAUSTED = "coin_budget_exhausted"
    """The sell venue's coin budget is fully seeded and no idle coin slot could be released:
    not a real inventory shortage but a limit of the simulation (reported separately)."""


class RebalanceStatus(StrEnum):
    """Lifecycle of a virtual transfer."""

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PaperConfig:
    """Simulation parameters (see ``PaperSettings``)."""

    usdt_per_exchange: Decimal
    coin_per_route_usd: Decimal
    rebalance_threshold_pct: Decimal
    rebalance_delay_ms: int
    blocked_retry_ms: int = 30 * 60_000
    """A rebalance without a verified network is retried after this long."""
    trade_notional_usd: Decimal = Decimal(1_000)
    """Target trade size; trades shrink to the available inventory."""
    min_trade_fraction: Decimal = Decimal("0.1")
    """Trades smaller than this fraction of the target size are skipped (no inventory)."""
    transfer_tax_pct: Mapping[str, Decimal] = field(default_factory=dict)
    """On-chain transfer tax per asset (percent of the amount moved after the fee)."""
    coin_budget_per_venue_usd: Decimal | None = None
    """Fixed cap of the coin inventory seeded on one venue (``None`` = unlimited, legacy)."""
    coin_idle_release_ms: int | None = 24 * 3_600_000
    """A coin slot idle at least this long is freed (converted back to USDT) when a new coin
    needs the venue's budget; ``None`` = never (slots stay forever, first-come lock-in)."""
    conversion_cost_pct: Decimal = Decimal("0.3")
    """Estimated cost of converting an idle coin back to USDT (taker fee + half the spread)."""

    def __post_init__(self) -> None:
        if self.usdt_per_exchange <= ZERO or self.coin_per_route_usd <= ZERO:
            msg = "seed amounts must be positive"
            raise ValueError(msg)
        if not ZERO < self.rebalance_threshold_pct < HUNDRED:
            msg = "rebalance_threshold_pct must be within (0, 100)"
            raise ValueError(msg)
        if self.rebalance_delay_ms < 0:
            msg = "rebalance_delay_ms must not be negative"
            raise ValueError(msg)
        if self.coin_idle_release_ms is not None and self.coin_idle_release_ms <= 0:
            msg = "coin_idle_release_ms must be positive (or None)"
            raise ValueError(msg)
        if not ZERO <= self.conversion_cost_pct < HUNDRED:
            msg = "conversion_cost_pct must be within [0, 100)"
            raise ValueError(msg)


def allocate_capital(
    capital_usd: Decimal, venue_count: int, usdt_share_pct: Decimal
) -> tuple[Decimal, Decimal]:
    """Split the fixed set capital equally over the venues: ``(usdt, coin_budget)`` per venue.

    ``venue_count * (usdt + coin_budget) == capital_usd``, so every set (whatever its size)
    deploys the same total capital at most.
    """
    if venue_count < 2:
        msg = "a venue set needs at least 2 venues"
        raise ValueError(msg)
    if not ZERO < usdt_share_pct < HUNDRED:
        msg = "usdt share must be within (0, 100) percent"
        raise ValueError(msg)
    per_venue = capital_usd / venue_count
    usdt = per_venue * usdt_share_pct / HUNDRED
    return usdt, per_venue - usdt


@dataclass(frozen=True, slots=True)
class Seed:
    """Starting inventory of one venue (counted as capital at ``price``)."""

    amount: Decimal
    price: Decimal


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    """Result of one simulated trade."""

    symbol: str
    base: str
    buy_exchange: str
    sell_exchange: str
    at_ms: int
    skip_reason: SkipReason | None
    breakdown: SpreadBreakdown | None = None

    @property
    def executed(self) -> bool:
        """True when balances changed."""
        return self.skip_reason is None

    @property
    def net_usd(self) -> Decimal:
        """Realized arbitrage profit of the trade (zero when skipped)."""
        return self.breakdown.net_profit_usd if self.executed and self.breakdown else ZERO


@dataclass(frozen=True, slots=True)
class Rebalance:
    """A virtual transfer of ``amount`` of ``asset`` (fee deducted on arrival)."""

    asset: str
    from_exchange: str
    to_exchange: str
    amount: Decimal
    fee: Decimal
    fee_usd: Decimal
    network: str | None
    started_at_ms: int
    arrives_at_ms: int
    status: RebalanceStatus
    note: str = ""
    id: int | None = None

    @property
    def received(self) -> Decimal:
        """Amount credited at the destination."""
        return self.amount - self.fee


@dataclass(frozen=True, slots=True)
class RebalanceNeed:
    """A balance below the threshold and the venue that can refill it."""

    asset: str
    from_exchange: str
    to_exchange: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class Valuation:
    """Portfolio value split (USD)."""

    capital: Decimal
    """Seeded inventory valued at seed prices."""
    equity: Decimal
    """Current holdings (including in-flight transfers) at current prices."""
    realized: Decimal
    rebalance_costs: Decimal

    @property
    def total_pnl(self) -> Decimal:
        """Equity minus capital."""
        return self.equity - self.capital

    @property
    def mark_to_market(self) -> Decimal:
        """Price effect on held inventory (and lot dust): total minus trading and rebalancing."""
        return self.total_pnl - self.realized + self.rebalance_costs

    @property
    def return_on_capital_pct(self) -> Decimal:
        """Total P&L over capital, in percent."""
        return self.total_pnl / self.capital * HUNDRED if self.capital > ZERO else ZERO


@dataclass(slots=True)
class PaperPortfolio:
    """Balances per (exchange, asset), seeds, in-flight transfers and running totals."""

    config: PaperConfig
    balances: dict[Venue, Decimal] = field(default_factory=dict)
    seeds: dict[Venue, Seed] = field(default_factory=dict)
    in_flight: list[Rebalance] = field(default_factory=list)
    prices: dict[str, Decimal] = field(default_factory=dict)
    realized: Decimal = ZERO
    rebalance_costs: Decimal = ZERO
    blocked: dict[Venue, int] = field(default_factory=dict)
    """Destination venues whose last rebalance had no verified network -> blocked-at ms."""
    venues: frozenset[str] | None = None
    """The venue set this portfolio may touch (``None`` = unrestricted, legacy/tests)."""
    last_used_ms: dict[Venue, int] = field(default_factory=dict)
    """Last time a coin slot was seeded or traded (idle detection; not persisted - after a
    restart every slot gets a fresh idle window)."""
    conversions: list[Rebalance] = field(default_factory=list)
    """Idle-slot conversions made since the last :meth:`drain_conversions` (to be persisted)."""

    def _require_in_set(self, *exchanges: str) -> None:
        if self.venues is None:
            return
        for exchange in exchanges:
            if exchange not in self.venues:
                msg = f"venue {exchange!r} is not in this portfolio's venue set"
                raise ValueError(msg)

    # ------------------------------------------------------------------ prices & seeding

    def mark_price(self, asset: str, price: Decimal) -> None:
        """Latest USD price of ``asset`` (used for seeding, rebalance fees and valuation)."""
        if price > ZERO:
            self.prices[asset] = price

    def ensure_seeded(
        self, buy_exchange: str, sell_exchange: str, base: str, now_ms: int = 0
    ) -> bool:
        """Seed USDT on both venues and the coin on the sell venue on first use.

        Returns False when the coin has no price yet (cannot be seeded). When the sell venue's
        coin budget is used up, a slot idle for ``coin_idle_release_ms`` is freed first
        (``now_ms`` required); if none is free the coin stays unseeded and the trade skips
        with ``COIN_BUDGET_EXHAUSTED``.
        """
        self._require_in_set(buy_exchange, sell_exchange)
        for exchange in (buy_exchange, sell_exchange):
            self._seed((exchange, USD_QUOTE), self.config.usdt_per_exchange, Decimal(1))
        if (sell_exchange, base) in self.seeds:
            return True
        price = self.prices.get(base)
        if price is None:
            return False
        usd = self._coin_seed_usd(sell_exchange)
        if usd < self.config.coin_per_route_usd and self._release_idle(
            sell_exchange, base, now_ms, self.config.coin_per_route_usd - usd
        ):
            usd = self._coin_seed_usd(sell_exchange)
        if usd > ZERO:
            self._seed((sell_exchange, base), usd / price, price)
            self.last_used_ms[(sell_exchange, base)] = now_ms
        return True

    def drain_conversions(self) -> list[Rebalance]:
        """Idle-slot conversions made so far (cleared), to be stored with the next commit."""
        done, self.conversions = self.conversions, []
        return done

    def _release_idle(self, exchange: str, new_base: str, now_ms: int, needed: Decimal) -> bool:
        """Free idle coin slots of ``exchange`` (oldest first) until ``needed`` USD of budget.

        The coin is converted back to USDT at the current price minus ``conversion_cost_pct``:
        the original slot value becomes USDT seed (capital stays fixed), the cost is booked as
        a rebalance cost and stored as a ``conversion`` record. Returns True if any was freed.
        """
        release_ms = self.config.coin_idle_release_ms
        if release_ms is None or now_ms <= 0:
            return False
        busy = {(r.to_exchange, r.asset) for r in self.in_flight} | {
            (r.from_exchange, r.asset) for r in self.in_flight
        }
        idle: list[tuple[int, Venue]] = []
        for venue in self.seeds:
            ex, asset = venue
            if ex != exchange or asset in (USD_QUOTE, new_base) or venue in busy:
                continue
            last = self.last_used_ms.setdefault(venue, now_ms)
            if now_ms - last >= release_ms and asset in self.prices:
                idle.append((last, venue))
        freed = ZERO
        for _, venue in sorted(idle):
            if freed >= needed:
                break
            freed += self._convert_to_usdt(venue, now_ms)
        return freed > ZERO

    def _convert_to_usdt(self, venue: Venue, now_ms: int) -> Decimal:
        """Sell the whole balance of an idle coin slot; returns the freed slot value (USD)."""
        exchange, asset = venue
        seed = self.seeds.pop(venue)
        amount = self.balances.pop(venue, ZERO)
        price = self.prices[asset]
        self.last_used_ms.pop(venue, None)
        self.blocked.pop(venue, None)
        gross = amount * price
        cost = gross * self.config.conversion_cost_pct / HUNDRED
        slot_value = seed.amount * seed.price
        usdt = (exchange, USD_QUOTE)
        old_usdt = self.seeds.get(usdt)
        # Capital is unchanged: the slot's seed value moves to the venue's USDT seed, so the
        # price drift and the cost show up as P&L (mark-to-market and rebalance cost).
        self.seeds[usdt] = Seed(
            amount=(old_usdt.amount if old_usdt else ZERO) + slot_value, price=Decimal(1)
        )
        self._add(usdt, gross - cost)
        self.rebalance_costs += cost
        if amount > ZERO:
            self.conversions.append(
                Rebalance(
                    asset,
                    exchange,
                    exchange,
                    amount,
                    cost / price,
                    cost,
                    CONVERSION_NETWORK,
                    now_ms,
                    now_ms,
                    RebalanceStatus.COMPLETED,
                    "idle coin slot converted back to USDT",
                )
            )
        return slot_value

    def _coin_seed_usd(self, exchange: str) -> Decimal:
        budget = self.config.coin_budget_per_venue_usd
        if budget is None:
            return self.config.coin_per_route_usd
        used = sum(
            (
                s.amount * s.price
                for (ex, asset), s in self.seeds.items()
                if ex == exchange and asset != USD_QUOTE
            ),
            ZERO,
        )
        return max(ZERO, min(self.config.coin_per_route_usd, budget - used))

    def _seed(self, venue: Venue, amount: Decimal, price: Decimal) -> None:
        if venue in self.seeds:
            return
        self.seeds[venue] = Seed(amount=amount, price=price)
        self.balances[venue] = self.balances.get(venue, ZERO) + amount

    def balance(self, exchange: str, asset: str) -> Decimal:
        """Free balance."""
        return self.balances.get((exchange, asset), ZERO)

    # ------------------------------------------------------------------ trading

    def trade_size(
        self,
        buy_exchange: str,
        sell_exchange: str,
        base: str,
        best_ask: Decimal,
        now_ms: int = 0,
    ) -> tuple[Decimal, SkipReason | None]:
        """USD size of the next trade: the target notional, capped by the USDT on the buy
        venue and by the coin on the sell venue.

        The coin cap uses the buy venue's ``best_ask``: the base bought (and then sold) for
        ``size`` is ``size / VWAP <= size / best_ask``, so it never exceeds the inventory.

        Returns ``(0, reason)`` when the available inventory is below the minimum size.
        """
        self._require_in_set(buy_exchange, sell_exchange)
        if not self.ensure_seeded(buy_exchange, sell_exchange, base, now_ms):
            return ZERO, SkipReason.NO_PRICE
        usdt_venue, coin_venue = (buy_exchange, USD_QUOTE), (sell_exchange, base)
        usdt = self.balance(*usdt_venue)
        coin_usd = self.balance(*coin_venue) * best_ask
        minimum = self.config.trade_notional_usd * self.config.min_trade_fraction
        if usdt < minimum:
            return ZERO, self._shortage_reason(usdt_venue, SkipReason.INSUFFICIENT_USDT)
        if coin_usd < minimum:
            return ZERO, self._shortage_reason(coin_venue, self._coin_shortage(coin_venue))
        return min(self.config.trade_notional_usd, usdt, coin_usd), None

    def trade(
        self,
        symbol: str,
        base: str,
        buy_exchange: str,
        sell_exchange: str,
        breakdown: SpreadBreakdown | None,
        at_ms: int,
    ) -> TradeOutcome:
        """Buy on ``buy_exchange`` and sell inventory on ``sell_exchange`` simultaneously.

        ``breakdown`` is the estimator's result on the books taken after the latency (no
        per-trade transfer cost: inventory is rebalanced separately).
        """

        def outcome(reason: SkipReason | None) -> TradeOutcome:
            return TradeOutcome(symbol, base, buy_exchange, sell_exchange, at_ms, reason, breakdown)

        if breakdown is None:
            return outcome(SkipReason.BOOKS_UNAVAILABLE)
        if breakdown.net_profit_usd <= ZERO:
            return outcome(SkipReason.SPREAD_GONE)
        if not self.ensure_seeded(buy_exchange, sell_exchange, base, at_ms):
            return outcome(SkipReason.NO_PRICE)
        usdt_venue, coin_venue = (buy_exchange, USD_QUOTE), (sell_exchange, base)
        if self.balance(*usdt_venue) < breakdown.cost_quote:
            return outcome(self._shortage_reason(usdt_venue, SkipReason.INSUFFICIENT_USDT))
        if self.balance(*coin_venue) < breakdown.base_sold:
            return outcome(self._shortage_reason(coin_venue, self._coin_shortage(coin_venue)))
        self._add(usdt_venue, -breakdown.cost_quote)
        self._add((buy_exchange, base), breakdown.base_received)
        self._add(coin_venue, -breakdown.base_sold)
        self._add((sell_exchange, USD_QUOTE), breakdown.proceeds_quote)
        self.realized += breakdown.net_profit_usd
        self.last_used_ms[coin_venue] = at_ms
        if (buy_exchange, base) in self.seeds:
            self.last_used_ms[(buy_exchange, base)] = at_ms
        return outcome(None)

    def _coin_shortage(self, coin_venue: Venue) -> SkipReason:
        """No coin to sell: a never-seeded slot means the venue's coin budget is exhausted."""
        if coin_venue in self.seeds:
            return SkipReason.INSUFFICIENT_COIN
        return SkipReason.COIN_BUDGET_EXHAUSTED

    def _shortage_reason(self, venue: Venue, default: SkipReason) -> SkipReason:
        if any((r.to_exchange, r.asset) == venue for r in self.in_flight):
            return SkipReason.REBALANCE_IN_FLIGHT
        if venue in self.blocked:
            return SkipReason.NO_REBALANCE_PATH
        return default

    def _add(self, venue: Venue, delta: Decimal) -> None:
        self.balances[venue] = self.balances.get(venue, ZERO) + delta

    # ------------------------------------------------------------------ rebalancing

    def rebalance_needs(self, now_ms: int) -> list[RebalanceNeed]:
        """Seeded balances below the threshold that another venue can refill."""
        needs: list[RebalanceNeed] = []
        busy = {(r.to_exchange, r.asset) for r in self.in_flight}
        for venue, seed in sorted(self.seeds.items()):
            exchange, asset = venue
            balance = self.balance(exchange, asset)
            if balance >= seed.amount * self.config.rebalance_threshold_pct / HUNDRED:
                continue
            if venue in busy or self._recently_blocked(venue, now_ms):
                continue
            source = self._best_source(asset, exclude=exchange)
            if source is None:
                continue
            surplus = self.balance(source, asset) - self._seeded(source, asset)
            amount = min(seed.amount - balance, surplus)
            if amount > ZERO:
                needs.append(RebalanceNeed(asset, source, exchange, amount))
        return needs

    def _in_set(self, exchange: str) -> bool:
        return self.venues is None or exchange in self.venues

    def _recently_blocked(self, venue: Venue, now_ms: int) -> bool:
        blocked_at = self.blocked.get(venue)
        return blocked_at is not None and now_ms - blocked_at < self.config.blocked_retry_ms

    def _seeded(self, exchange: str, asset: str) -> Decimal:
        seed = self.seeds.get((exchange, asset))
        return seed.amount if seed is not None else ZERO

    def _best_source(self, asset: str, *, exclude: str) -> str | None:
        surpluses = [
            (self.balance(exchange, a) - self._seeded(exchange, a), exchange)
            for (exchange, a) in self.balances
            if a == asset and exchange != exclude and self._in_set(exchange)
        ]
        positive = [(s, e) for s, e in surpluses if s > ZERO]
        return max(positive)[1] if positive else None

    def start_rebalance(self, need: RebalanceNeed, quote: TransferQuote, now_ms: int) -> Rebalance:
        """Lock ``need.amount`` at the source and schedule its arrival, or record a block.

        ``quote`` is the cheapest network from the real (read-only) metadata; only a
        ``VERIFIED`` path with a fee below the amount is usable.
        """
        price = Decimal(1) if need.asset == USD_QUOTE else self.prices.get(need.asset, ZERO)
        tax_pct = self.config.transfer_tax_pct.get(need.asset, ZERO)
        fee = quote.fee_base + (need.amount - quote.fee_base) * tax_pct / HUNDRED
        usable = quote.status is TransferStatus.VERIFIED and fee < need.amount
        if not usable:
            note = quote.note or f"transfer {quote.status.value}"
            if quote.status is TransferStatus.VERIFIED:
                note = "withdrawal fee exceeds the amount"
            self.blocked[(need.to_exchange, need.asset)] = now_ms
            return Rebalance(
                need.asset,
                need.from_exchange,
                need.to_exchange,
                need.amount,
                ZERO,
                ZERO,
                quote.network,
                now_ms,
                now_ms,
                RebalanceStatus.BLOCKED,
                note,
            )
        self.blocked.pop((need.to_exchange, need.asset), None)
        fee_usd = fee * price
        rebalance = Rebalance(
            need.asset,
            need.from_exchange,
            need.to_exchange,
            need.amount,
            fee,
            fee_usd,
            quote.network,
            now_ms,
            now_ms + self.config.rebalance_delay_ms,
            RebalanceStatus.IN_FLIGHT,
        )
        self._add((need.from_exchange, need.asset), -need.amount)
        self.rebalance_costs += fee_usd
        self.in_flight.append(rebalance)
        return rebalance

    def settle(self, now_ms: int) -> list[Rebalance]:
        """Credit transfers that arrived; returns them as ``COMPLETED``."""
        arrived = [r for r in self.in_flight if r.arrives_at_ms <= now_ms]
        self.in_flight = [r for r in self.in_flight if r.arrives_at_ms > now_ms]
        for rebalance in arrived:
            self._add((rebalance.to_exchange, rebalance.asset), rebalance.received)
        return [replace(r, status=RebalanceStatus.COMPLETED) for r in arrived]

    # ------------------------------------------------------------------ valuation

    def valuation(self) -> Valuation:
        """Capital vs current equity (assets without a price are valued at their seed)."""
        capital = sum((s.amount * s.price for s in self.seeds.values()), ZERO)
        holdings: dict[str, Decimal] = {}
        for (_, asset), amount in self.balances.items():
            holdings[asset] = holdings.get(asset, ZERO) + amount
        for rebalance in self.in_flight:
            holdings[rebalance.asset] = holdings.get(rebalance.asset, ZERO) + rebalance.received
        equity = sum((amount * self._price(asset) for asset, amount in holdings.items()), ZERO)
        return Valuation(capital, equity, self.realized, self.rebalance_costs)

    def _price(self, asset: str) -> Decimal:
        if asset == USD_QUOTE:
            return Decimal(1)
        if asset in self.prices:
            return self.prices[asset]
        seeds = [s.price for (_, a), s in self.seeds.items() if a == asset]
        return seeds[0] if seeds else ZERO

    # ------------------------------------------------------------------ restore

    @classmethod
    def restore(
        cls,
        config: PaperConfig,
        holdings: Iterable[tuple[str, str, Decimal, Seed | None]],
        in_flight: Iterable[Rebalance],
        totals: Mapping[str, Decimal],
        venues: frozenset[str] | None = None,
    ) -> PaperPortfolio:
        """Rebuild from the last balance snapshot, open transfers and running totals."""
        portfolio = cls(config, venues=venues)
        for exchange, asset, amount, seed in holdings:
            portfolio.balances[(exchange, asset)] = amount
            if seed is not None:
                portfolio.seeds[(exchange, asset)] = seed
        portfolio.in_flight = [r for r in in_flight if r.status is RebalanceStatus.IN_FLIGHT]
        portfolio.realized = totals.get("realized", ZERO)
        portfolio.rebalance_costs = totals.get("rebalance_costs", ZERO)
        return portfolio
