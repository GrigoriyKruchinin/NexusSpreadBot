from decimal import Decimal as D

from nexus.domain.digest import (
    DigestData,
    EpisodeStats,
    EpisodeSummary,
    PaperStats,
    QuarantineSummary,
)
from nexus.notifications.digest import DigestFormatter

T0 = 1_792_303_200_000  # 2026-10-18 09:00 Europe/Moscow (06:00 UTC)
DAY = 24 * 3_600_000


def _data() -> DigestData:
    return DigestData(
        window_start_ms=T0,
        window_end_ms=T0 + DAY,
        episodes=EpisodeStats(
            total=9,
            verified=5,
            unverified=3,
            quarantined=1,
            survived_latency=4,
            latency_checked=6,
            median_duration_s=80,
            max_duration_s=843,
            top=(
                EpisodeSummary("ERA/USDT", "bybit", "okx", D("12.345"), D("1.2345"), 200, True),
                EpisodeSummary("<b>X</b>/USDT", "mexc", "gateio", D("6"), D("0.6"), 30, None),
            ),
        ),
        paper=PaperStats(
            trades=4,
            skipped={"spread_gone": 1, "insufficient_coin": 2},
            realized_usd=D("20.1"),
            rebalance_usd=D(3),
            rebalances=2,
            blocked_rebalances=1,
            capital_usd=D(7000),
            equity_usd=D(7015),
            realized_total_usd=D(30),
            rebalance_total_usd=D(5),
        ),
        quarantines=(QuarantineSummary("ZIL/USDT", "binance", "okx", "unverified_persistent"),),
        active_quarantines=3,
        uptime_pct={"binance": 99, "okx": 100, "bitget": None},
        coverage_pct={"binance": 87, "okx": None},
        unverified_evaluations=37,
    )


def test_digest_snapshot() -> None:
    assert DigestFormatter().render(_data(), "Europe/Moscow") == (
        "📊 <b>Daily digest</b>\n"
        "<i>18 Oct 09:00 → 19 Oct 09:00 (Europe/Moscow)</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔀 <b>Opportunity episodes: 9</b>\n"
        "✅ verified 5 · ⚠️ unverified 3 · 🚫 quarantined 1\n"
        "⚡ Survived latency: <b>4</b> of 6 checked\n"
        "⏱ Duration: median 1m 20s · max 14m 03s\n"
        "<b>Top routes by peak net</b>\n"
        "1. <code>ERA/USDT</code> Bybit → OKX — <b>+$12.35</b> (1.23%) · 3m 20s ⚡\n"
        "2. <code>&lt;b&gt;X&lt;/b&gt;/USDT</code> MEXC → Gate.io — <b>+$6.00</b> (0.60%) · 30s\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>Paper trading</b>\n"
        "Trades: <b>4</b> · skipped: insufficient_coin 2, spread_gone 1\n"
        "24h: realized <b>+$20.10</b> · transfers -$3.00 (2) · blocked 1\n"
        "Since start: P&amp;L <b>+$15.00</b> = realized +$30.00 − transfers $5.00"
        " + MTM -$10.00\n"
        "Capital $7,000.00 · ROC <b>+0.21%</b>\n"
        "🛡 Hedged (no inventory price risk): <b>+$25.00</b> · ROC <b>+0.36%</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚫 <b>Quarantine</b>: 1 new · 3 active\n"
        "• <code>ZIL/USDT</code> Binance → OKX: spread persists without a verified transfer"
        " path\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌐 <b>Exchanges</b>\n"
        "<pre>Exchange  Uptime  Transfers\n"
        "Binance      99%        87%\n"
        "Bitget       n/a        n/a\n"
        "OKX         100%        n/a</pre>\n"
        "<blockquote>Unverified opportunities (stored, not alerted): 37</blockquote>"
    )


def test_empty_digest() -> None:
    data = DigestData(
        window_start_ms=T0,
        window_end_ms=T0 + DAY,
        episodes=EpisodeStats(),
        paper=None,
        quarantines=(),
        active_quarantines=0,
        uptime_pct={},
        coverage_pct={},
    )
    text = DigestFormatter().render(data, "UTC")
    assert "🔀 <b>Opportunity episodes: 0</b>" in text
    assert "Survived latency" not in text
    assert "📝 <b>Paper trading</b>: no activity yet" in text
    assert "🌐 <b>Exchanges</b>: no data" in text
    assert "(UTC)" in text


async def test_digest_service_sends_last_24h() -> None:
    from nexus.services.digest import DigestService
    from tests.fakes import ManualClock, RecordingNotifier

    windows: list[tuple[int, int]] = []

    class _Repo:
        async def collect(self, since_ms: int, until_ms: int) -> DigestData:
            windows.append((since_ms, until_ms))
            return _data()

    notifier = RecordingNotifier()
    service = DigestService(_Repo(), notifier, ManualClock(T0 + DAY))  # type: ignore[arg-type]
    await service.send("Europe/Moscow")
    assert windows == [(T0, T0 + DAY)]
    assert notifier.sent[0].text.startswith("📊 <b>Daily digest</b>")
    assert not notifier.sent[0].silent
