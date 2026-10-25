from dataclasses import replace
from decimal import Decimal as D

from nexus.domain.digest import (
    DigestData,
    EpisodeStats,
    EpisodeSummary,
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
        quarantines=(QuarantineSummary("ZIL/USDT", "binance", "okx", "unverified_persistent"),),
        active_quarantines=3,
        uptime_pct={"binance": 99, "okx": 100, "bitget": None},
        coverage_pct={"binance": 87, "okx": None},
        unverified_evaluations=37,
    )


def test_digest_snapshot() -> None:
    assert DigestFormatter("ru").render(_data(), "Europe/Moscow") == (
        "📊 <b>Ежедневный дайджест</b>\n"
        "<i>18 Oct 09:00 → 19 Oct 09:00 (Europe/Moscow)</i>\n"
        "Условные биржи: нет\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Эпизоды:   все 9\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔀 <b>Эпизодов возможностей: 9</b>\n"
        "✅ подтверждённых 5 · ⚠️ неподтверждённых 3 · 🚫 в карантине 1\n"
        "⚡ Пережили задержку: <b>4</b> из 6 проверенных\n"
        "⏱ Длительность: медиана 1 мин 20 с · максимум 14 мин 03 с\n"
        "<b>Топ связок по пиковой чистой прибыли</b>\n"
        "1. <code>ERA/USDT</code> Bybit → OKX — <b>+$12.35</b> (1.23%) · 3 мин 20 с ⚡\n"
        "2. <code>&lt;b&gt;X&lt;/b&gt;/USDT</code> MEXC → Gate.io — <b>+$6.00</b> (0.60%) · 30 с\n"
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
        quarantines=(),
        active_quarantines=0,
        uptime_pct={},
        coverage_pct={},
    )
    text = DigestFormatter("ru").render(data, "UTC")
    assert "🔀 <b>Эпизодов возможностей: 0</b>" in text
    assert "Пережили задержку" not in text
    assert "Бумажн" not in text
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
    assert notifier.sent[0].text.startswith("📊 <b>Daily digest</b>")
    assert not notifier.sent[0].silent


def _cond_data(conditional: tuple[str, ...]) -> DigestData:
    base = _data()
    return DigestData(
        window_start_ms=base.window_start_ms,
        window_end_ms=base.window_end_ms,
        episodes=EpisodeStats(total=24, total_excl_conditional=6),
        quarantines=(),
        active_quarantines=0,
        uptime_pct={},
        coverage_pct={},
        conditional_venues=conditional,
    )


def test_digest_conditional_block_golden() -> None:
    text = DigestFormatter("ru").render(_cond_data(("bybit", "gateio")), "UTC")
    assert text.split("\n")[2:6] == [
        "⚠️ Условные биржи (данные собираются, торговать пока нельзя): Bybit, Gate.io",
        "━━━━━━━━━━━━━━━━━━━━",
        "Эпизоды:   все 24 | без условных (фильтр) 6",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    assert len(text) < 4096


def test_digest_conditional_block_empty_list() -> None:
    text = DigestFormatter("ru").render(_cond_data(()), "UTC")
    assert text.split("\n")[2:5] == [
        "Условные биржи: нет",
        "━━━━━━━━━━━━━━━━━━━━",
        "Эпизоды:   все 24",
    ]
    assert "без условных" not in text


def test_digest_conditional_names_are_escaped() -> None:
    text = DigestFormatter("ru").render(_cond_data(("<b>x",)), "UTC")
    assert text.split("\n")[2] == (
        "⚠️ Условные биржи (данные собираются, торговать пока нельзя): &lt;b&gt;x"
    )
    assert "<b>x" not in text


def test_digest_shows_na_when_excl_values_are_missing() -> None:
    data = replace(_cond_data(("bybit", "gateio")), episodes=EpisodeStats(total=24))
    lines = DigestFormatter("ru").render(data, "UTC").split("\n")
    assert lines[4] == "Эпизоды:   все 24 | без условных (фильтр) н/д"


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
    assert record["episodes"] == 24
    assert record["episodes_excl_conditional"] == 6


def test_digest_defaults_to_english() -> None:
    text = DigestFormatter().render(_data(), "UTC")
    assert "<b>Daily digest</b>" in text
    assert "Opportunity episodes: 9" in text
    assert "Exchange  Uptime  Transfers" in text
    assert "Ежедневный" not in text
