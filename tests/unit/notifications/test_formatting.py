import json
from decimal import Decimal as D
from typing import Any

import pytest

from nexus.domain.events import (
    EpisodeClosed,
    ExchangeDown,
    ExchangeRecovered,
    ExchangeStatus,
    QuarantinedRoute,
    RoutesQuarantined,
    ScannerStarted,
    ScannerStopped,
    SystemEvent,
    event_from_payload,
    event_to_payload,
)
from nexus.notifications.formatting import (
    SystemEventFormatter,
    fmt_amount,
    fmt_duration,
    fmt_pct,
    fmt_price,
    fmt_usd,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (D("80946.1"), "80,946.1"),
        (D("0.000123456789"), "0.000123457"),
        (D(100), "100"),
        (D("1.5"), "1.5"),
        (D(0), "0"),
    ],
)
def test_fmt_price(value: D, expected: str) -> None:
    assert fmt_price(value) == expected


def test_number_formatting() -> None:
    assert fmt_usd(D("-3.456")) == "-$3.46"
    assert fmt_usd(D("1234.5"), signed=True) == "+$1,234.50"
    assert fmt_pct(D("0.798101")) == "0.80%"
    assert fmt_amount(D("9.99000000")) == "9.99"
    assert fmt_amount(D("12345")) == "12,345"


def test_started_message_waiver_line_roundtrip() -> None:
    formatter = SystemEventFormatter()
    base: dict[str, Any] = {
        "exchanges": (ExchangeStatus("okx", True, 1),),
        "min_net_profit_pct": "0.3",
        "min_net_profit_usd": "5",
        "reference_notional_usd": "1000",
        "common_symbols": 1,
    }
    plain = formatter.render(ScannerStarted(**base))
    assert "привязки ключей к IP" not in plain.lower()
    assert "НЕ использован" not in plain
    event = ScannerStarted(
        **base,
        ip_unbound_venues=("binance", "okx", "kucoin"),
        public_fallback_venues=("bybit",),
    )
    restored = event_from_payload(json.loads(json.dumps(event_to_payload(event))))
    assert restored == event
    text = formatter.render(restored)
    assert "ℹ️ Привязка ключей к IP не подтверждена (рекомендуется): binance, okx, kucoin" in text
    assert "⚠️ Ключ НЕ использован" in text
    assert "публичном режиме: bybit" in text


def test_system_events_roundtrip_and_render() -> None:
    formatter = SystemEventFormatter()
    events: list[SystemEvent] = [
        ScannerStarted(
            exchanges=(ExchangeStatus("bybit", True, 511, 87), ExchangeStatus("okx", False, 443)),
            min_net_profit_pct="0.3",
            min_net_profit_usd="5",
            reference_notional_usd="1000",
            common_symbols=420,
        ),
        ScannerStopped(reason="SIGTERM"),
        ExchangeDown(exchange="gateio", error="timeout <script>", consecutive_failures=3),
        ExchangeRecovered(exchange="gateio", downtime_s=95),
    ]
    rendered = []
    for event in events:
        restored = event_from_payload(event_to_payload(event))
        assert restored == event
        rendered.append(formatter.render(restored))
    assert "🚀 <b>Nexus Spread Scanner запущен</b>" in rendered[0]
    assert "🔑 <b>Bybit</b> — рынков: 511 · переводы 87%" in rendered[0]
    assert "🌐 <b>OKX</b> — рынков: 443\n" in rendered[0]
    assert "<b>≥ 0.3%</b> и <b>≥ $5</b>" in rendered[0]
    assert "SIGTERM" in rendered[1]
    assert "&lt;script&gt;" in rendered[2]
    assert "Gate.io снова доступна" in rendered[3]


def test_unknown_event_kind() -> None:
    with pytest.raises(ValueError, match="unknown"):
        event_from_payload({"kind": "nope", "data": {}})


def _closed(**overrides: object) -> EpisodeClosed:
    fields: dict[str, object] = {
        "symbol": "ABC/USDT",
        "buy_exchange": "binance",
        "sell_exchange": "kucoin",
        "reason": "gap",
        "duration_s": 200,
        "peak_net_usd": "12.345",
        "peak_net_pct": "1.2345",
        "evaluations": 14,
        "realerts": 1,
        "survived_latency": True,
    }
    fields.update(overrides)
    return EpisodeClosed(**fields)  # type: ignore[arg-type]


def test_episode_closed_message_snapshot() -> None:
    event = _closed()
    assert event_from_payload(event_to_payload(event)) == event
    assert SystemEventFormatter().render(event) == (
        "🏁 <b>Возможность закрылась</b> · <code>ABC/USDT</code>\n"
        "Binance → KuCoin\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏱ Длительность: <b>3 мин 20 с</b> · проверок: 14\n"
        "💰 Максимум чистой прибыли: <b>+$12.35 (1.23%)</b>\n"
        "⚡ Пережила задержку исполнения: <b>✅ да</b>\n"
        "🔁 Повторных алертов: 1\n"
        "<blockquote>Причина закрытия: спред исчез</blockquote>"
    )


