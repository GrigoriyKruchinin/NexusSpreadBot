"""Alert payload: approved fields, honest unknowns, rounding, versioned decoding."""

from dataclasses import replace
from decimal import Decimal as D

from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.events import ALERT_PAYLOAD_VERSION, AlertContext, AlertLifetime
from nexus.domain.spread import (
    ExecutableVolume,
    LegState,
    SpreadEvaluation,
    TransferQuote,
    TransferStatus,
)
from tests.support import EVALUATED_AT_MS as T0
from tests.support import make_evaluation

VOLUME = ExecutableVolume(
    scanned_base=D("10.123456789"),
    scanned_quote=D("1000.005"),
    max_base=D(19),
    max_quote=D("1918"),
    max_net_usd=D("1.5"),
)


def _evaluation(
    transfer: TransferQuote, volume: ExecutableVolume | None = VOLUME
) -> SpreadEvaluation:
    return replace(make_evaluation(transfer=transfer), volume=volume)


def test_verified_transfer_block_and_rounding() -> None:
    quote = TransferQuote(
        TransferStatus.VERIFIED,
        network="BEP20",
        fee_base=D("0.8"),
        withdraw_state=LegState.OPEN,
        deposit_state=LegState.CLOSED,
        withdraw_min=D("0.001"),
        deposit_min=D("2"),
        deposit_confirmations=15,
        est_arrival_min=D("2.04"),
        arrival_source="table",
        busy=False,
        contract_verified=True,
    )
    ctx = AlertContext.build(_evaluation(quote), None)
    transfer = ctx.transfer
    assert transfer is not None
    assert (transfer.status, transfer.network) == ("verified", "BEP20")
    assert transfer.fee_base == "0.8"
    assert transfer.fee_usd == "80.8"  # 0.8 * vwap_sell 101
    assert (transfer.withdraw, transfer.deposit) == ("open", "closed")
    assert (transfer.est_arrival_min, transfer.arrival_source) == ("2", "table")
    assert transfer.deposit_min == "2"
    assert transfer.deposit_confirmations == 15
    assert transfer.busy is False
    assert transfer.contract_verified
    volume = ctx.volume
    assert volume is not None
    assert volume.scanned_base == "10.12345679"  # 8 dp, half up
    assert volume.scanned_quote == "1000.01"  # 2 dp, half up
    assert (volume.max_base, volume.max_quote, volume.max_net_usd) == ("19", "1918", "1.5")


def test_unknown_transfer_has_no_fee_and_unknown_flags() -> None:
    quote = TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata")
    ctx = AlertContext.build(_evaluation(quote), None)
    transfer = ctx.transfer
    assert transfer is not None
    assert transfer.status == "unknown"
    assert transfer.fee_base is None
    assert transfer.fee_usd is None
    assert transfer.est_arrival_min is None
    assert (transfer.withdraw, transfer.deposit) == ("unknown", "unknown")
    assert transfer.note == "no source transfer metadata"


def test_tiny_fee_usd_keeps_four_places() -> None:
    quote = TransferQuote(TransferStatus.VERIFIED, network="SOL", fee_base=D("0.0003"))
    transfer = AlertContext.build(_evaluation(quote), None).transfer
    assert transfer is not None
    assert transfer.fee_usd == "0.0303"


def test_no_volume_when_evaluation_has_none() -> None:
    quote = TransferQuote(TransferStatus.VERIFIED, network="SOL", fee_base=D(0))
    assert AlertContext.build(_evaluation(quote, None), None).volume is None


def test_lifetime_from_episode_open_and_closed() -> None:
    evaluation = make_evaluation()
    episode = OpportunityEpisode.open(evaluation)
    later = episode.extend(replace(evaluation, evaluated_at_ms=T0 + 90_000))
    ctx = AlertContext.build(evaluation, later)
    assert ctx.lifetime == AlertLifetime(T0, T0 + 90_000, None)
    assert ctx.lifetime is not None
    assert ctx.lifetime.lifetime_ms() == 90_000
    assert ctx.lifetime.lifetime_ms(T0 + 100_000) == 100_000
    closed = later.close(T0 + 120_000, EpisodeCloseReason.GAP)
    life = AlertContext.build(evaluation, closed).lifetime
    assert life == AlertLifetime(T0, T0 + 90_000, T0 + 120_000)
    assert life is not None
    assert life.lifetime_ms(T0 + 999_000) == 120_000  # closed: now is irrelevant
    assert AlertContext.build(evaluation, None).lifetime is None


def test_episode_lifetime_accessor() -> None:
    evaluation = make_evaluation()
    episode = OpportunityEpisode.open(evaluation)
    assert episode.lifetime_ms() == 0
    assert episode.lifetime_ms(T0 + 5_000) == 5_000
    assert episode.lifetime_ms(T0 - 5_000) == 0
    closed = episode.close(T0 + 7_000, EpisodeCloseReason.GAP)
    assert closed.lifetime_ms(T0 + 99_000) == 7_000


def test_payload_roundtrip_is_json_safe_and_versioned() -> None:
    quote = TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D(1))
    episode = OpportunityEpisode.open(make_evaluation())
    ctx = AlertContext.build(_evaluation(quote), episode, realert=1, previous_net_usd=D("3.50"))
    payload = ctx.to_payload()
    assert payload["v"] == ALERT_PAYLOAD_VERSION == 2
    assert payload["previous_net_usd"] == "3.5"
    import json

    assert AlertContext.from_payload(json.loads(json.dumps(payload))) == ctx


def test_old_in_flight_payload_decodes_as_version_1() -> None:
    ctx = AlertContext.from_payload({"episode_id": 4, "realert": 2, "previous_net_usd": "9"})
    assert (ctx.episode_id, ctx.realert, ctx.previous_net_usd) == (4, 2, "9")
    assert (ctx.v, ctx.volume, ctx.transfer, ctx.lifetime) == (1, None, None, None)
    assert AlertContext.from_payload(None) == AlertContext()
    assert AlertContext.from_payload({}) == AlertContext()


def test_newer_payload_ignores_unknown_keys_and_bad_blocks() -> None:
    payload = {
        "episode_id": 1,
        "v": 3,
        "future": {"x": 1},
        "lifetime": {"opened_at_ms": 1, "last_seen_at_ms": 2, "closed_at_ms": None, "new": 5},
        "transfer": {"unexpected": "shape"},  # missing required field -> block dropped
        "volume": "garbage",
    }
    ctx = AlertContext.from_payload(payload)
    assert ctx.v == 3
    assert ctx.lifetime == AlertLifetime(1, 2, None)
    assert ctx.transfer is None
    assert ctx.volume is None
