import json
from decimal import Decimal as D
from typing import Any

import pytest

from nexus.domain.events import (
    AlertContext,
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
from nexus.domain.spread import EvaluationStatus, TransferQuote, TransferStatus
from nexus.notifications.formatting import (
    OpportunityFormatter,
    SystemEventFormatter,
    fmt_amount,
    fmt_duration,
    fmt_pct,
    fmt_price,
    fmt_usd,
)
from tests.support import make_evaluation


def test_opportunity_alert_content() -> None:
    text = OpportunityFormatter().render(make_evaluation())
    assert text.startswith("💹 <b>Арбитражная возможность</b> · <code>ABC/USDT</code>")
    assert "🟢 <b>ПОКУПКА</b> на <b>Binance</b> по <code>100</code>" in text
    assert "🔴 <b>ПРОДАЖА</b> на <b>KuCoin</b> по <code>101</code>" in text
    assert "💰 <b>Чистая прибыль: +$7.98 (0.80%)</b>" in text
    assert "📈 Спред до издержек: <b>1.00%</b>" in text
    assert "📦 Объём: <b>$1,000.00</b> USDT → <b>10</b> ABC" in text
    assert (
        "<pre>Комиссия покупки  $1.00\nКомиссия продажи  $1.01\n"
        "Проскальзывание   $0.00\nПеревод           $0.00</pre>"
    ) in text
    assert "✅ подтверждён, сеть <b>TRC20</b>" in text
    assert "⏱ Возраст стаканов: 120 мс / 340 мс" in text
    assert "<blockquote>" in text
    assert "UTC</blockquote>" in text
    assert "оценочная" not in text


def test_unverified_transfer_is_always_labelled() -> None:
    evaluation = make_evaluation(
        transfer=TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata")
    )
    text = OpportunityFormatter().render(evaluation)
    assert "⚠️ <b>Маршрут перевода не подтверждён</b> — no source transfer metadata" in text
    assert "Перевод           н/д" in text


def test_estimated_fees_are_labelled() -> None:
    text = OpportunityFormatter().render(make_evaluation(fees_estimated=True))
    assert "ℹ️ <i>Комиссия тейкера оценочная" in text


def test_exchange_strings_are_escaped() -> None:
    evaluation = make_evaluation(
        buy_exchange="<b>evil</b>",
        transfer=TransferQuote(TransferStatus.UNKNOWN, network="<i>x</i>", note="a<b>&c"),
    )
    text = OpportunityFormatter().render(evaluation)
    assert "<b>evil</b>" not in text
    assert "&lt;b&gt;evil&lt;/b&gt;" in text.replace("<b>&lt;", "&lt;")
    assert "a&lt;b&gt;&amp;c" in text


def test_render_requires_breakdown() -> None:
    with pytest.raises(ValueError, match="breakdown"):
        OpportunityFormatter().render(
            make_evaluation(status=EvaluationStatus.STALE_BOOK, with_breakdown=False)
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
    assert "без привязки к IP" not in plain
    event = ScannerStarted(**base, ip_unbound_venues=("binance", "okx", "kucoin"))
    restored = event_from_payload(json.loads(json.dumps(event_to_payload(event))))
    assert restored == event
    assert (
        "⚠️ Ключи без привязки к IP (разрешено для локального запуска): binance, okx, kucoin"
        in formatter.render(restored)
    )


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


def test_realert_is_labelled_with_previous_net() -> None:
    text = OpportunityFormatter().render(
        make_evaluation(), AlertContext(episode_id=4, realert=2, previous_net_usd="5.2")
    )
    assert text.startswith(
        "💹 <b>Повтор №2: спред растёт</b> · <code>ABC/USDT</code>\n"
        "🔁 В прошлом алерте чистая прибыль была <b>+$5.20</b>\n"
    )
    first = OpportunityFormatter().render(make_evaluation(), AlertContext(episode_id=4))
    assert first.startswith("💹 <b>Арбитражная возможность</b>")
    assert "Повтор" not in first


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


def test_chain_tax_is_shown_without_a_verified_network() -> None:
    from dataclasses import replace

    base = make_evaluation(transfer=TransferQuote(TransferStatus.UNKNOWN))
    assert base.breakdown is not None
    taxed = replace(base, breakdown=replace(base.breakdown, transfer_fee_usd=D("15.13")))
    assert "Перевод           $15.13 налог + н/д" in OpportunityFormatter().render(taxed)


def test_alert_marker_only_for_conditional_routes() -> None:
    from nexus.notifications.formatting import OpportunityFormatter
    from tests.support import make_evaluation

    fmt = OpportunityFormatter(("bybit", "gateio"))
    plain = fmt.render(make_evaluation(buy_exchange="binance", sell_exchange="okx"))
    assert "условн" not in plain
    one = fmt.render(make_evaluation(buy_exchange="binance", sell_exchange="bybit"))
    assert "⚠️ условная биржа (Bybit)" in one.split("\n")[0]
    both = fmt.render(make_evaluation(buy_exchange="bybit", sell_exchange="gateio"))
    assert "⚠️ условные биржи (Bybit, Gate.io)" in both.split("\n")[0]
    assert "условн" not in OpportunityFormatter().render(make_evaluation(sell_exchange="bybit"))
    assert len(both) < 4096


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
