"""Daily digest template (Telegram HTML, en|ru; every dynamic value is escaped)."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from nexus.domain.digest import (
    DigestData,
    EpisodeStats,
)
from nexus.notifications.alert_catalog import DEFAULT_LANGUAGE, catalog
from nexus.notifications.formatting import (
    SEPARATOR,
    esc,
    exchange_name,
    fmt_pct,
    fmt_usd,
    format_duration,
    truncate,
)

QUARANTINES_SHOWN: Final = 5
LATENCY_MARK: Final[dict[bool | None, str]] = {True: " ⚡", False: " 🐢", None: ""}


class DigestFormatter:
    """Renders :class:`DigestData` for a time zone in ``en`` or ``ru``."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self._t = catalog(language)

    def render(self, data: DigestData, tz: str) -> str:
        """Render the digest."""
        zone = ZoneInfo(tz)

        def local(epoch_ms: int) -> str:
            return datetime.fromtimestamp(epoch_ms / 1000, tz=zone).strftime("%d %b %H:%M")

        lines = [
            self._t["dg_title"],
            f"<i>{local(data.window_start_ms)} → {local(data.window_end_ms)} ({esc(tz)})</i>",
            *self._conditional(data),
            SEPARATOR,
            *self._episodes(data.episodes),
            SEPARATOR,
            *self._quarantine(data),
            SEPARATOR,
            *self._exchanges(data),
            self._t["dg_unverified"].format(n=data.unverified_evaluations),
        ]
        return truncate("\n".join(lines))

    def _conditional(self, data: DigestData) -> list[str]:
        """Conditional-venue note and the episode totals (all / excluding conditional)."""
        t = self._t
        if not data.conditional_venues:
            return [
                t["dg_no_conditional"],
                SEPARATOR,
                t["dg_episodes_all"].format(total=data.episodes.total),
            ]
        ep_excl = data.episodes.total_excl_conditional
        names = ", ".join(esc(exchange_name(v)) for v in data.conditional_venues)
        return [
            t["dg_conditional"].format(names=names),
            SEPARATOR,
            t["dg_episodes_split"].format(
                total=data.episodes.total, excl=t["dg_na"] if ep_excl is None else ep_excl
            ),
        ]

    def _episodes(self, stats: EpisodeStats) -> list[str]:
        t = self._t
        lines = [
            t["dg_ep_title"].format(n=stats.total),
            t["dg_ep_split"].format(v=stats.verified, u=stats.unverified, q=stats.quarantined),
        ]
        if not stats.total:
            return lines
        lines.append(
            t["dg_ep_latency"].format(n=stats.survived_latency, checked=stats.latency_checked)
        )
        if stats.median_duration_s is not None and stats.max_duration_s is not None:
            lines.append(
                t["dg_ep_duration"].format(
                    median=format_duration(t, stats.median_duration_s),
                    max=format_duration(t, stats.max_duration_s),
                )
            )
        if stats.top:
            lines.append(t["dg_top"])
            for rank, e in enumerate(stats.top, start=1):
                lines.append(
                    f"{rank}. <code>{esc(e.symbol)}</code> {esc(exchange_name(e.buy_exchange))}"
                    f" → {esc(exchange_name(e.sell_exchange))} — "
                    f"<b>{fmt_usd(e.peak_net_usd, signed=True)}</b>"
                    f" ({fmt_pct(e.peak_net_pct)}) · {format_duration(t, e.duration_s)}"
                    f"{LATENCY_MARK[e.survived_latency]}"
                )
        return lines

    def _quarantine(self, data: DigestData) -> list[str]:
        t = self._t
        lines = [t["dg_q_title"].format(new=len(data.quarantines), active=data.active_quarantines)]
        for q in data.quarantines[:QUARANTINES_SHOWN]:
            why = t.get(f"q_{q.reason}", q.reason)
            lines.append(
                f"• <code>{esc(q.symbol)}</code> {esc(exchange_name(q.buy_exchange))}"
                f" → {esc(exchange_name(q.sell_exchange))}: {esc(why)}"
            )
        hidden = len(data.quarantines) - QUARANTINES_SHOWN
        if hidden > 0:
            lines.append(t["sys_more"].format(n=hidden))
        return lines

    def _exchanges(self, data: DigestData) -> list[str]:
        t = self._t
        names = sorted(set(data.uptime_pct) | set(data.coverage_pct))
        if not names:
            return [t["dg_ex_none"]]
        col = t["dg_ex_col_name"]
        width = max(len(col), *(len(exchange_name(n)) for n in names))
        uw, tw = len(t["dg_ex_col_uptime"]), len(t["dg_ex_col_transfers"])
        rows = [f"{col.ljust(width)}  {t['dg_ex_col_uptime']}  {t['dg_ex_col_transfers']}"]
        for name in names:
            uptime = self._pct_cell(data.uptime_pct.get(name))
            coverage = self._pct_cell(data.coverage_pct.get(name))
            rows.append(f"{exchange_name(name).ljust(width)}  {uptime:>{uw}}  {coverage:>{tw}}")
        return [t["dg_ex_title"], f"<pre>{esc(chr(10).join(rows))}</pre>"]

    def _pct_cell(self, value: int | None) -> str:
        return self._t["dg_na"] if value is None else f"{value}%"
