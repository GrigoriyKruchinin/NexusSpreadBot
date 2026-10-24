"""Telegram HTML message templates (user-facing text is Russian).

Every dynamic value passes through :func:`esc` (``html.escape``): exchange-provided strings
(network codes, error texts) must never be able to inject markup.
"""

from __future__ import annotations

import html
from collections.abc import Collection
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from nexus.domain.conditional import conditional_legs
from nexus.domain.events import (
    AlertContext,
    EpisodeClosed,
    ExchangeDown,
    ExchangeRecovered,
    RoutesQuarantined,
    ScannerStarted,
    ScannerStopped,
    SystemEvent,
    WatchdogAlert,
    WatchdogRecovered,
    WatchdogRetired,
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
    "unverified_persistent": "спред держится, а маршрут перевода не подтверждён",
    "transfer_unavailable": "ввод или вывод монеты отключён",
}
EPISODE_CLOSE_REASONS: Final[dict[str, str]] = {
    "gap": "спред исчез",
    "quarantined": "связка отправлена в карантин",
    "restart": "сканер перезапускался",
}
WATCHDOG_TITLES: Final[dict[str, str]] = {
    "scanner": "Сканер",
    "backup": "Резервная копия",
    "paper_sets": "Paper-наборы",
}
PAPER_SET_CHECK_PREFIX: Final = "paper_set:"
WATCHDOG_REASONS: Final[dict[str, str]] = {
    "scanner_stale": "сканер не записывает данные уже {minutes} мин: проверьте контейнер scanner",
    "scanner_no_data": "в базе нет записей работы сканера",
    "backup_missing": "файл статуса резервного копирования не найден",
    "backup_unreadable": "файл статуса резервного копирования нечитаем",
    "backup_failed": "последняя резервная копия завершилась ошибкой ({minutes} мин назад)",
    "backup_not_copied": "копия дампа не сохранена вне контейнера (диск не подключён?)",
    "check_error": "проверка не выполняется (база данных или файл статуса недоступны)",
    "paper_set_stale": "данные paper-набора не обновляются {minutes} мин: проверьте логи сканера",
    "backup_stale": "последняя резервная копия была {minutes} мин назад",
}
STOP_REASONS: Final[dict[str, str]] = {
    "shutdown": "сканер остановлен или перезапускается (docker stop / make down-local)",
}


def watchdog_title(check: str) -> str:
    """Title of a check; a per-set check shows the set name only (``a-z0-9_``, validated)."""
    if check.startswith(PAPER_SET_CHECK_PREFIX):
        return f"Paper-набор {check.removeprefix(PAPER_SET_CHECK_PREFIX)}"
    return WATCHDOG_TITLES.get(check, check)


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
    """Russian short form: seconds, minutes + seconds, or hours + minutes."""
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{seconds} с"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин {secs:02d} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes:02d} мин"


def truncate(text: str) -> str:
    """Cut a message to Telegram's length limit."""
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return text
    return text[: TELEGRAM_MAX_LENGTH - 1] + "…"


