from dataclasses import replace
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
        "📊 <b>Ежедневный дайджест</b>\n"
        "<i>18 Oct 09:00 → 19 Oct 09:00 (Europe/Moscow)</i>\n"
        "Условные биржи: нет\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Эпизоды:   все 9\n"
        "Бумажный P&amp;L (hedged): все +$25.00\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔀 <b>Эпизодов возможностей: 9</b>\n"
        "✅ подтверждённых 5 · ⚠️ неподтверждённых 3 · 🚫 в карантине 1\n"
        "⚡ Пережили задержку: <b>4</b> из 6 проверенных\n"
        "⏱ Длительность: медиана 1 мин 20 с · максимум 14 мин 03 с\n"
        "<b>Топ связок по пиковой чистой прибыли</b>\n"
        "1. <code>ERA/USDT</code> Bybit → OKX — <b>+$12.35</b> (1.23%) · 3 мин 20 с ⚡\n"
        "2. <code>&lt;b&gt;X&lt;/b&gt;/USDT</code> MEXC → Gate.io — <b>+$6.00</b> (0.60%) · 30 с\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>Бумажная торговля</b>\n"
        "Сделок: <b>4</b> · пропущено: не хватает монеты 2,"
        " спред исчез за время задержки 1\n"
        "За 24 ч: заработано <b>+$20.10</b> · переводы -$3.00 (2) · заблокировано 1\n"
        "С начала: P&amp;L <b>+$15.00</b> = арбитраж +$30.00 − переводы $5.00"
        " + переоценка -$10.00\n"
        "Капитал $7,000.00 · доходность <b>+0.21%</b>\n"
        "🛡 С хеджем (без ценового риска инвентаря): <b>+$25.00</b>"
        " · доходность <b>+0.36%</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚫 <b>Карантин</b>: новых 1 · активных 3\n"
        "• <code>ZIL/USDT</code> Binance → OKX: спред держится,"
        " а маршрут перевода не подтверждён\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌐 <b>Биржи</b>\n"
        "<pre>Биржа    Аптайм  Переводы\n"
        "Binance     99%       87%\n"
        "Bitget      н/д       н/д\n"
        "OKX        100%       н/д</pre>\n"
        "<blockquote>Неподтверждённые возможности (записаны, без алертов): 37</blockquote>"
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
    assert "🔀 <b>Эпизодов возможностей: 0</b>" in text
    assert "Пережили задержку" not in text
    assert "📝 <b>Бумажная торговля</b>: пока нет активности" in text
    assert "🌐 <b>Биржи</b>: нет данных" in text
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
    assert notifier.sent[0].text.startswith("📊 <b>Ежедневный дайджест</b>")
    assert not notifier.sent[0].silent


def _cond_data(conditional: tuple[str, ...]) -> DigestData:
    base = _data()
    return DigestData(
        window_start_ms=base.window_start_ms,
        window_end_ms=base.window_end_ms,
        episodes=EpisodeStats(total=24, total_excl_conditional=6),
        paper=PaperStats(
            realized_total_usd=D("50.20"),
            rebalance_total_usd=D("9"),
            realized_total_excl_conditional_usd=D("12.75"),
            rebalance_total_excl_conditional_usd=D("3"),
        ),
        quarantines=(),
        active_quarantines=0,
        uptime_pct={},
        coverage_pct={},
        conditional_venues=conditional,
    )


def test_digest_conditional_block_golden() -> None:
    text = DigestFormatter().render(_cond_data(("bybit", "gateio")), "UTC")
    assert text.split("\n")[2:7] == [
        "⚠️ Условные биржи (данные собираются, торговать пока нельзя): Bybit, Gate.io",
        "━━━━━━━━━━━━━━━━━━━━",
        "Эпизоды:   все 24 | без условных 6",
        "Бумажный P&amp;L (hedged): все +$41.20 | без условных ≈ +$9.75 (оценка)",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    assert len(text) < 4096


def test_digest_conditional_block_empty_list() -> None:
    text = DigestFormatter().render(_cond_data(()), "UTC")
    assert text.split("\n")[2:6] == [
        "Условные биржи: нет",
        "━━━━━━━━━━━━━━━━━━━━",
        "Эпизоды:   все 24",
        "Бумажный P&amp;L (hedged): все +$41.20",
    ]
    assert "без условных" not in text


def test_digest_conditional_names_are_escaped() -> None:
    text = DigestFormatter().render(_cond_data(("<b>x",)), "UTC")
    assert text.split("\n")[2] == (
        "⚠️ Условные биржи (данные собираются, торговать пока нельзя): &lt;b&gt;x"
    )
    assert "<b>x" not in text


def test_paper_hedged_excl_is_unknown_until_computed() -> None:
    p = PaperStats(realized_total_usd=D(5), rebalance_total_usd=D(1))
    assert p.hedged_pnl_usd == D(4)
    assert p.hedged_pnl_excl_conditional_usd is None  # never a silent +$0.00
    done = PaperStats(
        realized_total_excl_conditional_usd=D(5), rebalance_total_excl_conditional_usd=D(1)
    )
    assert done.hedged_pnl_excl_conditional_usd == D(4)


def test_digest_shows_na_when_excl_values_are_missing() -> None:
    base = _cond_data(("bybit", "gateio"))
    data = replace(
        base,
        episodes=EpisodeStats(total=24),
        paper=PaperStats(realized_total_usd=D("50.20"), rebalance_total_usd=D("9")),
    )
    lines = DigestFormatter().render(data, "UTC").split("\n")
    assert lines[4] == "Эпизоды:   все 24 | без условных н/д"
    assert lines[5] == "Бумажный P&amp;L (hedged): все +$41.20 | без условных н/д"
    no_paper = DigestFormatter().render(replace(base, paper=None), "UTC").split("\n")
    assert no_paper[5] == "Бумажный P&amp;L (hedged): н/д"


async def test_digest_log_na_when_excl_missing() -> None:
    from nexus.services.digest import summary_totals

    data = replace(
        _cond_data(("bybit",)),
        episodes=EpisodeStats(total=3),
        paper=PaperStats(realized_total_usd=D(2)),
    )
    assert summary_totals(data, excl_conditional=True) == {
        "episodes": None,
        "paper_hedged_pnl_usd": None,
    }


async def test_digest_log_has_conditional_fields() -> None:
    import structlog
    from structlog.testing import capture_logs

    from nexus.services.digest import DigestService
    from tests.fakes import ManualClock, RecordingNotifier

    class _Repo:
        async def collect(self, since_ms: int, until_ms: int) -> DigestData:
            return _cond_data(("bybit", "gateio"))

    structlog.reset_defaults()
    with capture_logs() as logs:
        await DigestService(_Repo(), RecordingNotifier(), ManualClock(T0)).send("UTC")  # type: ignore[arg-type]
    [record] = [r for r in logs if r["event"] == "digest_sent"]
    assert record["conditional_venues"] == ["bybit", "gateio"]
    assert record["total_all"] == {"episodes": 24, "paper_hedged_pnl_usd": "41.20"}
    assert record["total_excl_conditional"] == {"episodes": 6, "paper_hedged_pnl_usd": "9.75"}
