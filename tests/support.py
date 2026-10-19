"""Shared test builders."""

from dataclasses import replace
from decimal import Decimal as D

from nexus.domain.spread import (
    EvaluationStatus,
    SpreadBreakdown,
    SpreadEvaluation,
    TransferQuote,
    TransferStatus,
)

EVALUATED_AT_MS = 1_800_000_000_123


def make_breakdown() -> SpreadBreakdown:
    return SpreadBreakdown(
        best_ask_buy=D(100),
        best_bid_sell=D(101),
        vwap_buy=D(100),
        vwap_sell=D(101),
        base_bought=D(10),
        base_received=D("9.99"),
        base_sold=D("9.99"),
        cost_quote=D(1000),
        proceeds_quote=D("1007.98101"),
        gross_spread_pct=D(1),
        net_profit_usd=D("7.98101"),
        net_profit_pct=D("0.798101"),
        fee_buy_usd=D(1),
        fee_sell_usd=D("1.00899"),
        transfer_fee_usd=D(0),
        slippage_usd=D(0),
    )


def make_evaluation(
    *,
    status: EvaluationStatus = EvaluationStatus.PROFITABLE,
    transfer: TransferQuote | None = None,
    with_breakdown: bool = True,
    symbol: str = "ABC/USDT",
    buy_exchange: str = "binance",
    sell_exchange: str = "kucoin",
    evaluated_at_ms: int = EVALUATED_AT_MS,
    fees_estimated: bool = False,
    net_usd: D | None = None,
) -> SpreadEvaluation:
    """``net_usd`` overrides the breakdown's net profit (percent = net / $1,000 notional)."""
    base, quote = symbol.split("/")
    breakdown = make_breakdown() if with_breakdown else None
    if breakdown is not None and net_usd is not None:
        breakdown = replace(breakdown, net_profit_usd=net_usd, net_profit_pct=net_usd / 10)
    return SpreadEvaluation(
        symbol=symbol,
        base=base,
        quote=quote,
        buy_exchange=buy_exchange,
        sell_exchange=sell_exchange,
        notional_usd=D(1000),
        status=status,
        transfer=transfer or TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D(0)),
        buy_book_age_ms=120,
        sell_book_age_ms=340,
        evaluated_at_ms=evaluated_at_ms,
        gross_spread_pct=D(1),
        breakdown=breakdown,
        reason="" if with_breakdown else "sell side",
        fees_estimated=fees_estimated,
    )