@pytest.mark.parametrize(("survived", "label"), [(False, "❌ нет"), (None, "н/д")])
def test_episode_closed_latency_labels_and_escaping(survived: bool | None, label: str) -> None:
    text = SystemEventFormatter().render(
        _closed(survived_latency=survived, realerts=0, symbol="<x>", reason="a&b")
    )
    assert f"<b>{label}</b>" in text
    assert "Повторных" not in text
    assert "&lt;x&gt;" in text
    assert "a&amp;b" in text


@pytest.mark.parametrize(
    ("seconds", "expected"), [(0, "0 с"), (45, "45 с"), (200, "3 мин 20 с"), (7_500, "2 ч 05 мин")]
)
def test_fmt_duration(seconds: int, expected: str) -> None:
    assert fmt_duration(seconds) == expected


def test_routes_quarantined_message_snapshot_and_cap() -> None:
    route = QuarantinedRoute("ZIL/USDT", "binance", "okx", "unverified_persistent", "15 min")
    event = RoutesQuarantined(routes=(route,), duration_h=24)
    assert event_from_payload(event_to_payload(event)) == event
    assert SystemEventFormatter().render(event) == (
        "🚫 <b>В карантин отправлено связок: 1</b> на <b>24 ч</b>\n"
        "<i>Алертов и проверки стаканов по ним не будет; карантин снимется раньше, "
        "если маршрут перевода подтвердится.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• <code>ZIL/USDT</code> Binance → OKX: спред держится, а маршрут перевода "
        "не подтверждён\n"
        "  <i>15 min</i>"
    )
    many = RoutesQuarantined(
        routes=tuple(
            QuarantinedRoute(f"T{i}/USDT", "a", "b", "transfer_unavailable", "<x>")
            for i in range(13)
        ),
        duration_h=24,
    )
    text = SystemEventFormatter().render(many)
    assert text.count("•") == 10
    assert "… и ещё 3" in text
    assert "&lt;x&gt;" in text


def test_watchdog_events_roundtrip_and_render() -> None:
    from nexus.domain.events import (
        WatchdogAlert,
        WatchdogRecovered,
        event_from_payload,
        event_to_payload,
    )
    from nexus.notifications.formatting import SystemEventFormatter

    formatter = SystemEventFormatter()
    alert = WatchdogAlert("scanner", "scanner_stale", 25)
    assert event_from_payload(event_to_payload(alert)) == alert
    assert formatter.render(alert) == (
        "🚨 <b>Сканер: нужна проверка</b>\n"
        "<blockquote>сканер не записывает данные уже 25 мин: проверьте контейнер scanner"
        "</blockquote>"
    )
    recovered = WatchdogRecovered("backup", 95)
    assert event_from_payload(event_to_payload(recovered)) == recovered
    assert formatter.render(recovered) == (
        "✅ <b>Резервная копия: проблема устранена</b>\nДлилась около <b>1 ч 35 мин</b>"
    )


@pytest.mark.parametrize(
    "reason",
    [
        "scanner_no_data",
        "backup_missing",
        "backup_unreadable",
        "backup_failed",
        "backup_not_copied",
        "backup_stale",
        "something_new",
    ],
)
def test_watchdog_alert_texts_are_russian_and_escaped(reason: str) -> None:
    from nexus.domain.events import WatchdogAlert
    from nexus.notifications.formatting import SystemEventFormatter

    text = SystemEventFormatter().render(WatchdogAlert("<b>backup</b>", reason, None))
    assert "&lt;b&gt;backup" in text
    assert "<b>backup</b>" not in text
    assert "{minutes}" not in text


def test_truncate_keeps_short_text_and_closes_open_tags() -> None:
    from nexus.notifications.formatting import TELEGRAM_MAX_LENGTH, truncate

    assert truncate("short <b>x</b>") == "short <b>x</b>"
    text = "<blockquote><b>" + "a" * 5000 + "</b></blockquote>"
    cut = truncate(text)
    assert len(cut) <= TELEGRAM_MAX_LENGTH
    assert cut.endswith("…</b></blockquote>")


@pytest.mark.parametrize("tail", ["<b", "<code class=", "&am", "&#12"])
def test_truncate_never_cuts_inside_a_tag_or_entity(tail: str) -> None:
    from nexus.notifications.formatting import TELEGRAM_MAX_LENGTH, truncate

    head = "x" * (TELEGRAM_MAX_LENGTH - 64 - len(tail))
    cut = truncate(head + tail + "y" * 400)
    assert cut == head + "…"
