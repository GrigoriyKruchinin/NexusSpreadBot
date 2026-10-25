"""HT1 S10: the JSON codec of positions and pool state round-trips exactly (no database)."""

from decimal import Decimal as D

import pytest

from nexus.interfaces.repositories import HedgedPoolState
from nexus.persistence.hedged_repository import (
    HedgedPayloadVersionError,
    payload_to_position,
    payload_to_state,
    position_to_payload,
    state_to_payload,
)
from nexus.simulation.hedged import evaluate_entry
from nexus.simulation.hedged_portfolio import (
    HedgedPortfolio,
    HedgedPosition,
    HedgedStatus,
    PnlLines,
    Rebalance,
)
from tests.unit.simulation.hedged_fixtures import config, request


def _position() -> HedgedPosition:
    cfg = config(p_stuck=0.0)
    req = request()
    port = HedgedPortfolio(cfg, ["okx", "kucoin", "binance"], "h")
    decision = evaluate_entry(cfg, req, port.entry_state())
    assert decision.plan is not None
    return port.open_position(decision.plan, req, "k1")


def test_position_round_trip_is_exact() -> None:
    pos = _position()
    pos.funding_times.update({1_000, 2_000})
    pos.funding_total = D("0.123456789012345678")
    pos.status = HedgedStatus.CLOSED
    pos.lines = PnlLines(s=D("1.5"), r=D("-0.25"), liquidation=D("3"))
    pos.last_perp_price = D("101.0000000001")
    back = payload_to_position(position_to_payload(pos))
    assert back == pos
    assert isinstance(back.funding_times, set)
    assert back.lines is not None
    assert back.lines.total == pos.lines.total


def test_position_without_lines_round_trips() -> None:
    pos = _position()
    assert payload_to_position(position_to_payload(pos)) == pos


def test_pool_state_round_trip() -> None:
    state = HedgedPoolState(
        pools={"okx": D("3333.33"), "kucoin": D("1")},
        rebalances=[Rebalance("okx", "kucoin", D(500), D("1.5"), 10, 20)],
        rebalance_fee_paid=D("0.75"),
    )
    assert payload_to_state(state_to_payload(state)) == state


def test_payloads_carry_a_version() -> None:
    assert position_to_payload(_position())["payload_version"] == 1
    assert (
        state_to_payload(HedgedPoolState(pools={}, rebalances=[], rebalance_fee_paid=D(0)))[
            "payload_version"
        ]
        == 1
    )


@pytest.mark.parametrize("bad", [None, 0, 2, "1"])
def test_unknown_payload_version_is_rejected_loudly(bad: object) -> None:
    pos_payload = position_to_payload(_position())
    state_payload = state_to_payload(
        HedgedPoolState(pools={}, rebalances=[], rebalance_fee_paid=D(0))
    )
    for payload, loader in ((pos_payload, payload_to_position), (state_payload, payload_to_state)):
        broken = dict(payload)
        if bad is None:
            del broken["payload_version"]
        else:
            broken["payload_version"] = bad
        with pytest.raises(HedgedPayloadVersionError, match="payload_version"):
            loader(broken)