class OpportunityFormatter:
    """Renders a profitable :class:`SpreadEvaluation` as a Telegram HTML alert."""

    def __init__(self, conditional_venues: Collection[str] = ()) -> None:
        self._conditional = tuple(conditional_venues)

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
            ("Комиссия покупки", fmt_usd(bd.fee_buy_usd)),
            ("Комиссия продажи", fmt_usd(bd.fee_sell_usd)),
            ("Проскальзывание", fmt_usd(bd.slippage_usd)),
            ("Перевод", self._transfer_cost(evaluation)),
        ]
        width = max(len(label) for label, _ in rows)
        table = "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)

        context = context or AlertContext()
        title = "Арбитражная возможность"
        if context.realert:
            title = f"Повтор №{context.realert}: спред растёт"
        legs = conditional_legs(
            evaluation.buy_exchange, evaluation.sell_exchange, self._conditional
        )
        marker = ""
        if legs:
            label = "условная биржа" if len(legs) == 1 else "условные биржи"
            marker = f"  ⚠️ {label} ({esc(', '.join(exchange_name(v) for v in legs))})"
        lines = [
            f"💹 <b>{esc(title)}</b> · <code>{esc(evaluation.symbol)}</code>{marker}",
            *(
                [
                    f"🔁 В прошлом алерте чистая прибыль была "
                    f"<b>{fmt_usd(Decimal(context.previous_net_usd), signed=True)}</b>"
                ]
                if context.realert and context.previous_net_usd
                else []
            ),
            SEPARATOR,
            f"🟢 <b>ПОКУПКА</b> на <b>{buy}</b> по <code>{fmt_price(bd.best_ask_buy)}</code>"
            f" · средняя <code>{fmt_price(bd.vwap_buy)}</code>",
            f"🔴 <b>ПРОДАЖА</b> на <b>{sell}</b> по <code>{fmt_price(bd.best_bid_sell)}</code>"
            f" · средняя <code>{fmt_price(bd.vwap_sell)}</code>",
            "",
            f"💰 <b>Чистая прибыль: {fmt_usd(bd.net_profit_usd, signed=True)}"
            f" ({fmt_pct(bd.net_profit_pct)})</b>",
            f"📈 Спред до издержек: <b>{fmt_pct(bd.gross_spread_pct)}</b>",
            f"📦 Объём: <b>{fmt_usd(bd.cost_quote)}</b> {quote} → "
            f"<b>{fmt_amount(bd.base_bought)}</b> {base}",
            SEPARATOR,
            "🧾 <b>Издержки</b>",
            f"<pre>{esc(table)}</pre>",
            self._transfer_line(evaluation),
            *(
                ["ℹ️ <i>Комиссия тейкера оценочная (биржа не отдаёт её по паре).</i>"]
                if evaluation.fees_estimated
                else []
            ),
            f"<blockquote>⏱ Возраст стаканов: {evaluation.buy_book_age_ms} мс / "
            f"{evaluation.sell_book_age_ms} мс\n"
            f"🕒 {fmt_time(evaluation.evaluated_at_ms)}</blockquote>",
        ]
        return truncate("\n".join(lines))

    @staticmethod
    def _transfer_cost(evaluation: SpreadEvaluation) -> str:
        bd = evaluation.breakdown
        if bd is None:
            return "н/д"
        if not evaluation.transfer_verified:
            # Only a per-asset chain tax can be priced without a verified network.
            return f"{fmt_usd(bd.transfer_fee_usd)} налог + н/д" if bd.transfer_fee_usd else "н/д"
        return fmt_usd(bd.transfer_fee_usd)

    @staticmethod
    def _transfer_line(evaluation: SpreadEvaluation) -> str:
        transfer = evaluation.transfer
        if transfer.status is TransferStatus.VERIFIED:
            network = esc(transfer.network or "?")
            return f"🔁 Перевод: ✅ подтверждён, сеть <b>{network}</b>"
        note = f" — {esc(transfer.note)}" if transfer.note else ""
        return (
            "⚠️ <b>Маршрут перевода не подтверждён</b>"
            f"{note}\n<i>Перед действием проверьте статус ввода/вывода вручную.</i>"
        )


