"""Hedged-transfer paper portfolio: USDT pools, positions, funding, exits, rebalancing, valuation.

Pure Decimal bookkeeping without I/O. Nothing here can place an order or move funds: every cash
movement is a simulated ledger entry between per-venue USDT pools. P&L identity (spec 3):
``total = S + R + D + U + P + F - L - RB - LQ`` where ``LQ`` is the margin forfeited beyond the
price move when the hedge was liquidated.

Cash model (``RB`` and ``L`` are prepaid reserves, so the pools always equal the ledger):
entry takes ``cost + L + RB`` from A's pool and ``margin + perp fee`` from H's pool; each exit
credits B's pool with the sale proceeds and H's pool with ``margin share + perp P&L - fee``;
funding is credited to / debited from H's pool when booked.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from nexus.domain.models import ZERO, OrderBook, PriceLevel
from nexus.domain.perp import MarkKline
from nexus.engine.depth import buy_base, floor_to_step, sell_base
from nexus.simulation.hedged import (
    EntryPlan,
    EntryRequest,
    EntryState,
    HedgedConfig,
    depth_within,
)
from nexus.simulation.transit import estimate_transit

ONE = Decimal(1)
MINUTE_MS = 60_000
HOUR_MS = 3_600_000


class HedgedStatus(StrEnum):
    """Position state (spec 1)."""

    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    LIQUIDATED = "LIQUIDATED"
    """Hedge broke; the spot leg continues unhedged until it is sold."""
    CLOSED = "CLOSED"
    CLOSED_UNHEDGED = "CLOSED_UNHEDGED"
    FORCED_EXIT = "FORCED_EXIT"


TERMINAL = frozenset({HedgedStatus.CLOSED, HedgedStatus.CLOSED_UNHEDGED, HedgedStatus.FORCED_EXIT})


class ExitStatus(StrEnum):
    """Result of one exit attempt."""

    NOT_ARRIVED = "NOT_ARRIVED"
    TERMINAL = "TERMINAL"
    DEPOSIT_CLOSED = "DEPOSIT_CLOSED"
    STALE = "STALE"
    THIN = "THIN"
    HEDGE_UNPRICED = "HEDGE_UNPRICED"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class PnlLines:
    """Decomposition of a finished position (all USDT)."""

    s: Decimal = ZERO
    r: Decimal = ZERO
    d: Decimal = ZERO
    u: Decimal = ZERO
    p: Decimal = ZERO
    f: Decimal = ZERO
    leg_reserve: Decimal = ZERO
    rb: Decimal = ZERO
    liquidation: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        """``S + R + D + U + P + F - L - RB - LQ``."""
        return (
            self.s
            + self.r
            + self.d
            + self.u
            + self.p
            + self.f
            - self.leg_reserve
            - self.rb
            - self.liquidation
        )


@dataclass(slots=True)
class HedgedPosition:
    """One hedged transfer attempt that was entered (skips are not positions)."""

    key: str
    plan: EntryPlan
    coin: str
    buy_venue: str
    sell_venue: str
    opened_ms: int
    arrive_ms: int
    tau_min: Decimal
    stuck: bool
    status: HedgedStatus = HedgedStatus.IN_TRANSIT
    q_open: Decimal = ZERO
    q_h_open: Decimal = ZERO
    margin_open: Decimal = ZERO
    funding_total: Decimal = ZERO
    funding_times: set[int] = field(default_factory=set)
    sold_gross: Decimal = ZERO
    """Sum of ``q_i * b_i`` over spot fills on B."""
    perp_close_value: Decimal = ZERO
    """Sum of ``q_h_i * f_i`` over perp closes (liquidated units at ``P_liq``)."""
    perp_exit_fees: Decimal = ZERO
    liquidation_loss: Decimal = ZERO
    liquidated_ms: int | None = None
    perp_closed_ms: int | None = None
    closed_ms: int | None = None
    net_cash: Decimal = ZERO
    """Cash ledger of this position: entry outflows (negative) plus exit and funding inflows."""
    hedge_unpriced: bool = False
    hedge_unpriced_final: bool = False
    deposit_closed_forced: bool = False
    hedge_break: bool = False
    last_perp_price: Decimal | None = None
    """Highest valid perp mark/ask seen (``P_last`` for the unpriceable final booking)."""
    last_b_bid: Decimal | None = None
    unpriced_since_ms: int | None = None
    lines: PnlLines | None = None
    b1: Decimal | None = None
    f1: Decimal | None = None

    @property
    def is_open(self) -> bool:
        """True until the position reaches a terminal state."""
        return self.status not in TERMINAL

    @property
    def perp_open(self) -> bool:
        """True while a short perp quantity is still open."""
        return self.q_h_open > ZERO


@dataclass(frozen=True, slots=True)
class ExitOutcome:
    """What one exit attempt did."""

    status: ExitStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Rebalance:
    """Virtual USDT move between two pools (the fee is a statistic, RB is prepaid)."""

    source: str
    target: str
    amount: Decimal
    fee_usd: Decimal
    started_ms: int
    arrive_ms: int


@dataclass(frozen=True, slots=True)
class Valuation:
    """Equity and the directional-leak check (spec 9, 11)."""

    equity: Decimal
    pools: Decimal
    in_flight: Decimal
    open_value: Decimal
    open_basis_mtm: Decimal
    directional_mtm: Decimal
    """Equity change not explained by the ledger, entry references and basis: dust only."""
    ledger_residual: Decimal
    """``pools + in-flight - capital - sum(position cash)``: 0 unless the bookkeeping leaks."""


class HedgedPortfolio:
    """USDT pools per venue plus the positions of one HT set."""

    def __init__(self, cfg: HedgedConfig, venues: Sequence[str], run_hash: str) -> None:
        if not venues:
            msg = "at least one venue is required"
            raise ValueError(msg)
        self._cfg = cfg
        self._run_hash = run_hash
        self.pool_target = cfg.capital_usd / len(venues)
        self.pools: dict[str, Decimal] = dict.fromkeys(venues, self.pool_target)
        self.positions: dict[str, HedgedPosition] = {}
        self.rebalances: list[Rebalance] = []
        self.last_fill_ms: dict[tuple[str, str, str], int] = {}
        self.rebalance_retry_ms: dict[str, int] = {}
        self.rebalance_fee_paid = ZERO
        """Actual USDT network fees of completed rebalances (statistic; RB reserves cover them)."""

    @property
    def config(self) -> HedgedConfig:
        """Active parameters."""
        return self._cfg

    # ------------------------------------------------------------------ entry

    def entry_state(self) -> EntryState:
        """Read-only snapshot for :func:`evaluate_entry`."""
        open_positions = [p for p in self.positions.values() if p.is_open]
        return EntryState(
            pools=dict(self.pools),
            open_count=len(open_positions),
            open_coins=frozenset(p.coin for p in open_positions),
            last_fill_ms=dict(self.last_fill_ms),
            pool_target=self.pool_target,
        )

    def open_position(
        self, plan: EntryPlan, req: EntryRequest, position_key: str
    ) -> HedgedPosition:
        """Apply an accepted entry: cash out, margin locked, transfer time drawn (seeded)."""
        a_ex, b_ex = req.a.market.exchange, req.b.market.exchange
        if position_key in self.positions:
            msg = f"duplicate position key {position_key}"
            raise ValueError(msg)
        estimate = estimate_transit(
            run_hash=self._run_hash,
            position_key=position_key,
            source_exchange=a_ex,
            dest_exchange=b_ex,
            network=plan.network,
            confirmations=plan.deposit_confirmations,
            est_arrival_min=plan.est_arrival_min,
            p_stuck=self._cfg.p_stuck,
            stuck_h=self._cfg.stuck_h,
        )
        outflow_a = plan.cost + plan.leg_reserve + plan.rb_reserve
        outflow_h = plan.margin + plan.entry_fee
        self.pools[a_ex] -= outflow_a
        self.pools[plan.hedge_venue] -= outflow_h
        if min(self.pools[a_ex], self.pools[plan.hedge_venue]) < ZERO:
            self.pools[a_ex] += outflow_a
            self.pools[plan.hedge_venue] += outflow_h
            msg = "entry exceeds the USDT pool (evaluate_entry must pass first)"
            raise ValueError(msg)
        pos = HedgedPosition(
            key=position_key,
            plan=plan,
            coin=req.coin,
            buy_venue=a_ex,
            sell_venue=b_ex,
            opened_ms=req.now_ms,
            arrive_ms=req.now_ms + int(estimate.tau_min * MINUTE_MS),
            tau_min=estimate.tau_min,
            stuck=estimate.stuck,
            q_open=plan.q,
            q_h_open=plan.q_h,
            margin_open=plan.margin,
            net_cash=-(outflow_a + outflow_h),
        )
        self.positions[position_key] = pos
        self.last_fill_ms[(req.coin, a_ex, b_ex)] = req.now_ms
        return pos

    # ------------------------------------------------------------------ hold

    def accrue_funding(
        self, pos: HedgedPosition, funding_time_ms: int, rate: Decimal, mark: Decimal
    ) -> Decimal | None:
        """Book ``q_h * mark * rate`` for one funding time (short receives when rate > 0).

        Idempotent per funding time. Returns ``None`` when nothing is booked: duplicate,
        before the entry, after the perp closed, or no perp quantity left.
        """
        if (
            funding_time_ms in pos.funding_times
            or funding_time_ms <= pos.opened_ms
            or not pos.perp_open
            or (pos.perp_closed_ms is not None and funding_time_ms > pos.perp_closed_ms)
        ):
            return None
        amount = pos.q_h_open * mark * rate
        pos.funding_times.add(funding_time_ms)
        pos.funding_total += amount
        pos.net_cash += amount
        self.pools[pos.plan.hedge_venue] += amount
        return amount

    def note_prices(
        self, pos: HedgedPosition, *, perp_price: Decimal | None, b_bid: Decimal | None
    ) -> None:
        """Remember the worst valid perp price and the last B bid (adverse final booking)."""
        if perp_price is not None and (
            pos.last_perp_price is None or perp_price > pos.last_perp_price
        ):
            pos.last_perp_price = perp_price
        if b_bid is not None:
            pos.last_b_bid = b_bid

    def check_liquidation(self, pos: HedgedPosition, price: Decimal, at_ms: int) -> bool:
        """Liquidate when the perp mark (ask if mark is missing) reaches ``P_liq``."""
        if not pos.is_open or pos.status is HedgedStatus.LIQUIDATED or not pos.perp_open:
            return False
        if price < pos.plan.p_liq:
            return False
        self._liquidate(pos, at_ms)
        return True

    def check_liquidation_klines(
        self, pos: HedgedPosition, klines: Iterable[MarkKline], since_ms: int | None = None
    ) -> bool:
        """Liquidate at the first candle after ``since_ms`` whose high reaches ``P_liq``."""
        start = pos.opened_ms if since_ms is None else max(since_ms, pos.opened_ms)
        if not pos.perp_open or pos.status is HedgedStatus.LIQUIDATED or not pos.is_open:
            return False
        for kline in sorted(klines, key=lambda k: k.open_ms):
            if kline.open_ms + MINUTE_MS > start and kline.high >= pos.plan.p_liq:
                self._liquidate(pos, max(kline.open_ms, start))
                return True
        return False

    def _liquidate(self, pos: HedgedPosition, at_ms: int) -> None:
        """Loss = full margin of the open perp quantity; the spot leg stays, now unhedged."""
        plan = pos.plan
        move = pos.q_h_open * (plan.p_liq - plan.f0)  # adverse price move of the short
        pos.liquidation_loss += pos.margin_open - move
        pos.perp_close_value += pos.q_h_open * plan.p_liq
        pos.q_h_open = ZERO
        pos.margin_open = ZERO
        pos.status = HedgedStatus.LIQUIDATED
        pos.hedge_break = True
        pos.liquidated_ms = at_ms
        pos.perp_closed_ms = at_ms

    # ------------------------------------------------------------------ exit

    def hold_exceeded(self, pos: HedgedPosition, now_ms: int) -> bool:
        """True from ``opened + max_hold_h`` on (forced exit)."""
        return now_ms >= pos.opened_ms + self._cfg.max_hold_h * HOUR_MS

    def final_booking_due(self, pos: HedgedPosition, now_ms: int) -> bool:
        """True from ``opened + max_hold_h + unpriced_grace_h`` on (C8)."""
        limit = self._cfg.max_hold_h + self._cfg.unpriced_grace_h
        return now_ms >= pos.opened_ms + limit * HOUR_MS

    def try_exit(
        self,
        pos: HedgedPosition,
        now_ms: int,
        b_book: OrderBook | None,
        h_book: OrderBook | None,
        *,
        deposit_open: bool = True,
        forced: bool = False,
    ) -> ExitOutcome:
        """Sell on B and close the matching perp share; partial fills keep the rest open.

        Both legs must be priceable: a spot sale never happens while its hedge cannot be closed
        (C8, no naked short). ``forced`` walks the whole book, pricing any shortfall adversely.
        """
        cfg = self._cfg
        if not pos.is_open:
            return ExitOutcome(ExitStatus.TERMINAL)
        if now_ms < pos.arrive_ms + cfg.latency_ms:
            return ExitOutcome(ExitStatus.NOT_ARRIVED)
        if pos.status is HedgedStatus.IN_TRANSIT:
            pos.status = HedgedStatus.ARRIVED
        fresh_b = self._fresh(b_book, now_ms)
        fresh_h = self._fresh(h_book, now_ms)
        if fresh_b is not None:
            self.note_prices(pos, perp_price=None, b_bid=fresh_b.best_bid)
        if fresh_h is not None and fresh_h.best_ask is not None:
            self.note_prices(pos, perp_price=fresh_h.best_ask, b_bid=None)
        if fresh_b is not None and fresh_h is not None:
            skew = abs(fresh_b.timestamp_ms - fresh_h.timestamp_ms)
            if skew > cfg.max_book_skew_ms:
                fresh_b = fresh_h = None
        if pos.perp_open and fresh_h is None:
            return self._unpriced(pos, now_ms, "perp book stale or missing")
        if fresh_b is None or fresh_b.best_bid is None:
            return ExitOutcome(ExitStatus.STALE, "B book stale or missing")
        if not deposit_open:
            if not forced:
                return ExitOutcome(ExitStatus.DEPOSIT_CLOSED)
            pos.deposit_closed_forced = True
        return self._execute_exit(pos, now_ms, fresh_b, fresh_h, forced=forced)

    def _fresh(self, book: OrderBook | None, now_ms: int) -> OrderBook | None:
        if book is None or book.age_ms(now_ms) > self._cfg.max_book_age_ms:
            return None
        return book

    def _unpriced(self, pos: HedgedPosition, now_ms: int, detail: str) -> ExitOutcome:
        pos.hedge_unpriced = True
        if pos.unpriced_since_ms is None:
            pos.unpriced_since_ms = now_ms
        return ExitOutcome(ExitStatus.HEDGE_UNPRICED, detail)

    def _execute_exit(
        self,
        pos: HedgedPosition,
        now_ms: int,
        b_book: OrderBook,
        h_book: OrderBook | None,
        *,
        forced: bool,
    ) -> ExitOutcome:
        cfg = self._cfg
        window = cfg.max_slippage * cfg.exit_slippage_mult
        best_bid = b_book.best_bid
        if best_bid is None:  # pragma: no cover - guarded by try_exit
            return ExitOutcome(ExitStatus.STALE)
        q_open = pos.q_open
        if forced:
            qs = q_open
        else:
            qs = min(q_open, depth_within(b_book.bids, best_bid, window, buy=False))
            if qs <= ZERO:
                return ExitOutcome(ExitStatus.THIN, "B bids within 2x slippage are empty")
        qh = pos.q_h_open
        if qh > ZERO and qs < q_open:
            qh = min(qh, floor_to_step(qs * pos.q_h_open / q_open, pos.plan.perp_lot_base))
        perp_fill = None
        if qh > ZERO:
            best_ask = h_book.best_ask if h_book is not None else None
            if h_book is None or best_ask is None:
                return self._unpriced(pos, now_ms, "perp ask side empty")
            if not forced and depth_within(h_book.asks, best_ask, window, buy=True) < qh:
                return self._unpriced(pos, now_ms, "perp asks within 2x slippage too thin")
            perp_fill = self._close_price(h_book.asks, qh, best_ask, window, up=True)
        spot_gross = self._close_price(b_book.bids, qs, best_bid, window, up=False)
        self._book_exit(pos, qs, spot_gross, qh, perp_fill, now_ms, forced=forced)
        pos.hedge_unpriced = False
        pos.unpriced_since_ms = None
        return ExitOutcome(ExitStatus.CLOSED if not pos.is_open else ExitStatus.PARTIAL)

    @staticmethod
    def _close_price(
        levels: Sequence[PriceLevel], amount: Decimal, best: Decimal, window: Decimal, *, up: bool
    ) -> Decimal:
        """Gross quote value of closing ``amount``: book walk, shortfall at the worst price."""
        walk = buy_base(levels, amount) if up else sell_base(levels, amount)
        if walk is not None:
            return walk.quote_amount
        covered = ZERO
        value = ZERO
        worst = best
        for level in levels:
            take = min(amount - covered, level.amount)
            value += take * level.price
            covered += take
            worst = level.price
        adverse = worst * (ONE + window) if up else worst * (ONE - window)
        return value + (amount - covered) * adverse

    def _book_exit(
        self,
        pos: HedgedPosition,
        qs: Decimal,
        spot_gross: Decimal,
        qh: Decimal,
        perp_value: Decimal | None,
        now_ms: int,
        *,
        forced: bool,
    ) -> None:
        plan = pos.plan
        proceeds = spot_gross * (ONE - plan.phi_b)
        self.pools[pos.sell_venue] += proceeds
        pos.net_cash += proceeds
        pos.sold_gross += spot_gross
        pos.q_open -= qs
        if qh > ZERO and perp_value is not None:
            margin_part = pos.margin_open * qh / pos.q_h_open
            fee = plan.phi_h * perp_value
            back = margin_part + qh * plan.f0 - perp_value - fee
            self.pools[plan.hedge_venue] += back
            pos.net_cash += back
            pos.margin_open -= margin_part
            pos.q_h_open -= qh
            pos.perp_close_value += perp_value
            pos.perp_exit_fees += fee
        if pos.q_open > ZERO:
            return
        # all coin sold: any residual perp quantity would be unhedged short; cannot happen
        # because the last spot piece closes the whole remaining perp quantity.
        pos.closed_ms = now_ms
        if pos.status is HedgedStatus.LIQUIDATED:
            pos.status = HedgedStatus.CLOSED_UNHEDGED
        else:
            pos.status = HedgedStatus.FORCED_EXIT if forced else HedgedStatus.CLOSED
        self._finalize(pos)

    def book_unpriced_final(
        self, pos: HedgedPosition, now_ms: int, b_book: OrderBook | None
    ) -> bool:
        """Final adverse booking of a still-unpriceable hedge (C8), unless it was liquidated.

        Perp buy-to-close at ``P_last * (1 + 2 * slippage)`` (fee charged); spot sold on the
        current fresh B book, else at the last valid bid ``* (1 - 2 * slippage)``.
        """
        cfg = self._cfg
        if not pos.is_open or pos.status is HedgedStatus.LIQUIDATED or not pos.perp_open:
            return False
        window = cfg.max_slippage * cfg.exit_slippage_mult
        plan = pos.plan
        p_last = max(pos.last_perp_price or ZERO, plan.mark, plan.f0)
        f_close = p_last * (ONE + window)
        qh = pos.q_h_open
        perp_value = qh * f_close
        fresh_b = self._fresh(b_book, now_ms)
        if fresh_b is not None and fresh_b.best_bid is not None:
            spot_gross = self._close_price(
                fresh_b.bids, pos.q_open, fresh_b.best_bid, window, up=False
            )
        else:
            bid = pos.last_b_bid if pos.last_b_bid is not None else plan.b0
            spot_gross = pos.q_open * bid * (ONE - window)
        pos.hedge_unpriced = True
        pos.hedge_unpriced_final = True
        self._book_exit(pos, pos.q_open, spot_gross, qh, perp_value, now_ms, forced=False)
        return True

    def _finalize(self, pos: HedgedPosition) -> None:
        plan = pos.plan
        q, q_h = plan.q, plan.q_h
        b1 = pos.sold_gross / q
        f1 = pos.perp_close_value / q_h if q_h > ZERO else plan.f0
        pos.b1, pos.f1 = b1, f1
        pos.lines = PnlLines(
            s=q * plan.b0 * (ONE - plan.phi_b) - plan.cost,
            r=q_h * ((b1 - f1) - (plan.b0 - plan.f0)),
            d=-q * plan.phi_b * (b1 - plan.b0),
            u=(q - q_h) * (b1 - plan.b0),
            p=-plan.entry_fee - pos.perp_exit_fees,
            f=pos.funding_total,
            leg_reserve=plan.leg_reserve,
            rb=plan.rb_reserve,
            liquidation=pos.liquidation_loss,
        )

    # ------------------------------------------------------------------ capital

    def plan_rebalances(
        self,
        now_ms: int,
        route: Callable[[str, str], tuple[Decimal, Decimal] | None],
    ) -> list[Rebalance]:
        """Refill pools below the threshold from the largest surplus (virtual USDT transfer).

        ``route(source, target)`` returns ``(fee_usd, delay_min)`` of the cheapest VERIFIED USDT
        network or ``None`` (blocked: retried after ``rebalance_retry_ms``).
        """
        cfg = self._cfg
        started: list[Rebalance] = []
        in_flight_to = {r.target for r in self.rebalances}
        for target in sorted(self.pools, key=lambda v: self.pools[v]):
            if (
                self.pools[target] >= cfg.refill_threshold_usd
                or target in in_flight_to
                or self.rebalance_retry_ms.get(target, 0) > now_ms
            ):
                continue
            donors = sorted(
                (v for v in self.pools if v != target and v not in in_flight_to),
                key=lambda v: self.pools[v] - self.pool_target,
                reverse=True,
            )
            if not donors:
                continue
            source = donors[0]
            amount = min(
                self.pool_target - self.pools[target], self.pools[source] - self.pool_target
            )
            if amount <= ZERO:
                continue
            quote = route(source, target)
            if quote is None:
                self.rebalance_retry_ms[target] = now_ms + cfg.rebalance_retry_ms
                continue
            fee, delay_min = quote
            move = Rebalance(
                source, target, amount, fee, now_ms, now_ms + int(delay_min * MINUTE_MS)
            )
            self.pools[source] -= amount
            self.rebalances.append(move)
            started.append(move)
            in_flight_to.add(target)
        return started

    def settle_rebalances(self, now_ms: int) -> list[Rebalance]:
        """Credit arrived rebalances to their target pool."""
        arrived = [r for r in self.rebalances if r.arrive_ms <= now_ms]
        for move in arrived:
            self.pools[move.target] += move.amount
            self.rebalance_fee_paid += move.fee_usd
        self.rebalances = [r for r in self.rebalances if r.arrive_ms > now_ms]
        return arrived

    # ------------------------------------------------------------------ valuation

    def valuation(
        self,
        spot_mid: Mapping[str, Decimal],
        marks: Mapping[tuple[str, str], Decimal],
    ) -> Valuation:
        """Equity with open positions valued delta-neutral (coin at the shared mid, perp at mark).

        ``spot_mid[coin]`` is the median spot mid; ``marks[(coin, hedge_venue)]`` the perp mark.
        A position without a price is valued at its entry references (no unrealised P&L).
        """
        pools = sum(self.pools.values(), ZERO)
        in_flight = sum((r.amount for r in self.rebalances), ZERO)
        open_value = ZERO
        reference = ZERO
        basis = ZERO
        ledger = ZERO
        for pos in self.positions.values():
            ledger += pos.net_cash
            if not pos.is_open:
                continue
            plan = pos.plan
            mid = spot_mid.get(pos.coin, plan.b0)
            mark = marks.get((pos.coin, plan.hedge_venue), plan.f0)
            value = pos.q_open * mid
            reference += pos.q_open * plan.b0
            if pos.perp_open:
                value += pos.margin_open + pos.q_h_open * (plan.f0 - mark)
                reference += pos.margin_open
                basis += pos.q_h_open * ((mid - mark) - (plan.b0 - plan.f0))
            open_value += value
        equity = pools + in_flight + open_value
        directional = equity - self._cfg.capital_usd - ledger - reference - basis
        return Valuation(
            equity=equity,
            pools=pools,
            in_flight=in_flight,
            open_value=open_value,
            open_basis_mtm=basis,
            directional_mtm=directional,
            ledger_residual=pools + in_flight - self._cfg.capital_usd - ledger,
        )
