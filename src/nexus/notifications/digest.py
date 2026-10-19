"""Daily digest template (Telegram HTML; every dynamic value is escaped)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

from nexus.domain.digest import DigestData, EpisodeStats, PaperStats
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
            "📊 <b>Daily digest</b>",
            f"<i>{local(data.window_start_ms)} → {local(data.window_end_ms)} ({esc(tz)})</i>",
            SEPARATOR,
            *self._episodes(data.episodes),
            SEPARATOR,
            *self._paper(data.paper),
            SEPARATOR,
            *self._quarantine(data),
            SEPARATOR,
            *self._exchanges(data),
            f"<blockquote>Unverified opportunities (stored, not alerted): "
            f"{data.unverified_evaluations}</blockquote>",
        ]
        return truncate("\n".join(lines))

    @staticmethod
    def _episodes(stats: EpisodeStats) -> list[str]:
        lines = [
            f"🔀 <b>Opportunity episodes: {stats.total}</b>",
            f"✅ verified {stats.verified} · ⚠️ unverified {stats.unverified}"
            f" · 🚫 quarantined {stats.quarantined}",
        ]
        if not stats.total:
            return lines
        lines.append(
            f"⚡ Survived latency: <b>{stats.survived_latency}</b> of {stats.latency_checked}"
            " checked"
        )
        if stats.median_duration_s is not None and stats.max_duration_s is not None:
            lines.append(
                f"⏱ Duration: median {fmt_duration(stats.median_duration_s)}"
                f" · max {fmt_duration(stats.max_duration_s)}"
            )
        if stats.top:
            lines.append("<b>Top routes by peak net</b>")
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
            return ["📝 <b>Paper trading</b>: no activity yet"]
        skipped = ", ".join(f"{esc(k)} {v}" for k, v in sorted(paper.skipped.items()))
        roc = paper.roc_pct
        return [
            "📝 <b>Paper trading</b>",
            f"Trades: <b>{paper.trades}</b>" + (f" · skipped: {skipped}" if skipped else ""),
            f"24h: realized <b>{fmt_usd(paper.realized_usd, signed=True)}</b>"
            f" · transfers {fmt_usd(-paper.rebalance_usd, signed=True)} ({paper.rebalances})"
            + (f" · blocked {paper.blocked_rebalances}" if paper.blocked_rebalances else ""),
            f"Since start: P&amp;L <b>{fmt_usd(paper.total_pnl_usd, signed=True)}</b>"
            f" = realized {fmt_usd(paper.realized_total_usd, signed=True)}"
            f" − transfers {fmt_usd(paper.rebalance_total_usd)}"
            f" + MTM {fmt_usd(paper.mark_to_market_usd, signed=True)}",
            f"Capital {fmt_usd(paper.capital_usd)} · ROC "
            + (f"<b>{_signed_pct(roc)}</b>" if roc is not None else "n/a"),
        ]

    @staticmethod
    def _quarantine(data: DigestData) -> list[str]:
        lines = [
            f"🚫 <b>Quarantine</b>: {len(data.quarantines)} new · {data.active_quarantines} active"
        ]
        for q in data.quarantines[:QUARANTINES_SHOWN]:
            why = QUARANTINE_REASONS.get(q.reason, q.reason)
            lines.append(
                f"• <code>{esc(q.symbol)}</code> {esc(exchange_name(q.buy_exchange))}"
                f" → {esc(exchange_name(q.sell_exchange))}: {esc(why)}"
            )
        hidden = len(data.quarantines) - QUARANTINES_SHOWN
        if hidden > 0:
            lines.append(f"… and {hidden} more")
        return lines

    @staticmethod
    def _exchanges(data: DigestData) -> list[str]:
        names = sorted(set(data.uptime_pct) | set(data.coverage_pct))
        if not names:
            return ["🌐 <b>Exchanges</b>: no data"]
        width = max(len("Exchange"), *(len(exchange_name(n)) for n in names))
        rows = [f"{'Exchange'.ljust(width)}  Uptime  Transfers"]
        for name in names:
            uptime = _pct_cell(data.uptime_pct.get(name))
            coverage = _pct_cell(data.coverage_pct.get(name))
            rows.append(f"{exchange_name(name).ljust(width)}  {uptime:>6}  {coverage:>9}")
        return ["🌐 <b>Exchanges</b>", f"<pre>{esc(chr(10).join(rows))}</pre>"]


def _pct_cell(value: int | None) -> str:
    return "n/a" if value is None else f"{value}%"


def _signed_pct(value: Decimal) -> str:
    text = fmt_pct(value)
    return text if value < 0 else f"+{text}"
