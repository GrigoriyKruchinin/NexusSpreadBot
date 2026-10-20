"""Depth-aware net spread estimator.

Model of one round trip on the reference notional ``N`` (quote asset == USD 1:1):

1. **Buy leg** on the buy venue: walk the asks to find the base amount ``N`` buys, round it
   down to the lot step, then re-walk the asks to get the exact quote cost ``C <= N``.
2. **Buy taker fee** is charged in the received asset: ``base_received = bought * (1 - f_buy)``.
3. **Transfer** (optional): subtract the cheapest common-network withdrawal fee (base units).
   Nothing is ever transferred by the bot; this models the cost of rebalancing inventory.
4. **Sell leg** on the sell venue: round down to the lot step (remainder counts as lost) and
   walk the bids for gross proceeds ``P``; the sell taker fee is charged in quote:
   ``proceeds = P * (1 - f_sell)``.
5. ``net_profit = proceeds - C`` and ``net_profit_pct = net_profit / C * 100``.

Both thresholds (percent AND USD) must be met for the result to be ``PROFITABLE``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from nexus.config.groups import SpreadSettings
from nexus.domain.clock import Clock
from nexus.domain.models import ZERO, MarketInfo, OrderBook
from nexus.domain.spread import (
    EvaluationStatus,
    SpreadBreakdown,
    SpreadEvaluation,
    TransferQuote,
    TransferStatus,
)
from nexus.engine.depth import buy_base, floor_to_step, max_base_for_quote, sell_base

HUNDRED = Decimal(100)
ONE = Decimal(1)
USD_PEGGED_QUOTES: frozenset[str] = frozenset({"USDT", "USDC"})


@dataclass(frozen=True, slots=True)
class EstimatorConfig:
    """Parameters of the net spread estimator."""

    min_net_profit_pct: Decimal
    min_net_profit_usd: Decimal
    reference_notional_usd: Decimal
    max_orderbook_age_ms: int
    max_book_skew_ms: int
    max_gross_spread_pct: Decimal
    include_transfer_cost: bool
    require_verified_transfer: bool
    max_unverified_gross_spread_pct: Decimal | None = None
    """Sanity cap applied unless the transfer path AND the token identity (matching contract
    addresses) are verified (``None`` = only ``max_gross_spread_pct`` applies)."""
    transfer_tax_pct: Mapping[str, Decimal] = field(default_factory=dict)
    """On-chain transfer tax per base asset (percent of the amount moved)."""

    @classmethod
    def from_settings(cls, settings: SpreadSettings) -> EstimatorConfig:
        """Build from :class:`~nexus.config.groups.SpreadSettings`."""
        return cls(
            min_net_profit_pct=settings.min_net_profit_pct,
            min_net_profit_usd=settings.min_net_profit_usd,
            reference_notional_usd=settings.reference_notional_usd,
            max_orderbook_age_ms=settings.max_orderbook_age_ms,
            max_book_skew_ms=settings.max_book_skew_ms,
            max_gross_spread_pct=settings.max_gross_spread_pct,
            include_transfer_cost=settings.include_transfer_cost,
            require_verified_transfer=settings.require_verified_transfer,
            max_unverified_gross_spread_pct=settings.max_unverified_gross_spread_pct,
            transfer_tax_pct=dict(settings.transfer_tax_pct),
        )


class NetSpreadEstimator:
    """Evaluates a buy-here / sell-there route against real order book depth."""

    def __init__(self, config: EstimatorConfig, clock: Clock) -> None:
        self._config = config
        self._clock = clock

    @property
    def config(self) -> EstimatorConfig:
        """Active configuration."""
        return self._config

    def evaluate(
        self,
        *,
        buy_book: OrderBook,
        sell_book: OrderBook,
        buy_market: MarketInfo,
        sell_market: MarketInfo,
        transfer: TransferQuote,
    ) -> SpreadEvaluation:
        """Evaluate buying on ``buy_book`` and selling on ``sell_book``."""
        cfg = self._config
        now = self._clock.now_ms()
        buy_age = buy_book.age_ms(now)
        sell_age = sell_book.age_ms(now)

        def result(
            status: EvaluationStatus,
            reason: str = "",
            *,
            gross: Decimal | None = None,
            breakdown: SpreadBreakdown | None = None,
        ) -> SpreadEvaluation:
            return SpreadEvaluation(
                symbol=buy_market.symbol,
                base=buy_market.base,
                quote=buy_market.quote,
                buy_exchange=buy_book.exchange,
                sell_exchange=sell_book.exchange,
                notional_usd=cfg.reference_notional_usd,
                status=status,
                transfer=transfer,
                buy_book_age_ms=buy_age,
                sell_book_age_ms=sell_age,
                evaluated_at_ms=now,
                gross_spread_pct=gross,
                breakdown=breakdown,
                reason=reason,
                fees_estimated=buy_market.taker_fee_is_default or sell_market.taker_fee_is_default,
            )

        # ---- data quality guards ------------------------------------------------------
        if buy_market.symbol != sell_market.symbol or buy_book.symbol != sell_book.symbol:
            msg = "buy and sell legs must refer to the same symbol"
            raise ValueError(msg)
        for leg_book, leg_market in ((buy_book, buy_market), (sell_book, sell_market)):
            if (leg_book.exchange, leg_book.symbol) != (leg_market.exchange, leg_market.symbol):
                msg = "order book does not belong to the given market"
                raise ValueError(msg)
        if buy_market.quote not in USD_PEGGED_QUOTES:
            msg = f"quote asset {buy_market.quote} is not a supported USD stablecoin"
            raise ValueError(msg)
        if buy_book.exchange == sell_book.exchange:
            msg = "buy and sell legs must be on different exchanges"
            raise ValueError(msg)
        if buy_age > cfg.max_orderbook_age_ms or sell_age > cfg.max_orderbook_age_ms:
            return result(EvaluationStatus.STALE_BOOK, f"book age {buy_age}/{sell_age} ms")
        skew = abs(buy_book.timestamp_ms - sell_book.timestamp_ms)
        if skew > cfg.max_book_skew_ms:
            return result(EvaluationStatus.STALE_BOOK, f"book skew {skew} ms")
        if not (buy_market.active and sell_market.active):
            return result(EvaluationStatus.MARKET_INACTIVE)

        best_ask = buy_book.best_ask
        best_bid = sell_book.best_bid
        if best_ask is None or best_bid is None:
            return result(EvaluationStatus.INSUFFICIENT_DEPTH, "empty book side")

        gross = (best_bid - best_ask) / best_ask * HUNDRED
        if gross <= ZERO:
            return result(EvaluationStatus.NO_SPREAD, gross=gross)
        if gross > cfg.max_gross_spread_pct:
            return result(
                EvaluationStatus.SUSPICIOUS_SPREAD,
                "gross spread above sanity limit (ticker collision / delisting?)",
                gross=gross,
            )

        # ---- transfer path -----------------------------------------------------------
        if transfer.status is TransferStatus.UNAVAILABLE:
            return result(EvaluationStatus.TRANSFER_UNAVAILABLE, transfer.note, gross=gross)
        unverified_cap = cfg.max_unverified_gross_spread_pct
        identity_verified = (
            transfer.status is TransferStatus.VERIFIED and transfer.contract_verified
        )
        if not identity_verified and unverified_cap is not None and gross > unverified_cap:
            return result(
                EvaluationStatus.SUSPICIOUS_SPREAD,
                "large spread without a verified transfer path and token contract "
                "(ticker collision / suspended withdrawals?)",
                gross=gross,
            )

        # ---- buy leg -----------------------------------------------------------------
        max_base = max_base_for_quote(buy_book.asks, cfg.reference_notional_usd)
        if max_base is None:
            return result(EvaluationStatus.INSUFFICIENT_DEPTH, "buy side", gross=gross)
        base_bought = floor_to_step(max_base, buy_market.amount_step)
        if base_bought <= ZERO or not _meets_minimums(buy_market, base_bought, None):
            return result(EvaluationStatus.BELOW_MIN_ORDER, "buy leg", gross=gross)
        buy_fill = buy_base(buy_book.asks, base_bought)
        if buy_fill is None:  # pragma: no cover - guaranteed by max_base_for_quote
            return result(EvaluationStatus.INSUFFICIENT_DEPTH, "buy side", gross=gross)
        cost = buy_fill.quote_amount
        if not _meets_minimums(buy_market, base_bought, cost):
            return result(EvaluationStatus.BELOW_MIN_ORDER, "buy leg notional", gross=gross)

        base_received = base_bought * (ONE - buy_market.taker_fee)
        fee_buy_usd = cost * buy_market.taker_fee

        # ---- transfer cost -----------------------------------------------------------
        transfer_fee_base = (
            transfer.fee_base
            if cfg.include_transfer_cost and transfer.status is TransferStatus.VERIFIED
            else ZERO
        )
        if cfg.include_transfer_cost:
            # A chain-level tax applies whatever the network quote says (it is per asset).
            tax_pct = cfg.transfer_tax_pct.get(buy_market.base, ZERO)
            transfer_fee_base += (base_received - transfer_fee_base) * tax_pct / HUNDRED
        base_available = base_received - transfer_fee_base
        if base_available <= ZERO:
            return result(
                EvaluationStatus.BELOW_THRESHOLD, "transfer fee exceeds amount", gross=gross
            )

        # ---- sell leg ----------------------------------------------------------------
        base_sold = floor_to_step(base_available, sell_market.amount_step)
        if base_sold <= ZERO or not _meets_minimums(sell_market, base_sold, None):
            return result(EvaluationStatus.BELOW_MIN_ORDER, "sell leg", gross=gross)
        sell_fill = sell_base(sell_book.bids, base_sold)
        if sell_fill is None:
            return result(EvaluationStatus.INSUFFICIENT_DEPTH, "sell side", gross=gross)
        proceeds_gross = sell_fill.quote_amount
        if not _meets_minimums(sell_market, base_sold, proceeds_gross):
            return result(EvaluationStatus.BELOW_MIN_ORDER, "sell leg notional", gross=gross)
        fee_sell_usd = proceeds_gross * sell_market.taker_fee
        proceeds = proceeds_gross - fee_sell_usd

        # ---- result ------------------------------------------------------------------
        net_usd = proceeds - cost
        net_pct = net_usd / cost * HUNDRED
        slippage_usd = (cost - base_bought * best_ask) + (base_sold * best_bid - proceeds_gross)
        breakdown = SpreadBreakdown(
            best_ask_buy=best_ask,
            best_bid_sell=best_bid,
            vwap_buy=buy_fill.vwap,
            vwap_sell=sell_fill.vwap,
            base_bought=base_bought,
            base_received=base_received,
            base_sold=base_sold,
            cost_quote=cost,
            proceeds_quote=proceeds,
            gross_spread_pct=gross,
            net_profit_usd=net_usd,
            net_profit_pct=net_pct,
            fee_buy_usd=fee_buy_usd,
            fee_sell_usd=fee_sell_usd,
            transfer_fee_usd=transfer_fee_base * sell_fill.vwap,
            slippage_usd=slippage_usd,
        )
        profitable = net_pct >= cfg.min_net_profit_pct and net_usd >= cfg.min_net_profit_usd
        if not profitable:
            return result(EvaluationStatus.BELOW_THRESHOLD, gross=gross, breakdown=breakdown)
        if transfer.status is TransferStatus.UNKNOWN and cfg.require_verified_transfer:
            # Fully priced and stored (episodes, digest, quarantine), but never alerted.
            return result(
                EvaluationStatus.TRANSFER_UNVERIFIED,
                transfer.note,
                gross=gross,
                breakdown=breakdown,
            )
        return result(EvaluationStatus.PROFITABLE, gross=gross, breakdown=breakdown)


def _meets_minimums(market: MarketInfo, amount: Decimal, cost: Decimal | None) -> bool:
    if market.min_amount is not None and amount < market.min_amount:
        return False
    return not (cost is not None and market.min_cost is not None and cost < market.min_cost)
