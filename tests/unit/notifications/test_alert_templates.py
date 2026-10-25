"""Golden-string tests of the opportunity alert templates NEW / UPDATE / CLOSED (en, ru)."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.events import AlertContext, AlertLifetime, AlertTransfer, AlertVolume
from nexus.domain.spread import EvaluationStatus, LegState, TransferQuote, TransferStatus
from nexus.notifications.alert_catalog import CATALOGS, pinned_text
from nexus.notifications.formatting import OpportunityFormatter, signed_pct
from tests.support import make_evaluation

VOLUME = AlertVolume("720", "72000.00", "7200", "720000.00", "5000")
VERIFIED = AlertTransfer(
    status="verified",
    network="BEP20",
    fee_base="0.8",
    fee_usd="0.0808",
    est_arrival_min="5.0",
    withdraw="open",
    deposit="open",
)


def _ctx(**kw: object) -> AlertContext:
    fields: dict[str, object] = {
        "episode_id": 7,
        "volume": AlertVolume("10", "1000.00", "30.5", "3050.00", "34.20"),
        "transfer": VERIFIED,
        "lifetime": AlertLifetime(1_000_000, 1_000_000),
    }
    fields.update(kw)
    return AlertContext(**fields)  # type: ignore[arg-type]


NEW_EN = (
    "🟢 <b>ABC</b>/USDT   <b>+0.80 %</b> net\n"
    "Buy  <b>Binance</b>  100\n"
    "Sell <b>KuCoin</b>  101\n"
    "Net after fees/slippage: <b>+0.80 %</b> (≈ +$7.98 on $1,000)\n"
    "Volume: up to <b>$3,050</b> (≈ 30.5 ABC) by orderbooks\n"
    "Transfer: <b>BEP20</b> · fee 0.8 ABC (≈ $0.08) · ≈ 5 min (approx)\n"
    "Withdraw Binance: ✅ open   Deposit KuCoin: ✅ open\n"
    "Lifetime: just opened   ·   #7"
)
NEW_RU = (
    "🟢 <b>ABC</b>/USDT   <b>+0.80 %</b> чистыми\n"
    "Покупка  <b>Binance</b>  100\n"
    "Продажа <b>KuCoin</b>  101\n"
    "Чистый спред после комиссий и проскальзывания: <b>+0.80 %</b> (≈ +$7.98 на $1,000)\n"
    "Объём: до <b>$3,050</b> (≈ 30.5 ABC) по стаканам\n"
    "Перевод: <b>BEP20</b> · комиссия 0.8 ABC (≈ $0.08) · ≈ 5 мин (примерно)\n"
    "Вывод Binance: ✅ открыт   Ввод KuCoin: ✅ открыт\n"
    "Время жизни: только что открылась   ·   #7"
)


def test_new_golden_en_and_ru() -> None:
    evaluation = make_evaluation()
    assert OpportunityFormatter().render(evaluation, _ctx()) == NEW_EN
    assert OpportunityFormatter(language="ru").render(evaluation, _ctx()) == NEW_RU


def test_update_golden() -> None:
    ctx = _ctx(realert=1, lifetime=AlertLifetime(0, 260_000))
    text = OpportunityFormatter().render(make_evaluation(), ctx, peak_net_pct=D("1.9"))
    assert text.startswith("🔄 <b>ABC</b>/USDT   <b>+0.80 %</b> net\n")
    assert text.endswith("Lifetime: 4 m 20 s, peak +1.90 %   ·   #7")
    ru = OpportunityFormatter(language="ru").render(make_evaluation(), ctx, peak_net_pct=D("1.9"))
    assert ru.endswith("Время жизни: 4 мин 20 с, пик +1.90 %   ·   #7")
    assert "Lifetime: 4 m 20 s\n" not in OpportunityFormatter().render(make_evaluation(), ctx)


def test_closed_golden() -> None:
    ctx = _ctx(lifetime=AlertLifetime(0, 300_000, 365_000))
    evaluation = make_evaluation(net_usd=D("7"))
    text = OpportunityFormatter().render_closed(evaluation, ctx, peak_net_pct=D("1.9"))
    assert text == (
        "⚪ <b>Closed</b> · <b>ABC</b>/USDT\n"
        "Buy  <b>Binance</b>  100\n"
        "Sell <b>KuCoin</b>  101\n"
        "Volume: up to <b>$3,050</b> (≈ 30.5 ABC) by orderbooks\n"
        "Transfer: <b>BEP20</b> · fee 0.8 ABC (≈ $0.08) · ≈ 5 min (approx)\n"
        "Withdraw Binance: ✅ open   Deposit KuCoin: ✅ open\n"
        "Lived 6 m 05 s, peak +1.90 %, last +0.70 %   ·   #7"
    )
    ru = OpportunityFormatter(language="ru").render_closed(evaluation, ctx, peak_net_pct=D("1.9"))
    assert ru.startswith("⚪ <b>Закрыта</b> · <b>ABC</b>/USDT\n")
    assert ru.endswith("Прожила 6 мин 05 с, пик +1.90 %, последний +0.70 %   ·   #7")
    assert OpportunityFormatter().render_closed(evaluation, ctx).endswith("Lived 6 m 05 s   ·   #7")


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_unknown_transfer_and_unverified_network(lang: str) -> None:
    t = CATALOGS[lang]
    evaluation = make_evaluation(
        transfer=TransferQuote(TransferStatus.UNKNOWN, note="no <meta> & co")
    )
    text = OpportunityFormatter(language=lang).render(evaluation)
    assert t["transfer_unverified"].format(note=" — no &lt;meta&gt; &amp; co") in text
    assert t["flag_unknown"] in text
    assert t["hint_unverified"] in text
    assert t["volume_scanned"].format(quote="$1,000", base="10", coin="ABC") in text


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_closed_deposit_and_unavailable(lang: str) -> None:
    t = CATALOGS[lang]
    closed = replace(VERIFIED, deposit="closed")
    text = OpportunityFormatter(language=lang).render(make_evaluation(), _ctx(transfer=closed))
    assert t["flag_closed"] in text
    assert t["hint_closed"] in text
    assert t["hint_unverified"] not in text
    gone = AlertTransfer(status="unavailable", withdraw="closed")
    text = OpportunityFormatter(language=lang).render(make_evaluation(), _ctx(transfer=gone))
    assert "❌" in text
    assert t["hint_closed"] in text


def test_transfer_without_time_or_fee_usd() -> None:
    bare = AlertTransfer(status="verified", network="TRC20", fee_base="1", withdraw="open")
    text = OpportunityFormatter().render(make_evaluation(), _ctx(transfer=bare))
    assert "Transfer: <b>TRC20</b> · fee 1 ABC · time unknown" in text
    assert "❓ unknown" in text  # deposit state


def test_context_v1_falls_back_to_evaluation() -> None:
    evaluation = make_evaluation(
        transfer=TransferQuote(
            TransferStatus.VERIFIED,
            network="TRC20",
            fee_base=D(1),
            withdraw_state=LegState.OPEN,
            deposit_state=LegState.OPEN,
            est_arrival_min=D("2.5"),
        )
    )
    text = OpportunityFormatter().render(evaluation, AlertContext(episode_id=3))
    assert "Transfer: <b>TRC20</b> · fee 1 ABC (≈ $101.00) · ≈ 2.5 min (approx)" in text
    assert text.endswith("   ·   #3") is False or "Lifetime" not in text
    assert text.endswith("#3")


def test_html_escaping_and_limits() -> None:
    evaluation = make_evaluation(
        symbol="<A&B>/USDT",
        buy_exchange="<b>evil</b>",
        transfer=TransferQuote(TransferStatus.UNKNOWN, network="<i>x</i>", note="a<b>&c" * 900),
    )
    for lang in ("en", "ru"):
        formatter = OpportunityFormatter(language=lang)
        for text in (
            formatter.render(evaluation, _ctx()),
            formatter.render_closed(evaluation, _ctx()),
        ):
            assert "<A&B>" not in text
            assert "<b>evil</b>" not in text
            assert "&lt;A&amp;B&gt;" in text
            assert len(text) <= 4096


def test_new_template_is_compact() -> None:
    assert len(NEW_EN) <= 1200
    assert len(NEW_RU) <= 1200
    assert "<pre>" not in NEW_EN


def test_conditional_marker() -> None:
    fmt = OpportunityFormatter(("bybit", "gateio"))
    assert "conditional" not in fmt.render(make_evaluation())
    one = fmt.render(make_evaluation(sell_exchange="bybit"))
    assert "⚠️ conditional venue (Bybit)" in one.split("\n")[0]
    both = OpportunityFormatter(("bybit", "gateio"), "ru").render(
        make_evaluation(buy_exchange="bybit", sell_exchange="gateio")
    )
    assert "⚠️ условные биржи (Bybit, Gate.io)" in both.split("\n")[0]


def test_estimated_fees_and_requires_breakdown() -> None:
    assert "Taker fee is an estimate" in OpportunityFormatter().render(
        make_evaluation(fees_estimated=True)
    )
    with pytest.raises(ValueError, match="breakdown"):
        OpportunityFormatter().render(
            make_evaluation(status=EvaluationStatus.STALE_BOOK, with_breakdown=False)
        )


def test_catalogs_have_the_same_keys_and_no_secret_fields() -> None:
    assert CATALOGS["en"].keys() == CATALOGS["ru"].keys()
    assert "advice" in pinned_text("en")
    assert "не финансовый совет" in pinned_text("ru")
    assert pinned_text("xx") == pinned_text("en")


def test_signed_pct() -> None:
    assert signed_pct(D("1.123")) == "+1.12 %"
    assert signed_pct(D("-0.5")) == "-0.50 %"
