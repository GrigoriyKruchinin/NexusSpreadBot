"""Daily digest template (Telegram HTML, Russian; every dynamic value is escaped)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

from nexus.domain.digest import DigestData, EpisodeStats, PaperStats, PortfolioSummary
from nexus.notifications.formatting import (
    QUARANTINE_REASONS,
    SEPARATOR,
    esc,
    exchange_name,
    fmt_duration,
    fmt_pct,
    fmt_usd,
    truncate,
)

QUARANTINES_SHOWN: Final = 5
SKIP_REASONS: Final[dict[str, str]] = {
    "insufficient_usdt": "не хватает USDT",
    "insufficient_coin": "не хватает монеты",
    "rebalance_in_flight": "идёт виртуальный перевод",
    "no_rebalance_path": "нет пути пополнения",
    "spread_gone": "спред исчез за время задержки",
    "books_unavailable": "стаканы недоступны",
    "unfillable": "стакан не подходит (тонкий/устарел/ниже минимума)",
    "no_price": "нет цены монеты",
    "recent_fill": "связка только что торговалась",
}
MIN_PORTFOLIOS_SHOWN: Final = 2
LATENCY_MARK: Final[dict[bool | None, str]] = {True: " ⚡", False: " 🐢", None: ""}


class DigestFormatter:
    """Renders :class:`DigestData` for a time zone."""

    def render(self, data: DigestData, tz: str) -> str:
        """Render the digest."""
        zone = ZoneInfo(tz)

        def local(epoch_ms: int) -> str:
            return datetime.fromtimestamp(epoch_ms / 1000, tz=zone).strftime("%d %b %H:%M")

        lines = [
            "📊 <b>Ежедневный дайджест</b>",
            f"<i>{local(data.window_start_ms)} → {local(data.window_end_ms)} ({esc(tz)})</i>",
            *self._conditional(data),
            SEPARATOR,
            *self._episodes(data.episodes),
            SEPARATOR,
            *self._paper(data.paper),
            *self._portfolios(data.portfolios, local),
            SEPARATOR,
            *self._quarantine(data),
            SEPARATOR,
            *self._exchanges(data),
            f"<blockquote>Неподтверждённые возможности (записаны, без алертов): "
            f"{data.unverified_evaluations}</blockquote>",
        ]
        return truncate("\n".join(lines))

    @staticmethod
    def _conditional(data: DigestData) -> list[str]:
        """Conditional-venue note and the two combined totals (all / excluding conditional)."""
        paper = data.paper
        if not data.conditional_venues:
            return [
                "Условные биржи: нет",
                SEPARATOR,
                f"Эпизоды:   все {data.episodes.total}",
                "Бумажный P&amp;L (hedged): "
                + (f"все {fmt_usd(paper.hedged_pnl_usd, signed=True)}" if paper else "н/д"),
            ]
        excl = paper.hedged_pnl_excl_conditional_usd if paper else None
        excl_text = "н/д" if excl is None else f"≈ {fmt_usd(excl, signed=True)} (оценка)"
        ep_excl = data.episodes.total_excl_conditional
        names = ", ".join(esc(exchange_name(v)) for v in data.conditional_venues)
        return [
            f"⚠️ Условные биржи (данные собираются, торговать пока нельзя): {names}",
            SEPARATOR,
            f"Эпизоды:   все {data.episodes.total} | без условных "
            f"(фильтр) {'н/д' if ep_excl is None else ep_excl}",
            "Бумажный P&amp;L (hedged): "
            + (
                f"все {fmt_usd(paper.hedged_pnl_usd, signed=True)} "
                f"| без условных (фильтр) {excl_text}"
                if paper
                else "н/д"
            ),
        ]

    @staticmethod
    def _portfolios(
        portfolios: tuple[PortfolioSummary, ...], local: Callable[[int], str]
    ) -> list[str]:
        """Per-set simulation lines, only once more than one set has records."""
        if len(portfolios) < MIN_PORTFOLIOS_SHOWN:
            return []
        lines = [SEPARATOR, "📦 <b>Наборы бирж</b> (реальная симуляция по набору)"]
        for p in portfolios:
            since = datetime.fromtimestamp(p.since_ms / 1000, tz=ZoneInfo("UTC"))
            lines.append(
                f"• <code>{esc(p.portfolio_id)}</code> с {since:%d %b}: сделок {p.trades}"
                f" · hedged {fmt_usd(p.hedged_pnl_usd, signed=True)}"
            )
        lines.append(
            "<blockquote>Данные набора копятся только с момента добавления набора: "
            "без истории назад. Строки «фильтр» выше - оценка по уже записанным сделкам."
            "</blockquote>"
        )
        return lines

    @staticmethod
    def _episodes(stats: EpisodeStats) -> list[str]:
        lines = [
            f"🔀 <b>Эпизодов возможностей: {stats.total}</b>",
            f"✅ подтверждённых {stats.verified} · ⚠️ неподтверждённых {stats.unverified}"
            f" · 🚫 в карантине {stats.quarantined}",
        ]
        if not stats.total:
            return lines
        lines.append(
            f"⚡ Пережили задержку: <b>{stats.survived_latency}</b> из {stats.latency_checked}"
            " проверенных"
        )
        if stats.median_duration_s is not None and stats.max_duration_s is not None:
            lines.append(
                f"⏱ Длительность: медиана {fmt_duration(stats.median_duration_s)}"
                f" · максимум {fmt_duration(stats.max_duration_s)}"
            )
        if stats.top:
            lines.append("<b>Топ связок по пиковой чистой прибыли</b>")
            for rank, e in enumerate(stats.top, start=1):
                lines.append(
                    f"{rank}. <code>{esc(e.symbol)}</code> {esc(exchange_name(e.buy_exchange))}"
                    f" → {esc(exchange_name(e.sell_exchange))} — "
                    f"<b>{fmt_usd(e.peak_net_usd, signed=True)}</b>"
                    f" ({fmt_pct(e.peak_net_pct)}) · {fmt_duration(e.duration_s)}"
                    f"{LATENCY_MARK[e.survived_latency]}"
                )
        return lines

    @staticmethod
    def _paper(paper: PaperStats | None) -> list[str]:
        if paper is None:
            return ["📝 <b>Бумажная торговля</b>: пока нет активности"]
        skipped = ", ".join(
            f"{esc(SKIP_REASONS.get(k, k))} {v}" for k, v in sorted(paper.skipped.items())
        )
        roc, hedged_roc = paper.roc_pct, paper.hedged_roc_pct
        return [
            "📝 <b>Бумажная торговля</b>",
            f"Сделок: <b>{paper.trades}</b>" + (f" · пропущено: {skipped}" if skipped else ""),
            f"За 24 ч: заработано <b>{fmt_usd(paper.realized_usd, signed=True)}</b>"
            f" · переводы {fmt_usd(-paper.rebalance_usd, signed=True)} ({paper.rebalances})"
            + (f" · заблокировано {paper.blocked_rebalances}" if paper.blocked_rebalances else ""),
            f"С начала: P&amp;L <b>{fmt_usd(paper.total_pnl_usd, signed=True)}</b>"
            f" = арбитраж {fmt_usd(paper.realized_total_usd, signed=True)}"
            f" − переводы {fmt_usd(paper.rebalance_total_usd)}"
            f" + переоценка {fmt_usd(paper.mark_to_market_usd, signed=True)}",
            f"Капитал {fmt_usd(paper.capital_usd)} · доходность "
            + (f"<b>{_signed_pct(roc)}</b>" if roc is not None else "н/д"),
            f"🛡 С хеджем (без ценового риска инвентаря): <b>"
            f"{fmt_usd(paper.hedged_pnl_usd, signed=True)}</b>"
            + (f" · доходность <b>{_signed_pct(hedged_roc)}</b>" if hedged_roc is not None else ""),
        ]

    @staticmethod
    def _quarantine(data: DigestData) -> list[str]:
        lines = [
            f"🚫 <b>Карантин</b>: новых {len(data.quarantines)}"
            f" · активных {data.active_quarantines}"
        ]
        for q in data.quarantines[:QUARANTINES_SHOWN]:
            why = QUARANTINE_REASONS.get(q.reason, q.reason)
            lines.append(
                f"• <code>{esc(q.symbol)}</code> {esc(exchange_name(q.buy_exchange))}"
                f" → {esc(exchange_name(q.sell_exchange))}: {esc(why)}"
            )
        hidden = len(data.quarantines) - QUARANTINES_SHOWN
        if hidden > 0:
            lines.append(f"… и ещё {hidden}")
        return lines

    @staticmethod
    def _exchanges(data: DigestData) -> list[str]:
        names = sorted(set(data.uptime_pct) | set(data.coverage_pct))
        if not names:
            return ["🌐 <b>Биржи</b>: нет данных"]
        width = max(len("Биржа"), *(len(exchange_name(n)) for n in names))
        rows = [f"{'Биржа'.ljust(width)}  Аптайм  Переводы"]
        for name in names:
            uptime = _pct_cell(data.uptime_pct.get(name))
            coverage = _pct_cell(data.coverage_pct.get(name))
            rows.append(f"{exchange_name(name).ljust(width)}  {uptime:>6}  {coverage:>8}")
        return ["🌐 <b>Биржи</b>", f"<pre>{esc(chr(10).join(rows))}</pre>"]


def _pct_cell(value: int | None) -> str:
    return "н/д" if value is None else f"{value}%"


def _signed_pct(value: Decimal) -> str:
    text = fmt_pct(value)
    return text if value < 0 else f"+{text}"
