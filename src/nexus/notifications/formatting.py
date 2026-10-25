"""Telegram HTML message templates (alerts: en|ru via the catalog; system events: Russian).

Every dynamic value passes through :func:`esc` (``html.escape``): exchange-provided strings
(network codes, error texts) must never be able to inject markup.
"""

from __future__ import annotations

import html
import re
from collections.abc import Collection
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from nexus.domain.conditional import conditional_legs
from nexus.domain.events import (
    AlertContext,
    AlertTransfer,
    EpisodeClosed,
    ExchangeDown,
    ExchangeRecovered,
    RoutesQuarantined,
    ScannerStarted,
    ScannerStopped,
    SystemEvent,
    WatchdogAlert,
    WatchdogRecovered,
)
from nexus.domain.spread import SpreadBreakdown, SpreadEvaluation, TransferStatus
from nexus.notifications.alert_catalog import DEFAULT_LANGUAGE, catalog

SEPARATOR: Final = "━━━━━━━━━━━━━━━━━━━━"
TELEGRAM_MAX_LENGTH: Final = 4096
JUST_OPENED_S: Final = 10

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
}
WATCHDOG_REASONS: Final[dict[str, str]] = {
    "scanner_stale": "сканер не записывает данные уже {minutes} мин: проверьте контейнер scanner",
    "scanner_no_data": "в базе нет записей работы сканера",
    "backup_missing": "файл статуса резервного копирования не найден",
    "backup_unreadable": "файл статуса резервного копирования нечитаем",
    "backup_failed": "последняя резервная копия завершилась ошибкой ({minutes} мин назад)",
    "backup_not_copied": "копия дампа не сохранена вне контейнера (диск не подключён?)",
    "check_error": "проверка не выполняется (база данных или файл статуса недоступны)",
    "backup_stale": "последняя резервная копия была {minutes} мин назад",
}
STOP_REASONS: Final[dict[str, str]] = {
    "shutdown": "сканер остановлен или перезапускается (docker stop / make down)",
}


def watchdog_title(check: str) -> str:
    """Human title of a check."""
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


