"""Key policy startup check (A6): fixture payloads only, no network, no real keys."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import ccxt.async_support as ccxt_async
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from nexus.adapters import cex  # noqa: F401  (registers adapters)
from nexus.adapters.key_policy import (
    ATTEST_GATEIO_PERMS,
    ATTEST_KUCOIN_IP,
    IP_UNBOUND,
    KEY_POLICIES,
    NO_POLICY,
    REQUEST_FAILED,
    UNPARSEABLE,
    verify_key_policies,
)
from nexus.adapters.registry import AdapterOptions, exchange_registry
from nexus.config.groups import CORE_EXCHANGES, ExchangeCredentials, KeyPolicySettings
from nexus.domain.errors import (
    ConfigurationError,
    ExchangeAuthError,
    ExchangeError,
    KeyPolicyViolationError,
    ReadOnlyViolationError,
)

FAKE_KEY = "AKIA-FAKE-KEY-1234"
FAKE_UID = "uid-99887766"
FAKE_LABEL = "my-secret-label"

BINANCE_OK: dict[str, Any] = {
    "ipRestrict": True,
    "createTime": 1,
    "enableReading": True,
    "enableWithdrawals": False,
    "enableInternalTransfer": False,
    "permitsUniversalTransfer": False,
    "enableVanillaOptions": False,
    "enableFixApiTrade": False,
    "enableFixReadOnly": True,
    "enableFutures": False,
    "enableMargin": False,
    "enableSpotAndMarginTrading": False,
    "enablePortfolioMarginTrading": False,
}
BYBIT_OK: dict[str, Any] = {
    "retCode": 0,
    "result": {
        "id": FAKE_UID,
        "apiKey": FAKE_KEY,
        "readOnly": 1,
        "ips": ["203.0.113.7"],
        "permissions": {"Spot": ["SpotTrade"], "Wallet": ["AccountTransfer"][:0]},
    },
}
OKX_OK: dict[str, Any] = {
    "code": "0",
    "data": [{"perm": "read_only", "ip": "203.0.113.7", "uid": FAKE_UID, "label": FAKE_LABEL}],
}
KUCOIN_OK: dict[str, Any] = {
    "code": "200000",
    "data": {"permission": "General", "apiKey": FAKE_KEY, "uid": FAKE_UID, "remark": FAKE_LABEL},
}
GATEIO_OK: dict[str, Any] = {"user_id": FAKE_UID, "ip_whitelist": ["203.0.113.7"], "tier": 1}
ATTESTED = KeyPolicySettings(kucoin_ip_attested=True, gateio_permissions_attested=True)
OK = {
    "binance": BINANCE_OK,
    "bybit": BYBIT_OK,
    "okx": OKX_OK,
    "kucoin": KUCOIN_OK,
    "gateio": GATEIO_OK,
}


def rules(venue: str, payload: Any, settings: KeyPolicySettings = ATTESTED) -> tuple[str, ...]:
    return KEY_POLICIES[venue].evaluate(payload, settings)


def mutated(base: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    clone = copy.deepcopy(base)
    change(clone)
    return clone


@pytest.mark.parametrize("venue", CORE_EXCHANGES)
def test_pass_case(venue: str) -> None:
    assert rules(venue, OK[venue]) == ()


@pytest.mark.parametrize("venue", CORE_EXCHANGES)
@pytest.mark.parametrize("bad", [None, [], "text", 42, {}])
def test_unparseable_or_empty_payload_refused(venue: str, bad: Any) -> None:
    assert rules(venue, bad)  # fail closed, whatever the shape


# ---------------------------------------------------------------- binance
@pytest.mark.parametrize(
    "flag",
    [
        "enableWithdrawals",
        "enableInternalTransfer",
        "permitsUniversalTransfer",
        "enableSpotAndMarginTrading",
        "enableMargin",
        "enableFutures",
        "enableVanillaOptions",
        "enablePortfolioMarginTrading",
        "enableFixApiTrade",
    ],
)
def test_binance_forbidden_permission(flag: str) -> None:
    assert rules("binance", {**BINANCE_OK, flag: True}) == (f"permission:{flag}",)


@pytest.mark.parametrize("flag", ["enableNewTrading", "permitsNewTransfer"])
def test_binance_unknown_new_flag_refused(flag: str) -> None:
    assert rules("binance", {**BINANCE_OK, flag: True}) == (f"permission:{flag}",)
    assert rules("binance", {**BINANCE_OK, flag: "yes"}) == (f"permission:{flag}",)
    assert rules("binance", {**BINANCE_OK, flag: False}) == ()


def test_binance_unknown_flag_name_is_not_echoed() -> None:
    result = rules("binance", {**BINANCE_OK, "enable<script>evil secret": True})
    assert result == ("permission:unexpected_scope",)


def test_binance_reading_disabled_and_ip_unbound() -> None:
    result = rules("binance", {**BINANCE_OK, "enableReading": False, "ipRestrict": False})
    assert result == ("permission:reading_disabled", IP_UNBOUND)


@pytest.mark.parametrize("field", ["enableWithdrawals", "enableReading", "ipRestrict"])
def test_binance_missing_field(field: str) -> None:
    payload = {k: v for k, v in BINANCE_OK.items() if k != field}
    assert rules("binance", payload) == (f"missing_or_invalid_field:{field}",)


def test_binance_non_bool_field_refused() -> None:
    assert rules("binance", {**BINANCE_OK, "enableMargin": "false"}) == (
        "missing_or_invalid_field:enableMargin",
    )


# ---------------------------------------------------------------- bybit
def test_bybit_not_read_only() -> None:
    payload = mutated(BYBIT_OK, lambda p: p["result"].update(readOnly=0))
    assert rules("bybit", payload) == ("permission:not_read_only",)


def test_bybit_submember_transfer_uses_fixed_rule_name() -> None:
    payload = mutated(
        BYBIT_OK, lambda p: p["result"]["permissions"].update(Wallet=["SubMemberTransferX!"])
    )
    assert rules("bybit", payload) == ("permission:Wallet.SubMemberTransfer",)


@pytest.mark.parametrize("item", ["Withdraw", "AccountTransfer"])
def test_bybit_wallet_scopes(item: str) -> None:
    payload = mutated(BYBIT_OK, lambda p: p["result"]["permissions"].update(Wallet=[item]))
    assert rules("bybit", payload) == (f"permission:Wallet.{item}",)


@pytest.mark.parametrize("ips", [[], ["*"], ["203.0.113.7", "0.0.0.0/0"], "", "*"])
def test_bybit_ip_unbound(ips: Any) -> None:
    payload = mutated(BYBIT_OK, lambda p: p["result"].update(ips=ips))
    assert rules("bybit", payload) == (IP_UNBOUND,)


def test_bybit_ips_as_comma_string_is_accepted() -> None:
    payload = mutated(BYBIT_OK, lambda p: p["result"].update(ips="203.0.113.7,203.0.113.8"))
    assert rules("bybit", payload) == ()


@pytest.mark.parametrize("field", ["readOnly", "ips", "permissions"])
def test_bybit_missing_field(field: str) -> None:
    payload = mutated(BYBIT_OK, lambda p: p["result"].pop(field))
    assert rules("bybit", payload) == (f"missing_or_invalid_field:{field}",)


def test_bybit_readonly_bool_is_not_accepted() -> None:
    payload = mutated(BYBIT_OK, lambda p: p["result"].update(readOnly=True))
    assert rules("bybit", payload) == ("missing_or_invalid_field:readOnly",)


def test_bybit_error_envelope_refused() -> None:
    assert rules("bybit", {"retCode": 10003, "result": {}}) == (UNPARSEABLE,)


# ---------------------------------------------------------------- okx
@pytest.mark.parametrize(
    ("perm", "expected"),
    [
        ("read_only,trade", ("permission:trade",)),
        ("read_only,withdraw", ("permission:withdraw",)),
        ("trade", ("permission:trade", "permission:read_only_absent")),
        ("read_only, trade ,withdraw", ("permission:trade", "permission:withdraw")),
    ],
)
def test_okx_permissions(perm: str, expected: tuple[str, ...]) -> None:
    payload = mutated(OKX_OK, lambda p: p["data"][0].update(perm=perm))
    assert rules("okx", payload) == expected


def test_okx_unknown_scope_refused() -> None:
    payload = mutated(OKX_OK, lambda p: p["data"][0].update(perm="read_only,margin_loan"))
    assert rules("okx", payload) == ("permission:margin_loan",)


def test_okx_weird_scope_text_not_echoed() -> None:
    payload = mutated(OKX_OK, lambda p: p["data"][0].update(perm=f"read_only,{FAKE_KEY}!"))
    assert rules("okx", payload) == ("permission:unexpected_scope",)


def test_kucoin_weird_scope_text_not_echoed() -> None:
    payload = mutated(KUCOIN_OK, lambda p: p["data"].update(permission=f"General,{'x' * 80}"))
    assert rules("kucoin", payload) == ("permission:unexpected_scope",)


@pytest.mark.parametrize(
    "ips", [["10.0.0.0/8"], ["0.0.0.0/4"], ["::/3"], ["203.0.113.7", "0.0.0.0/0"]]
)
def test_wide_cidr_counts_as_unbound(ips: list[str]) -> None:
    assert rules("gateio", {**GATEIO_OK, "ip_whitelist": ips}) == (IP_UNBOUND,)


def test_narrow_cidr_is_a_binding() -> None:
    assert rules("gateio", {**GATEIO_OK, "ip_whitelist": ["203.0.113.0/24", "bogus"]}) == ()


def test_okx_ip_empty_refused() -> None:
    payload = mutated(OKX_OK, lambda p: p["data"][0].update(ip=""))
    assert rules("okx", payload) == (IP_UNBOUND,)


@pytest.mark.parametrize("field", ["perm", "ip"])
def test_okx_missing_field(field: str) -> None:
    payload = mutated(OKX_OK, lambda p: p["data"][0].pop(field))
    assert rules("okx", payload) == (f"missing_or_invalid_field:{field}",)


@pytest.mark.parametrize("payload", [{"code": "50111", "data": []}, {"code": "0", "data": []}])
def test_okx_error_or_empty_data(payload: dict[str, Any]) -> None:
    assert rules("okx", payload) == (UNPARSEABLE,)


# ---------------------------------------------------------------- kucoin
@pytest.mark.parametrize(
    ("permission", "expected"),
    [
        ("General,Spot", ("permission:Spot",)),
        ("General,Withdrawal,InnerTransfer", ("permission:InnerTransfer", "permission:Withdrawal")),
        ("Spot", ("permission:Spot",)),
    ],
)
def test_kucoin_permissions(permission: str, expected: tuple[str, ...]) -> None:
    payload = mutated(KUCOIN_OK, lambda p: p["data"].update(permission=permission))
    assert rules("kucoin", payload) == expected


def test_kucoin_missing_permission() -> None:
    payload = mutated(KUCOIN_OK, lambda p: p["data"].pop("permission"))
    assert rules("kucoin", payload) == ("missing_or_invalid_field:permission",)


def test_kucoin_error_code() -> None:
    assert rules("kucoin", {"code": "400003", "data": None}) == (UNPARSEABLE,)


# ---------------------------------------------------------------- gateio
@pytest.mark.parametrize("ips", [[], ["0.0.0.0/0"]])
def test_gateio_ip_unbound(ips: list[str]) -> None:
    assert rules("gateio", {**GATEIO_OK, "ip_whitelist": ips}) == (IP_UNBOUND,)


def test_gateio_missing_whitelist() -> None:
    payload = {k: v for k, v in GATEIO_OK.items() if k != "ip_whitelist"}
    assert rules("gateio", payload) == ("missing_or_invalid_field:ip_whitelist",)


# ---------------------------------------------------------------- attestation
def test_attestation_required_for_kucoin_and_gateio() -> None:
    none = KeyPolicySettings()
    assert rules("kucoin", KUCOIN_OK, none) == (ATTEST_KUCOIN_IP,)
    assert rules("gateio", GATEIO_OK, none) == (ATTEST_GATEIO_PERMS,)
    for venue in ("binance", "bybit", "okx"):
        assert rules(venue, OK[venue], none) == ()


def test_attestation_flags_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEY_POLICY_KUCOIN_IP_ATTESTED", "true")
    settings = KeyPolicySettings()
    assert settings.kucoin_ip_attested is True
    assert settings.gateio_permissions_attested is False


# ---------------------------------------------------------------- runner
class FakeAdapter:
    def __init__(self, payload: Any = None, error: BaseException | None = None) -> None:
        self.payload, self.error, self.calls = payload, error, 0

    async def fetch_key_info(self) -> Any:
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def creds(configured: bool = True) -> ExchangeCredentials:
    if not configured:
        return ExchangeCredentials()
    return ExchangeCredentials(api_key=SecretStr("k"), api_secret=SecretStr("s"))


async def test_runner_passes_and_calls_once_per_venue() -> None:
    adapters = {v: FakeAdapter(OK[v]) for v in CORE_EXCHANGES}
    await verify_key_policies(adapters, dict.fromkeys(CORE_EXCHANGES, creds()), ATTESTED)
    assert all(a.calls == 1 for a in adapters.values())


async def test_runner_skips_venue_without_key() -> None:
    adapter = FakeAdapter({"would": "fail"})
    await verify_key_policies({"binance": adapter}, {"binance": creds(False)}, KeyPolicySettings())
    await verify_key_policies({"binance": adapter}, {}, KeyPolicySettings())
    assert adapter.calls == 0


async def test_runner_refuses_and_names_venue_and_rule() -> None:
    adapters = {
        "binance": FakeAdapter({**BINANCE_OK, "enableWithdrawals": True}),
        "okx": FakeAdapter(OKX_OK),
        "bybit": FakeAdapter(BYBIT_OK),
    }
    with pytest.raises(KeyPolicyViolationError) as info:
        await verify_key_policies(
            adapters,
            {n: creds() for n in adapters},
            KeyPolicySettings(),
        )
    assert info.value.violations == {"binance": ("permission:enableWithdrawals",)}
    assert "binance" in str(info.value)
    assert "permission:enableWithdrawals" in str(info.value)


async def test_runner_request_failure_is_refused_without_leaking_message() -> None:
    adapter = FakeAdapter(error=ExchangeAuthError("okx", f"bad key {FAKE_KEY}"))
    with capture_logs() as logs, pytest.raises(KeyPolicyViolationError) as info:
        await verify_key_policies({"okx": adapter}, {"okx": creds()}, KeyPolicySettings())
    assert info.value.violations == {"okx": (REQUEST_FAILED,)}
    assert FAKE_KEY not in json.dumps(logs, default=str)
    assert FAKE_KEY not in str(info.value)


@pytest.mark.parametrize(
    "error", [ReadOnlyViolationError("x"), ConfigurationError("x"), ValueError(FAKE_KEY)]
)
async def test_runner_any_exception_is_request_failed_and_others_continue(
    error: BaseException,
) -> None:
    adapters = {"okx": FakeAdapter(error=error), "bybit": FakeAdapter(BYBIT_OK)}
    with capture_logs() as logs, pytest.raises(KeyPolicyViolationError) as info:
        await verify_key_policies(adapters, {n: creds() for n in adapters}, KeyPolicySettings())
    assert info.value.violations == {"okx": (REQUEST_FAILED,)}
    assert adapters["bybit"].calls == 1
    assert FAKE_KEY not in json.dumps(logs, default=str)
    assert any(
        e["event"] == "key_policy_request_failed" and e["error"] == type(error).__name__
        for e in logs
    )


async def test_runner_refuses_key_on_venue_without_policy() -> None:
    with pytest.raises(KeyPolicyViolationError) as info:
        await verify_key_policies({"mexc": FakeAdapter({})}, {"mexc": creds()}, ATTESTED)
    assert info.value.violations == {"mexc": (NO_POLICY,)}


async def test_runner_refuses_adapter_without_introspection() -> None:
    with pytest.raises(KeyPolicyViolationError):
        await verify_key_policies({"binance": object()}, {"binance": creds()}, ATTESTED)


async def test_logs_contain_no_response_fields() -> None:
    adapters = {
        "okx": FakeAdapter(mutated(OKX_OK, lambda p: p["data"][0].update(perm="read_only,trade"))),
        "kucoin": FakeAdapter(KUCOIN_OK),
        "bybit": FakeAdapter(BYBIT_OK),
    }
    with capture_logs() as logs, pytest.raises(KeyPolicyViolationError) as info:
        await verify_key_policies(adapters, {n: creds() for n in adapters}, KeyPolicySettings())
    dump = json.dumps(logs, default=str) + str(info.value)
    for secret in (FAKE_KEY, FAKE_UID, FAKE_LABEL, "203.0.113.7"):
        assert secret not in dump
    assert any(entry["event"] == "key_policy_checked" for entry in logs)


async def test_parser_bug_refuses_instead_of_crashing_open() -> None:
    def boom(_: Any) -> tuple[str, ...]:
        raise RuntimeError(FAKE_KEY)

    check = type(KEY_POLICIES["okx"])("okx", boom)
    with capture_logs() as logs:
        assert check.evaluate({}, ATTESTED) == (UNPARSEABLE,)
    assert any(e["event"] == "key_policy_parser_error" for e in logs)
    assert FAKE_KEY not in json.dumps(logs, default=str)


# ---------------------------------------------------------------- adapter + guard
CREDS_ALL = ExchangeCredentials(
    api_key=SecretStr("k"), api_secret=SecretStr("s"), api_passphrase=SecretStr("p")
)


@pytest.mark.parametrize("venue", exchange_registry.names())
async def test_get_only_guard_on_every_authenticated_client(venue: str) -> None:
    adapter = exchange_registry.create(venue, CREDS_ALL, AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]  # the client fetch_key_info uses
        assert client.apiKey  # authenticated
        assert client.nexus_read_only_guard is True
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            with pytest.raises(ReadOnlyViolationError):
                await client.fetch("https://example.invalid/x", method)
    finally:
        await adapter.close()


@pytest.mark.parametrize("venue", CORE_EXCHANGES)
async def test_fetch_key_info_issues_only_a_get(
    venue: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []

    async def fake_transport(
        self: Any, url: str, method: str = "GET", headers: Any = None, body: Any = None
    ) -> Any:
        seen.append((str(method).upper(), url))
        return OK[venue]

    # Patch ccxt's HTTP layer below the guard (installed at adapter construction).
    monkeypatch.setattr(ccxt_async.Exchange, "fetch", fake_transport)
    adapter = exchange_registry.create(venue, CREDS_ALL, AdapterOptions())
    try:
        assert adapter._rest.nexus_read_only_guard is True  # type: ignore[attr-defined]
        payload = await adapter.fetch_key_info()  # type: ignore[attr-defined]
    finally:
        await adapter.close()
    assert payload == OK[venue]
    assert len(seen) == 1  # one call per venue
    assert seen[0][0] == "GET"
    assert not any(w in seen[0][1].lower() for w in ("withdraw", "transfer", "order"))


async def test_fetch_key_info_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def failing_transport(self: Any, *_: Any, **__: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ccxt_async.NetworkError("boom")

    monkeypatch.setattr(ccxt_async.Exchange, "fetch", failing_transport)
    adapter = exchange_registry.create("okx", CREDS_ALL, AdapterOptions())
    try:
        with pytest.raises(ExchangeError):
            await adapter.fetch_key_info()  # type: ignore[attr-defined]
    finally:
        await adapter.close()
    assert calls == 1


# ---------------------------------------------------------------- startup wiring
async def test_scanner_scope_verifies_keys_before_anything_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus import container

    closed: list[str] = []

    class Stub:
        async def close(self) -> None:
            closed.append("adapter")

    async def refuse(*_: Any) -> None:
        raise KeyPolicyViolationError({"binance": ("permission:enableWithdrawals",)})

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("must not be reached after a key policy violation")

    monkeypatch.setattr(container, "build_adapters", lambda _s: {"binance": Stub()})
    monkeypatch.setattr(container, "verify_key_policies", refuse)
    monkeypatch.setattr(container, "create_engine", forbidden)
    settings: Any = type("S", (), {"credentials": {}, "key_policy": KeyPolicySettings()})()
    with pytest.raises(KeyPolicyViolationError):
        async with container.scanner_scope(settings):
            pass
    assert closed == ["adapter"]


def test_cli_exits_non_zero_on_key_policy_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus import cli

    async def refuse() -> None:
        raise KeyPolicyViolationError({"okx": ("permission:trade",)})

    monkeypatch.setattr(cli, "_run_scanner", refuse)
    assert cli.main(["scanner"]) == cli.EXIT_KEY_POLICY != 0
