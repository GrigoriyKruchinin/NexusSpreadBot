"""Daily digest template (Telegram HTML, Russian; every dynamic value is escaped)."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from nexus.domain.digest import (
    DigestData,
    EpisodeStats,
)
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
            *self._quarantine(data),
            SEPARATOR,
            *self._exchanges(data),
            f"<blockquote>Неподтверждённые возможности (записаны, без алертов): "
            f"{data.unverified_evaluations}</blockquote>",
        ]
        return truncate("\n".join(lines))

    @staticmethod
    def _conditional(data: DigestData) -> list[str]:
        """Conditional-venue note and the episode totals (all / excluding conditional)."""
        if not data.conditional_venues:
            return ["Условные биржи: нет", SEPARATOR, f"Эпизоды:   все {data.episodes.total}"]
        ep_excl = data.episodes.total_excl_conditional
        names = ", ".join(esc(exchange_name(v)) for v in data.conditional_venues)
        return [
            f"⚠️ Условные биржи (данные собираются, торговать пока нельзя): {names}",
            SEPARATOR,
            f"Эпизоды:   все {data.episodes.total} | без условных "
            f"(фильтр) {'н/д' if ep_excl is None else ep_excl}",
        ]

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