def signed_pct(value: Decimal) -> str:
    """``+1.12 %`` (explicit sign, space before the percent sign as in the alert templates)."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{'+' if rounded >= 0 else '-'}{abs(rounded)} %"


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


_TAG_RE: Final = re.compile(r"<(/?)([a-z][a-z0-9-]*)[^<>]*>")
_PARTIAL_TAIL_RE: Final = re.compile(r"(<[^<>]*|&[#a-zA-Z0-9]{0,10})$")


def truncate(text: str) -> str:
    """Cut a message to Telegram's length limit without breaking its HTML.

    A cut tag or entity is dropped and the tags still open are closed again, otherwise Telegram
    answers 400 (permanent rejection) for the whole message.
    """
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return text
    reserve = 64  # room for the ellipsis and the closing tags
    cut = _PARTIAL_TAIL_RE.sub("", text[: TELEGRAM_MAX_LENGTH - reserve])
    open_tags: list[str] = []
    for closing, name in _TAG_RE.findall(cut):
        if not closing:
            open_tags.append(name)
        elif name in open_tags:
            del open_tags[open_tags.index(name) :]
    return cut + "…" + "".join(f"</{name}>" for name in reversed(open_tags))


class OpportunityFormatter:
    """Renders the opportunity alert templates NEW / UPDATE / CLOSED in ``en`` or ``ru``.

    The templates are compact lines (no ``<pre>`` tables, which break on mobile). Every dynamic
    value is escaped; every fixed string comes from :mod:`nexus.notifications.alert_catalog`.
    Edit-in-place delivery (replacing a sent NEW by UPDATE / CLOSED) is not done here.
    """

    def __init__(
        self, conditional_venues: Collection[str] = (), language: str = DEFAULT_LANGUAGE
    ) -> None:
        self._conditional = tuple(conditional_venues)
        self._t = catalog(language)

    def render(
        self,
        evaluation: SpreadEvaluation,
        context: AlertContext | None = None,
        *,
        peak_net_pct: Decimal | None = None,
    ) -> str:
        """NEW for an episode's first alert, UPDATE for its re-alerts."""
        context = context or AlertContext()
        if context.realert:
            return self.render_update(evaluation, context, peak_net_pct=peak_net_pct)
        return self.render_new(evaluation, context)

    def render_new(self, evaluation: SpreadEvaluation, context: AlertContext | None = None) -> str:
        """Template NEW."""
        return self._compose("title_new", evaluation, context or AlertContext(), None)

    def render_update(
        self,
        evaluation: SpreadEvaluation,
        context: AlertContext | None = None,
        *,
        peak_net_pct: Decimal | None = None,
    ) -> str:
        """Template UPDATE: the NEW body with current numbers and the lifetime with the peak."""
        return self._compose("title_update", evaluation, context or AlertContext(), peak_net_pct)

    def render_closed(
        self,
        evaluation: SpreadEvaluation,
        context: AlertContext | None = None,
        *,
        peak_net_pct: Decimal | None = None,
    ) -> str:
        """Template CLOSED from the last seen evaluation (transfer and flags stay as last seen)."""
        context = context or AlertContext()
        bd = self._breakdown(evaluation)
        t = self._t
        if context.lifetime is not None:
            duration = self._duration(context.lifetime.lifetime_ms() // 1000)
            summary = (
                t["closed_summary"].format(
                    duration=duration,
                    peak=signed_pct(peak_net_pct),
                    last=signed_pct(bd.net_profit_pct),
                )
                if peak_net_pct is not None
                else t["closed_summary_nopeak"].format(duration=duration)
            )
        else:
            summary = ""
        lines = [
            t["title_closed"].format(coin=esc(evaluation.base), quote=esc(evaluation.quote)),
            *self._venue_lines(evaluation, bd),
            *self._transfer_lines(evaluation, context, bd),
            self._footer(summary, context),
        ]
        return truncate("\n".join(line for line in lines if line))

    def render_suppressed(self, count: int, limit: int) -> str:
        """The one collapsed message for alerts over the hourly cap."""
        return self._t["suppressed"].format(n=count, limit=limit)

    def _compose(
        self,
        title_key: str,
        evaluation: SpreadEvaluation,
        context: AlertContext,
        peak_net_pct: Decimal | None,
    ) -> str:
        bd = self._breakdown(evaluation)
        t = self._t
        title = t[title_key].format(
            coin=esc(evaluation.base),
            quote=esc(evaluation.quote),
            net_pct=signed_pct(bd.net_profit_pct),
        )
        net = t["net"].format(
            net_pct=signed_pct(bd.net_profit_pct),
            net_usd=fmt_usd(bd.net_profit_usd, signed=True),
            notional=fmt_usd(bd.cost_quote).removesuffix(".00"),
        )
        lines = [
            title + self._conditional_marker(evaluation),
            *self._venue_lines(evaluation, bd),
            net,
            *([t["fees_estimated"]] if evaluation.fees_estimated else []),
            *self._transfer_lines(evaluation, context, bd),
            self._footer(self._lifetime_text(context, peak_net_pct), context),
        ]
        return truncate("\n".join(line for line in lines if line))

    @staticmethod
    def _breakdown(evaluation: SpreadEvaluation) -> SpreadBreakdown:
        if evaluation.breakdown is None:
            msg = "cannot render an opportunity without a cost breakdown"
            raise ValueError(msg)
        return evaluation.breakdown

    def _conditional_marker(self, evaluation: SpreadEvaluation) -> str:
        legs = conditional_legs(
            evaluation.buy_exchange, evaluation.sell_exchange, self._conditional
        )
        if not legs:
            return ""
        key = "conditional_one" if len(legs) == 1 else "conditional_many"
        return "  " + self._t[key].format(venues=esc(", ".join(exchange_name(v) for v in legs)))

    def _venue_lines(self, evaluation: SpreadEvaluation, bd: SpreadBreakdown) -> list[str]:
        t = self._t
        return [
            f"{t['buy']} <b>{esc(exchange_name(evaluation.buy_exchange))}</b>"
            f"  {fmt_price(bd.best_ask_buy)}",
            f"{t['sell']} <b>{esc(exchange_name(evaluation.sell_exchange))}</b>"
            f"  {fmt_price(bd.best_bid_sell)}",
        ]

    def _transfer_lines(
        self, evaluation: SpreadEvaluation, context: AlertContext, bd: SpreadBreakdown
    ) -> list[str]:
        t = self._t
        coin = esc(evaluation.base)
        volume = context.volume
        quote = fmt_usd(Decimal(volume.max_quote) if volume else bd.cost_quote)
        base = fmt_amount(Decimal(volume.max_base) if volume else bd.base_bought)
        lines = [
            t["volume" if volume else "volume_scanned"].format(
                quote=quote.removesuffix(".00"), base=base, coin=coin
            )
        ]
        transfer = (
            context.transfer
            or AlertContext.build(evaluation, None).transfer
            or AlertTransfer(status=evaluation.transfer.status.value)
        )
        note = f" — {esc(transfer.note)}" if transfer.note else ""
        if transfer.status == TransferStatus.VERIFIED.value:
            fee_usd = (
                t["fee_usd"].format(usd=fmt_usd(Decimal(transfer.fee_usd)))
                if transfer.fee_usd is not None
                else ""
            )
            time = (
                t["time"].format(minutes=self._minutes(Decimal(transfer.est_arrival_min)))
                if transfer.est_arrival_min is not None
                else t["time_unknown"]
            )
            lines.append(
                t["transfer_ok"].format(
                    network=esc(transfer.network or "?"),
                    fee_base=fmt_amount(Decimal(transfer.fee_base or 0)),
                    coin=coin,
                    fee_usd=fee_usd,
                    time=time,
                )
            )
        elif transfer.status == TransferStatus.UNAVAILABLE.value:
            lines.append(t["transfer_unavailable"].format(note=note))
        else:
            lines.append(t["transfer_unverified"].format(note=note))
        states = (transfer.withdraw, transfer.deposit)
        lines.append(
            t["flags"].format(
                buy=esc(exchange_name(evaluation.buy_exchange)),
                sell=esc(exchange_name(evaluation.sell_exchange)),
                w=t.get(f"flag_{transfer.withdraw}", t["flag_unknown"]),
                d=t.get(f"flag_{transfer.deposit}", t["flag_unknown"]),
            )
        )
        if "closed" in states or transfer.status == TransferStatus.UNAVAILABLE.value:
            lines.append(t["hint_closed"])
        elif transfer.status != TransferStatus.VERIFIED.value or "unknown" in states:
            lines.append(t["hint_unverified"])
        return lines

    def _footer(self, text: str, context: AlertContext) -> str:
        parts = [text] if text else []
        if context.episode_id is not None:
            parts.append(self._t["episode"].format(episode=context.episode_id))
        return "   ·   ".join(parts)

    def _lifetime_text(self, context: AlertContext, peak_net_pct: Decimal | None) -> str:
        t = self._t
        lifetime = context.lifetime
        if lifetime is None:
            return ""
        seconds = lifetime.lifetime_ms() // 1000
        if not context.realert and seconds < JUST_OPENED_S:
            return t["lifetime_new"]
        duration = self._duration(seconds)
        if peak_net_pct is None:
            return t["lifetime"].format(duration=duration)
        return t["lifetime_peak"].format(duration=duration, peak=signed_pct(peak_net_pct))

    def _duration(self, seconds: int) -> str:
        t = self._t
        seconds = max(seconds, 0)
        if seconds < 60:
            return t["d_sec"].format(s=seconds)
        minutes, secs = divmod(seconds, 60)
        if minutes < 60:
            return t["d_min"].format(m=minutes, s=secs)
        hours, minutes = divmod(minutes, 60)
        return t["d_hour"].format(h=hours, m=minutes)

    def _minutes(self, minutes: Decimal) -> str:
        return self._t["min"].format(n=fmt_amount(minutes.quantize(Decimal("0.1"))))


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
        fallback = ", ".join(esc(v) for v in event.public_fallback_venues)
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
                        [
                            "⚠️ Ключ НЕ использован (не прошёл проверку «только чтение»), "
                            f"биржа работает в публичном режиме: {fallback}"
                        ]
                        if fallback
                        else []
                    ),
                    *(
                        [f"ℹ️ Привязка ключей к IP не подтверждена (рекомендуется): {unbound}"]
                        if unbound
                        else []
                    ),
                ]
            )
        )
