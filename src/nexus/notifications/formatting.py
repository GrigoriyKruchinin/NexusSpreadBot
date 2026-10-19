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
    AlertContext,
    EpisodeClosed,
    ExchangeDown,
    ExchangeRecovered,
    RoutesQuarantined,
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
    "mexc": "MEXC",
    "bitget": "Bitget",
}


QUARANTINE_ROUTES_SHOWN: Final = 10
QUARANTINE_REASONS: Final[dict[str, str]] = {
    "unverified_persistent": "spread persists without a verified transfer path",
    "transfer_unavailable": "deposits/withdrawals are disabled",
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


def fmt_duration(seconds: int) -> str:
    """``45s`` / ``3m 20s`` / ``2h 05m``."""
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def truncate(text: str) -> str:
    """Cut a message to Telegram's length limit."""
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return text
    return text[: TELEGRAM_MAX_LENGTH - 1] + "…"


class OpportunityFormatter:
    """Renders a profitable :class:`SpreadEvaluation` as a Telegram HTML alert."""

    def render(self, evaluation: SpreadEvaluation, context: AlertContext | None = None) -> str:
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

        context = context or AlertContext()
        title = "Arbitrage Opportunity"
        if context.realert:
            title = f"Re-alert #{context.realert}: spread is growing"
        lines = [
            f"💹 <b>{esc(title)}</b> · <code>{esc(evaluation.symbol)}</code>",
            *(
                [
                    f"🔁 Net was <b>{fmt_usd(Decimal(context.previous_net_usd), signed=True)}"
                    "</b> at the previous alert"
                ]
                if context.realert and context.previous_net_usd
                else []
            ),
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
        return truncate("\n".join(lines))

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
            case EpisodeClosed():
                return self._episode_closed(event)
            case RoutesQuarantined():
                return self._quarantined(event)

    @staticmethod
    def _quarantined(event: RoutesQuarantined) -> str:
        shown = event.routes[:QUARANTINE_ROUTES_SHOWN]
        lines = [
            f"🚫 <b>{len(event.routes)} route(s) quarantined</b> for <b>{event.duration_h} h</b>",
            "<i>No alerts and no order-book checks; lifted early if the transfer path "
            "becomes verified.</i>",
            SEPARATOR,
        ]
        for route in shown:
            why = QUARANTINE_REASONS.get(route.reason, route.reason)
            lines.append(
                f"• <code>{esc(route.symbol)}</code> {esc(exchange_name(route.buy_exchange))}"
                f" → {esc(exchange_name(route.sell_exchange))}: {esc(why)}"
            )
            if route.note:
                lines.append(f"  <i>{esc(route.note[:200])}</i>")
        if hidden := len(event.routes) - len(shown):
            lines.append(f"… and {hidden} more")
        return truncate("\n".join(lines))

    @staticmethod
    def _episode_closed(event: EpisodeClosed) -> str:
        survived = {True: "✅ yes", False: "❌ no", None: "n/a"}[event.survived_latency]
        peak_usd = fmt_usd(Decimal(event.peak_net_usd), signed=True)
        peak_pct = fmt_pct(Decimal(event.peak_net_pct))
        return "\n".join(
            [
                f"🏁 <b>Opportunity closed</b> · <code>{esc(event.symbol)}</code>",
                f"{esc(exchange_name(event.buy_exchange))} → "
                f"{esc(exchange_name(event.sell_exchange))}",
                SEPARATOR,
                f"⏱ Duration: <b>{fmt_duration(event.duration_s)}</b>"
                f" · {event.evaluations} evaluations",
                f"💰 Peak net: <b>{peak_usd} ({peak_pct})</b>",
                f"⚡ Survived execution latency: <b>{survived}</b>",
                *([f"🔁 Re-alerts: {event.realerts}"] if event.realerts else []),
                f"<blockquote>Closed: {esc(event.reason)}</blockquote>",
            ]
        )

    @staticmethod
    def _started(event: ScannerStarted) -> str:
        exchanges = "\n".join(
            f"{'🔑' if e.authenticated else '🌐'} <b>{esc(exchange_name(e.name))}</b>"
            f" — {e.markets} markets"
            + (
                f" · transfers {e.transfer_coverage_pct}%"
                if e.transfer_coverage_pct is not None
                else ""
            )
            for e in event.exchanges
        )
        return truncate(
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
