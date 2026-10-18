from decimal import Decimal as D

import pytest

from nexus.domain.events import (
    ExchangeDown,
    ExchangeRecovered,
    ExchangeStatus,
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
            exchanges=(ExchangeStatus("bybit", True, 511), ExchangeStatus("okx", False, 443)),
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
    assert "🔑 <b>Bybit</b> — 511 markets" in rendered[0]
    assert "🌐 <b>OKX</b> — 443 markets" in rendered[0]
    assert "<b>≥ 0.3%</b> and <b>≥ $5</b>" in rendered[0]
    assert "SIGTERM" in rendered[1]
    assert "&lt;script&gt;" in rendered[2]
    assert "Gate.io recovered" in rendered[3]


def test_unknown_event_kind() -> None:
    with pytest.raises(ValueError, match="unknown"):
        event_from_payload({"kind": "nope", "data": {}})