class SystemEventFormatter:
    """Renders :data:`~nexus.domain.events.SystemEvent` messages."""

    def render(self, event: SystemEvent) -> str:
        """Render any system event."""
        match event:
            case ScannerStarted():
                return self._started(event)
            case ScannerStopped():
                reason = STOP_REASONS.get(event.reason, event.reason)
                return (
                    "🛑 <b>Nexus Spread Scanner остановлен</b>\n"
                    f"<blockquote>{esc(reason)}</blockquote>"
                )
            case ExchangeDown():
                return (
                    f"⚠️ <b>{esc(exchange_name(event.exchange))} недоступна</b>\n"
                    f"{SEPARATOR}\n"
                    f"Ошибок подряд: <b>{event.consecutive_failures}</b>\n"
                    f"<blockquote>{esc(event.error[:500])}</blockquote>"
                )
            case ExchangeRecovered():
                return (
                    f"✅ <b>{esc(exchange_name(event.exchange))} снова доступна</b>\n"
                    f"Простой: <b>{event.downtime_s} с</b>"
                )
            case EpisodeClosed():
                return self._episode_closed(event)
            case RoutesQuarantined():
                return self._quarantined(event)
            case WatchdogAlert():
                return self._watchdog_alert(event)
            case WatchdogRecovered():
                title = watchdog_title(event.check)
                return (
                    f"✅ <b>{esc(title)}: проблема устранена</b>\n"
                    f"Длилась около <b>{fmt_duration(event.downtime_min * 60)}</b>"
                )
            case WatchdogRetired():
                name = watchdog_title(event.check)
                return (
                    f"ℹ️ <b>{esc(name)} больше не отслеживается</b>\n"
                    f"Данных нет более {event.hours} ч, считаю удалённым из конфигурации. "
                    "Проверьте, нужен ли он."
                )

    @staticmethod
    def _watchdog_alert(event: WatchdogAlert) -> str:
        title = watchdog_title(event.check)
        template = WATCHDOG_REASONS.get(event.reason, "неизвестная причина: {minutes}")
        text = template.format(minutes="?" if event.minutes is None else event.minutes)
        return f"🚨 <b>{esc(title)}: нужна проверка</b>\n<blockquote>{esc(text)}</blockquote>"

    @staticmethod
    def _quarantined(event: RoutesQuarantined) -> str:
        shown = event.routes[:QUARANTINE_ROUTES_SHOWN]
        lines = [
            f"🚫 <b>В карантин отправлено связок: {len(event.routes)}</b>"
            f" на <b>{event.duration_h} ч</b>",
            "<i>Алертов и проверки стаканов по ним не будет; карантин снимется раньше, "
            "если маршрут перевода подтвердится.</i>",
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
            lines.append(f"… и ещё {hidden}")
        return truncate("\n".join(lines))

    @staticmethod
    def _episode_closed(event: EpisodeClosed) -> str:
        survived = {True: "✅ да", False: "❌ нет", None: "н/д"}[event.survived_latency]
        peak_usd = fmt_usd(Decimal(event.peak_net_usd), signed=True)
        peak_pct = fmt_pct(Decimal(event.peak_net_pct))
        return "\n".join(
            [
                f"🏁 <b>Возможность закрылась</b> · <code>{esc(event.symbol)}</code>",
                f"{esc(exchange_name(event.buy_exchange))} → "
                f"{esc(exchange_name(event.sell_exchange))}",
                SEPARATOR,
                f"⏱ Длительность: <b>{fmt_duration(event.duration_s)}</b>"
                f" · проверок: {event.evaluations}",
                f"💰 Максимум чистой прибыли: <b>{peak_usd} ({peak_pct})</b>",
                f"⚡ Пережила задержку исполнения: <b>{survived}</b>",
                *([f"🔁 Повторных алертов: {event.realerts}"] if event.realerts else []),
                f"<blockquote>Причина закрытия: "
                f"{esc(EPISODE_CLOSE_REASONS.get(event.reason, event.reason))}</blockquote>",
            ]
        )

    @staticmethod
    def _started(event: ScannerStarted) -> str:
        exchanges = "\n".join(
            f"{'🔑' if e.authenticated else '🌐'} <b>{esc(exchange_name(e.name))}</b>"
            f" — рынков: {e.markets}"
            + (
                f" · переводы {e.transfer_coverage_pct}%"
                if e.transfer_coverage_pct is not None
                else ""
            )
            for e in event.exchanges
        )
        unbound = ", ".join(esc(v) for v in event.ip_unbound_venues)
        return truncate(
            "\n".join(
                [
                    "🚀 <b>Nexus Spread Scanner запущен</b>",
                    SEPARATOR,
                    exchanges,
                    "",
                    f"🔗 Общих пар: <b>{event.common_symbols}</b>",
                    f"🎯 Порог: чистая прибыль <b>≥ {esc(event.min_net_profit_pct)}%</b> и "
                    f"<b>≥ ${esc(event.min_net_profit_usd)}</b>",
                    f"📦 Расчётный объём: <b>${esc(event.reference_notional_usd)}</b>",
                    "<blockquote>🔑 ключ только для чтения"
                    " · 🌐 только публичные данные</blockquote>",
                    *(
                        [f"⚠️ Ключи без привязки к IP (разрешено для локального запуска): {unbound}"]
                        if unbound
                        else []
                    ),
                ]
            )
        )
