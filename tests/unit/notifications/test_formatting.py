from decimal import Decimal as D

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
    assert text.startswith("💹 <b>Arbitrage Opportunity</b> · <code>ABC/USDT</code>")
    assert "🟢 <b>BUY</b> on <b>Binance</b> @ <code>100</code>" in text
    assert "🔴 <b>SELL</b> on <b>KuCoin</b> @ <code>101</code>" in text
    assert "💰 <b>Net profit: +$7.98 (0.80%)</b>" in text
    assert "📈 Gross spread: <b>1.00%</b>" in text
    assert "📦 Size: <b>$1,000.00</b> USDT → <b>10</b> ABC" in text
    assert "<pre>Buy fee   $1.00\nSell fee  $1.01\nSlippage  $0.00\nTransfer  $0.00</pre>" in text
    assert "✅ verified via <b>TRC20</b>" in text
    assert "⏱ Book age: 120 ms / 340 ms" in text
    assert "<blockquote>" in text
    assert "UTC</blockquote>" in text
    assert "estimate" not in text


def test_unverified_transfer_is_always_labelled() -> None:
    evaluation = make_evaluation(
        transfer=TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata")
    )
    text = OpportunityFormatter().render(evaluation)
    assert "⚠️ <b>Transfer path unverified</b> — no source transfer metadata" in text
    assert "Transfer  n/a" in text


def test_estimated_fees_are_labelled() -> None:
    text = OpportunityFormatter().render(make_evaluation(fees_estimated=True))
    assert "ℹ️ <i>Taker fee is an estimate" in text


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
    assert "🚀 <b>Nexus Spread Scanner started</b>" in rendered[0]
    assert "🔑 <b>Bybit</b> — 511 markets · transfers 87%" in rendered[0]
    assert "🌐 <b>OKX</b> — 443 markets\n" in rendered[0]
    assert "<b>≥ 0.3%</b> and <b>≥ $5</b>" in rendered[0]
    assert "SIGTERM" in rendered[1]
    assert "&lt;script&gt;" in rendered[2]
    assert "Gate.io recovered" in rendered[3]


def test_unknown_event_kind() -> None:
    with pytest.raises(ValueError, match="unknown"):
        event_from_payload({"kind": "nope", "data": {}})


def test_realert_is_labelled_with_previous_net() -> None:
    text = OpportunityFormatter().render(
        make_evaluation(), AlertContext(episode_id=4, realert=2, previous_net_usd="5.2")
    )
    assert text.startswith(
        "💹 <b>Re-alert #2: spread is growing</b> · <code>ABC/USDT</code>\n"
        "🔁 Net was <b>+$5.20</b> at the previous alert\n"
    )
    first = OpportunityFormatter().render(make_evaluation(), AlertContext(episode_id=4))
    assert first.startswith("💹 <b>Arbitrage Opportunity</b>")
    assert "Re-alert" not in first


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
        "🏁 <b>Opportunity closed</b> · <code>ABC/USDT</code>\n"
        "Binance → KuCoin\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏱ Duration: <b>3m 20s</b> · 14 evaluations\n"
        "💰 Peak net: <b>+$12.35 (1.23%)</b>\n"
        "⚡ Survived execution latency: <b>✅ yes</b>\n"
        "🔁 Re-alerts: 1\n"
        "<blockquote>Closed: gap</blockquote>"
    )


@pytest.mark.parametrize(("survived", "label"), [(False, "❌ no"), (None, "n/a")])
def test_episode_closed_latency_labels_and_escaping(survived: bool | None, label: str) -> None:
    text = SystemEventFormatter().render(
        _closed(survived_latency=survived, realerts=0, symbol="<x>", reason="a&b")
    )
    assert f"<b>{label}</b>" in text
    assert "Re-alerts" not in text
    assert "&lt;x&gt;" in text
    assert "a&amp;b" in text


@pytest.mark.parametrize(
    ("seconds", "expected"), [(0, "0s"), (45, "45s"), (200, "3m 20s"), (7_500, "2h 05m")]
)
def test_fmt_duration(seconds: int, expected: str) -> None:
    assert fmt_duration(seconds) == expected


def test_routes_quarantined_message_snapshot_and_cap() -> None:
    route = QuarantinedRoute("ZIL/USDT", "binance", "okx", "unverified_persistent", "15 min")
    event = RoutesQuarantined(routes=(route,), duration_h=24)
    assert event_from_payload(event_to_payload(event)) == event
    assert SystemEventFormatter().render(event) == (
        "🚫 <b>1 route(s) quarantined</b> for <b>24 h</b>\n"
        "<i>No alerts and no order-book checks; lifted early if the transfer path "
        "becomes verified.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• <code>ZIL/USDT</code> Binance → OKX: spread persists without a verified "
        "transfer path\n"
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
    assert "… and 3 more" in text
    assert "&lt;x&gt;" in text
