"""Telegram HTML message templates.

Every dynamic value passes through :func:`esc` (``html.escape``): exchange-provided strings
(network codes, error texts) must never be able to inject markup.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from nexus.domain.events import (
    ExchangeDown,
    ExchangeRecovered,
    ScannerStarted,
    ScannerStopped,
    SystemEvent,
)
from nexus.domain.spread import SpreadEvaluation, TransferStatus

SEPARATOR: Final = "━━━━━━━━━━━━━━━━━━━━"
TELEGRAM_MAX_LENGTH: Final = 4096

EXCHANGE_DISPLAY_NAMES: Final[dict[str, str]] = {
    "binance": "Binance",
    "bybit": "Bybit",
    "okx": "OKX",
    "gateio": "Gate.io",
    "kucoin": "KuCoin",
}


def esc(value: object) -> str:
    """HTML-escape any value for Telegram HTML parse mode."""
    return html.escape(str(value), quote=False)


def exchange_name(name: str) -> str:
    """Human-friendly exchange name."""
    return EXCHANGE_DISPLAY_NAMES.get(name, name.capitalize())


def fmt_usd(value: Decimal, *, signed: bool = False) -> str:
    """``$1,234.57`` (optionally with an explicit sign)."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ("+" if signed else "")
    return f"{sign}${abs(rounded):,.2f}"


def fmt_pct(value: Decimal, *, places: int = 2) -> str:
    """``0.80%``."""
    quantum = Decimal(1).scaleb(-places)
    return f"{value.quantize(quantum, rounding=ROUND_HALF_UP)}%"


def fmt_price(value: Decimal, *, significant: int = 6) -> str:
    """Price with ``significant`` significant digits, no exponent, trailing zeros trimmed."""
    if value == 0:
        return "0"
    exponent = value.adjusted()
    places = max(significant - 1 - exponent, 0)
    quantized = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = f"{quantized:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_amount(value: Decimal) -> str:
    """Base asset amount, up to 8 decimals, trimmed."""
    quantized = value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    text = f"{quantized:,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def fmt_time(epoch_ms: int) -> str:
    """UTC timestamp."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truncate(text: str) -> str:
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return text
    return text[: TELEGRAM_MAX_LENGTH - 1] + "…"


class OpportunityFormatter:
    """Renders a profitable :class:`SpreadEvaluation` as a Telegram HTML alert."""

    def render(self, evaluation: SpreadEvaluation) -> str:
        """Render the alert; requires a cost breakdown."""
        bd = evaluation.breakdown
        if bd is None:
            msg = "cannot render an opportunity without a cost breakdown"
            raise ValueError(msg)
        buy = esc(exchange_name(evaluation.buy_exchange))
        sell = esc(exchange_name(evaluation.sell_exchange))
        base = esc(evaluation.base)
        quote = esc(evaluation.quote)

        rows = [
            ("Buy fee", fmt_usd(bd.fee_buy_usd)),
            ("Sell fee", fmt_usd(bd.fee_sell_usd)),
            ("Slippage", fmt_usd(bd.slippage_usd)),
            ("Transfer", self._transfer_cost(evaluation)),
        ]
        width = max(len(label) for label, _ in rows)
        table = "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)

        lines = [
            f"💹 <b>Arbitrage Opportunity</b> · <code>{esc(evaluation.symbol)}</code>",
            SEPARATOR,
            f"🟢 <b>BUY</b> on <b>{buy}</b> @ <code>{fmt_price(bd.best_ask_buy)}</code>"
            f" · VWAP <code>{fmt_price(bd.vwap_buy)}</code>",
            f"🔴 <b>SELL</b> on <b>{sell}</b> @ <code>{fmt_price(bd.best_bid_sell)}</code>"
            f" · VWAP <code>{fmt_price(bd.vwap_sell)}</code>",
            "",
            f"💰 <b>Net profit: {fmt_usd(bd.net_profit_usd, signed=True)}"
            f" ({fmt_pct(bd.net_profit_pct)})</b>",
            f"📈 Gross spread: <b>{fmt_pct(bd.gross_spread_pct)}</b>",
            f"📦 Size: <b>{fmt_usd(bd.cost_quote)}</b> {quote} → "
            f"<b>{fmt_amount(bd.base_bought)}</b> {base}",
            SEPARATOR,
            "🧾 <b>Cost breakdown</b>",
            f"<pre>{esc(table)}</pre>",
            self._transfer_line(evaluation),
            *(
                ["ℹ️ <i>Taker fee is an estimate (not reported per pair by the exchange).</i>"]
                if evaluation.fees_estimated
                else []
            ),
            f"<blockquote>⏱ Book age: {evaluation.buy_book_age_ms} ms / "
            f"{evaluation.sell_book_age_ms} ms\n"
            f"🕒 {fmt_time(evaluation.evaluated_at_ms)}</blockquote>",
        ]
        return _truncate("\n".join(lines))

    @staticmethod
    def _transfer_cost(evaluation: SpreadEvaluation) -> str:
        bd = evaluation.breakdown
        if bd is None or not evaluation.transfer_verified:
            return "n/a"
        return fmt_usd(bd.transfer_fee_usd)

    @staticmethod
    def _transfer_line(evaluation: SpreadEvaluation) -> str:
        transfer = evaluation.transfer
        if transfer.status is TransferStatus.VERIFIED:
            network = esc(transfer.network or "?")
            return f"🔁 Transfer: ✅ verified via <b>{network}</b>"
        note = f" — {esc(transfer.note)}" if transfer.note else ""
        return (
            "⚠️ <b>Transfer path unverified</b>"
            f"{note}\n<i>Check deposit/withdrawal status manually before acting.</i>"
        )


class SystemEventFormatter:
    """Renders :data:`~nexus.domain.events.SystemEvent` messages."""

    def render(self, event: SystemEvent) -> str:
        """Render any system event."""
        match event:
            case ScannerStarted():
                return self._started(event)
            case ScannerStopped():
                return (
                    "🛑 <b>Nexus Spread Scanner stopped</b>\n"
                    f"<blockquote>{esc(event.reason)}</blockquote>"
                )
            case ExchangeDown():
                return (
                    f"⚠️ <b>{esc(exchange_name(event.exchange))} unreachable</b>\n"
                    f"{SEPARATOR}\n"
                    f"Consecutive failures: <b>{event.consecutive_failures}</b>\n"
                    f"<blockquote>{esc(event.error[:500])}</blockquote>"
                )
            case ExchangeRecovered():
                return (
                    f"✅ <b>{esc(exchange_name(event.exchange))} recovered</b>\n"
                    f"Downtime: <b>{event.downtime_s} s</b>"
                )

    @staticmethod
    def _started(event: ScannerStarted) -> str:
        exchanges = "\n".join(
            f"{'🔑' if e.authenticated else '🌐'} <b>{esc(exchange_name(e.name))}</b>"
            f" — {e.markets} markets"
            for e in event.exchanges
        )
        return _truncate(
            "\n".join(
                [
                    "🚀 <b>Nexus Spread Scanner started</b>",
                    SEPARATOR,
                    exchanges,
                    "",
                    f"🔗 Common symbols: <b>{event.common_symbols}</b>",
                    f"🎯 Threshold: <b>≥ {esc(event.min_net_profit_pct)}%</b> and "
                    f"<b>≥ ${esc(event.min_net_profit_usd)}</b> net",
                    f"📦 Reference size: <b>${esc(event.reference_notional_usd)}</b>",
                    "<blockquote>🔑 read-only API key · 🌐 public data only</blockquote>",
                ]
            )
        )
