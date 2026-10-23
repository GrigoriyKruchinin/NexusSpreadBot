"""B15: PAPER_VENUE_SETS parsing and validation (fail closed, errors name the set/venue)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from nexus.config import ScannerRoleSettings
from nexus.config.groups import PaperSettings
from nexus.config.venue_sets import ALL_SET, DEFAULT_VENUE_SETS, resolve_venue_sets

ENABLED = ("binance", "bybit", "gateio", "kucoin", "okx")
CONDITIONAL = ("bybit", "gateio")


def resolve(spec: str = DEFAULT_VENUE_SETS, **kwargs: object) -> dict[str, tuple[str, ...]]:
    return resolve_venue_sets(spec, ENABLED, CONDITIONAL, strict=True, **kwargs)


def test_default_has_all_and_excl_conditional() -> None:
    sets = resolve()
    assert sets == {
        "all": ENABLED,
        "excl_conditional": ("binance", "kucoin", "okx"),
    }
    assert next(iter(sets)) == ALL_SET


def test_extra_set_is_one_line_exclusion() -> None:
    sets = resolve("all;excl_conditional;excl_gateio=-gateio")
    assert sets["excl_gateio"] == ("binance", "bybit", "kucoin", "okx")


def test_explicit_include_and_multiple_exclusions() -> None:
    sets = resolve("all;core3=binance,okx,kucoin;ex2=-gateio,-bybit")
    assert sets["core3"] == ("binance", "kucoin", "okx")  # enabled order, not spec order
    assert sets["ex2"] == ("binance", "kucoin", "okx")


def test_case_and_whitespace_are_normalized() -> None:
    sets = resolve(" ALL ; Excl_Gateio = -GateIO ")
    assert set(sets) == {"all", "excl_gateio"}
    assert "gateio" not in sets["excl_gateio"]


def test_all_set_must_be_present() -> None:
    with pytest.raises(ValueError, match="'all'"):
        resolve("excl_conditional")


def test_all_set_cannot_be_redefined() -> None:
    with pytest.raises(ValueError, match="'all'"):
        resolve("all=-gateio")


@pytest.mark.parametrize("name", ["Bad-Name", "has space", "a" * 33, "ünï"])
def test_bad_set_name(name: str) -> None:
    with pytest.raises(ValueError, match="set name"):
        resolve(f"all;{name}=-gateio")


def test_duplicate_set_name() -> None:
    with pytest.raises(ValueError, match=r"duplicate.*'x'"):
        resolve("all;x=-gateio;X=-bybit")


def test_unknown_venue_names_set_and_venue() -> None:
    with pytest.raises(ValueError, match=r"set 'typo'.*gatio"):
        resolve("all;typo=-gatio")
    with pytest.raises(ValueError, match=r"set 'inc'.*mexc"):
        resolve("all;inc=binance,mexc")


def test_single_venue_set_rejected() -> None:
    with pytest.raises(ValueError, match=r"set 'one'.*at least 2"):
        resolve("all;one=binance")
    with pytest.raises(ValueError, match=r"set 'none'.*at least 2"):
        resolve("all;none=-binance,-bybit,-gateio,-kucoin")


def test_mixed_signs_rejected() -> None:
    with pytest.raises(ValueError, match=r"set 'mix'.*mix"):
        resolve("all;mix=binance,-gateio")


def test_empty_spec_and_empty_entry_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        resolve("")
    with pytest.raises(ValueError, match="empty"):
        resolve("all;;x=-gateio")


def test_unknown_builtin_name_without_spec_rejected() -> None:
    with pytest.raises(ValueError, match=r"set 'foo' needs"):
        resolve("all;foo")


def test_duplicate_venue_in_set_rejected() -> None:
    with pytest.raises(ValueError, match=r"set 'd'.*binance.*twice"):
        resolve("all;d=binance,binance,okx")


def test_identical_to_all_rejected_when_strict() -> None:
    with pytest.raises(ValueError, match=r"set 'same'.*identical to 'all'"):
        resolve("all;same=binance,bybit,gateio,kucoin,okx")


def test_implicit_default_drops_degenerate_excl_conditional() -> None:
    # EXCHANGES_ENABLED narrowed so that excl_conditional is empty/identical: not an error
    sets = resolve_venue_sets(DEFAULT_VENUE_SETS, ("binance", "bybit"), ("bybit",), strict=False)
    assert sets == {"all": ("binance", "bybit")}
    same = resolve_venue_sets(DEFAULT_VENUE_SETS, ("binance", "okx"), (), strict=False)
    assert same == {"all": ("binance", "okx")}


def test_paper_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    paper = PaperSettings()
    assert paper.capital_usd == Decimal(10_000)
    assert paper.venue_sets == DEFAULT_VENUE_SETS


def test_paper_settings_rejects_bad_syntax_early(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_VENUE_SETS", "all;Bad Name=-x")
    with pytest.raises(ValidationError, match="set name"):
        PaperSettings()
    monkeypatch.setenv("PAPER_CAPITAL_USD", "0")
    monkeypatch.setenv("PAPER_VENUE_SETS", "all")
    with pytest.raises(ValidationError):
        PaperSettings()


def _scanner_env(monkeypatch: pytest.MonkeyPatch, enabled: str) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "x" * 16)
    monkeypatch.setenv("EXCHANGES_ENABLED", enabled)


def test_scanner_role_resolves_sets(monkeypatch: pytest.MonkeyPatch) -> None:
    _scanner_env(monkeypatch, "binance,bybit,gateio,kucoin,okx")
    monkeypatch.setenv("PAPER_VENUE_SETS", "all;excl_conditional;excl_gateio=-gateio")
    settings = ScannerRoleSettings.load()
    assert set(settings.venue_sets) == {"all", "excl_conditional", "excl_gateio"}


def test_scanner_role_fails_closed_on_explicit_unknown_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scanner_env(monkeypatch, "binance,okx,kucoin")
    monkeypatch.setenv("PAPER_VENUE_SETS", "all;oops=-bybit")
    with pytest.raises(ValidationError, match=r"oops.*bybit"):
        ScannerRoleSettings.load()


def test_scanner_role_narrow_enabled_default_sets_do_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scanner_env(monkeypatch, "binance,bybit")  # conditional defaults to (bybit,): 1 venue left
    assert ScannerRoleSettings.load().venue_sets == {"all": ("binance", "bybit")}
