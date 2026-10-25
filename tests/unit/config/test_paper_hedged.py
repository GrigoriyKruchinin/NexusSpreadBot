"""HT1 S11: PaperHedgedSettings, set syntax, HedgedConfig mapping and the run hash."""

from decimal import Decimal as D
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.config import ScannerRoleSettings
from nexus.config.groups import PaperHedgedSettings
from nexus.config.hedged_sets import normalize_hedged_sets, parse_hedged_sets, parse_perp_fees
from nexus.simulation.hedged_run import build_hedged_config, hedged_run_hash, hedged_set_specs

REPO_TOML = Path(__file__).resolve().parents[3] / "config" / "nexus.toml"

PINNED_HASHES = {
    "ht_excl_conditional": "cd98dc5883afd560ad490ac74c99f67d0caadadf983cf5079d7c641190e42c67",
    "ht_excl_conditional_bn": "3df56cf084760c9f6f32c050194a4ec4cd8f572fc94ecb1656c4f5972364412e",
}


def test_defaults_disabled_two_sets() -> None:
    s = PaperHedgedSettings()
    assert s.enabled is False
    specs = hedged_set_specs(s)
    assert [x.set_id for x in specs] == ["ht_excl_conditional", "ht_excl_conditional_bn"]
    assert specs[0].hedge_venues == ("okx", "kucoin")
    assert specs[1].hedge_venues == ("binance", "okx", "kucoin")
    assert specs[0].spot_venues == ("binance", "okx", "kucoin")


def test_committed_toml_matches_defaults_and_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(REPO_TOML))
    from_file = PaperHedgedSettings()
    assert from_file.enabled is False
    monkeypatch.delenv("NEXUS_CONFIG_FILE")
    assert from_file == PaperHedgedSettings()


def test_config_mapping_uses_fractions() -> None:
    cfg = build_hedged_config(PaperHedgedSettings())
    assert cfg.mmr_default == D("0.025")
    assert cfg.liq_min_distance == D("0.30")
    assert cfg.max_slippage == D("0.005")
    assert cfg.max_funding_cost == D("0.003")
    assert cfg.leg_risk_reserve == D("0.0005")
    assert cfg.perp_taker_fee["kucoin"] == D("0.0006")
    assert cfg.basis_pair_tolerance_ms == 15_000
    assert cfg.route_cooldown_ms == 60_000


@pytest.mark.parametrize(
    "spec",
    ["", "a", "a=", "a=okx;a=kucoin", "a=okx,okx", "a=bybit", "A B=okx", f"{'x' * 33}=okx"],
)
def test_bad_sets_rejected(spec: str) -> None:
    with pytest.raises(ValueError, match="PAPER_HEDGED_SETS"):
        parse_hedged_sets(spec)


def test_sets_normalized() -> None:
    assert normalize_hedged_sets(" A = OKX , kucoin ") == "a=okx,kucoin"


@pytest.mark.parametrize("spec", ["okx", "okx=x", "bybit=0.1", "okx=-1", "okx=5"])
def test_bad_fees_rejected(spec: str) -> None:
    with pytest.raises(ValueError, match="PERP_TAKER_FEE"):
        parse_perp_fees(spec)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"leverage": 0},
        {"leverage": 6},
        {"min_net_profit_pct": 0},
        {"trade_notional_usd": 0},
        {"spot_venues": "okx"},
        {"spot_venues": "okx,okx"},
        {"sets": "x=bybit"},
        {"sets": "x=binance", "spot_venues": "okx,kucoin"},
        {"p_stuck": 1},
    ],
)
def test_invalid_values_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PaperHedgedSettings(**kwargs)  # type: ignore[arg-type]


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_HEDGED_LEVERAGE", "3")
    monkeypatch.setenv("PAPER_HEDGED_ENABLED", "true")
    s = PaperHedgedSettings()
    assert s.leverage == D(3)
    assert s.enabled is True


def test_enabled_spot_venues_must_be_exchanges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw-" + "x" * 16)
    monkeypatch.setenv("EXCHANGES_ENABLED", "binance,okx")
    monkeypatch.setenv("CONDITIONAL_VENUES", "")
    monkeypatch.setenv("PAPER_HEDGED_ENABLED", "true")
    with pytest.raises(ValidationError, match="PAPER_HEDGED_SPOT_VENUES"):
        ScannerRoleSettings.load()


def test_hash_is_stable_and_per_set() -> None:
    s = PaperHedgedSettings()
    a, b = hedged_set_specs(s)
    assert hedged_run_hash(s, a) == hedged_run_hash(PaperHedgedSettings(), a)
    assert hedged_run_hash(s, a) != hedged_run_hash(s, b)
    assert len(hedged_run_hash(s, a)) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"capital_usd": 9000},
        {"leverage": 3},
        {"mmr_pct": 3},
        {"perp_taker_fee_pct": "binance=0.05,okx=0.06,kucoin=0.06"},
        {"min_net_profit_pct": "0.4"},
        {"basis_window_h": 5},
        {"basis_spot_max_age_s": 10},
        {"max_open_per_coin": 2},
        {"p_stuck": 0.02},
        {"latency_ms": 1000},
        {"perp_ticker_interval_s": 20},
        {"funding_refresh_s": 30},
        {"spot_venues": "binance,okx,kucoin,gateio"},
        {
            "hedge_policy": "best",
            "sets": "ht_excl_conditional=okx;ht_excl_conditional_bn=binance,okx,kucoin",
        },
    ],
)
def test_hash_changes_with_any_parameter(change: dict[str, object]) -> None:
    base = PaperHedgedSettings()
    spec = hedged_set_specs(base)[0]
    changed = PaperHedgedSettings(**change)  # type: ignore[arg-type]
    cspec = hedged_set_specs(changed)[0]
    assert hedged_run_hash(changed, cspec) != hedged_run_hash(base, spec)


def test_run_hash_pins_committed_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-registration pins (docs/quant/ht-preregistration.md): a change here is a new run."""
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(REPO_TOML))
    s = PaperHedgedSettings()
    hashes = {x.set_id: hedged_run_hash(s, x) for x in hedged_set_specs(s)}
    assert hashes == PINNED_HASHES


def test_hash_ignores_spelling() -> None:
    a = PaperHedgedSettings(leverage=D(2))
    b = PaperHedgedSettings(leverage=D("2.0"))
    assert hedged_run_hash(a, hedged_set_specs(a)[0]) == hedged_run_hash(b, hedged_set_specs(b)[0])
