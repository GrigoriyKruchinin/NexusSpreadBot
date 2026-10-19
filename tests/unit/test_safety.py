"""Hard safety rule: the bot never withdraws, transfers or trades (V1). See CLAUDE.md.

Two layers are tested:

1. Static (AST): no call in ``src/`` targets a fund-moving / order endpoint, including ccxt
   implicit API names, and ``getattr`` is only used with allow-listed targets.
2. Runtime: the read-only guard installed on every authenticated ccxt client blocks any
   non-GET request, even through implicit API methods or ``request()``.
"""

import ast
import re
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

import nexus.adapters.cex  # noqa: F401 - registers adapters
from nexus.adapters.cex.ccxt_base import install_read_only_guard
from nexus.adapters.registry import AdapterOptions, exchange_registry
from nexus.config.groups import ExchangeCredentials
from nexus.domain.errors import ReadOnlyViolationError

SRC = Path(__file__).resolve().parents[2] / "src"

_FORBIDDEN_CALL = re.compile(
    r"(?i)^("
    r".*withdraw.*|.*transfer.*|.*deposit_?address.*|"
    r"create_?\w*order\w*|cancel\w*order\w*|edit_?\w*order\w*|"
    r"fetch2?|request|sign|"
    r"(private|sapi|papi|fapi|dapi|v\d)\w*(post|put|delete)\w*"
    r")$"
)
_ALLOWED_CALLS = frozenset(
    {
        "fetch_deposit_withdraw_fees",  # ccxt read-only (GET) fee table
        "load_transfer_info",  # our read-only metadata interface
        "select_transfer_route",  # pure route selection (engine)
        "transfer_info",  # universe lookup
    }
)
_ALLOWED_GETATTR_TARGETS = frozenset({"ccxt_async", "ccxt_pro"})  # adapter class lookup


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _is_candidate(name: str) -> bool:
    # ccxt methods are snake_case or lowerCamel; skip our classes and private helpers.
    return not (name[:1].isupper() or name.startswith("_")) and name not in _ALLOWED_CALLS


def _imports_ccxt(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.startswith("ccxt") for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ccxt"):
            return True
    return False


def _violations_in(tree: ast.AST, label: str) -> list[str]:
    found: list[str] = []
    check_dynamic = _imports_ccxt(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        where = f"{label}:{node.lineno}"
        name = _call_name(node)
        if name and _is_candidate(name) and _FORBIDDEN_CALL.match(name):
            found.append(f"{where}: call to {name}()")
        if name == "getattr" and len(node.args) >= 2:
            target, attr = node.args[0], node.args[1]
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                if _FORBIDDEN_CALL.match(attr.value):
                    found.append(f"{where}: getattr(..., {attr.value!r})")
            elif check_dynamic and not (
                isinstance(target, ast.Name) and target.id in _ALLOWED_GETATTR_TARGETS
            ):
                found.append(f"{where}: dynamic getattr on {ast.unparse(target)}")
    return found


def test_no_fund_moving_or_order_calls_in_source() -> None:
    violations = [
        violation
        for path in SRC.rglob("*.py")
        for violation in _violations_in(
            ast.parse(path.read_text(), filename=str(path)), str(path.relative_to(SRC))
        )
    ]
    assert not violations, "forbidden calls:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    "snippet",
    [
        "client.withdraw('USDT', 1, 'addr')",
        "client.sapiPostCapitalWithdrawApply({})",
        "client.privatePostAssetTransfer({})",
        "client.sapi_post_asset_transfer({})",
        "client.private_withdrawals_post_withdrawals({})",
        "client.fetch_deposit_addresses_by_network('USDT')",
        "client.create_order('BTC/USDT', 'market', 'buy', 1)",
        "client.request('capital/withdraw/apply', 'sapi', 'POST')",
        "getattr(client, 'withdraw')('USDT', 1)",
        "import ccxt\ngetattr(client, name)()",
    ],
)
def test_guard_detects_known_bypasses(snippet: str) -> None:
    assert _violations_in(ast.parse(snippet), "snippet")


def test_no_withdraw_method_on_interfaces() -> None:
    from nexus.interfaces import market_data

    for name in dir(market_data):
        obj = getattr(market_data, name)
        if isinstance(obj, type) and obj.__module__ == market_data.__name__:
            assert not any(a.lower().startswith(("withdraw", "transfer")) for a in dir(obj)), name


# ------------------------------------------------------------------ runtime guard

_CREDS = {
    "binance": ExchangeCredentials(api_key=SecretStr("k"), api_secret=SecretStr("s")),
    "okx": ExchangeCredentials(
        api_key=SecretStr("k"), api_secret=SecretStr("s"), api_passphrase=SecretStr("p")
    ),
    "mexc": ExchangeCredentials(api_key=SecretStr("k"), api_secret=SecretStr("s")),
    "bitget": ExchangeCredentials(
        api_key=SecretStr("k"), api_secret=SecretStr("s"), api_passphrase=SecretStr("p")
    ),
}


@pytest.mark.parametrize(
    "exchange", ["binance", "bybit", "okx", "gateio", "kucoin", "mexc", "bitget"]
)
async def test_runtime_guard_blocks_non_get(exchange: str) -> None:
    adapter = exchange_registry.create(exchange, ExchangeCredentials(), AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]
        assert client.nexus_read_only_guard is True
        for method in ("POST", "DELETE", "PUT", "post"):
            with pytest.raises(ReadOnlyViolationError):
                await client.fetch("https://example.invalid/api", method)
    finally:
        await adapter.close()


async def test_runtime_guard_blocks_implicit_withdraw_endpoint() -> None:
    adapter = exchange_registry.create("binance", _CREDS["binance"], AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]
        withdraw = client.sapiPostCapitalWithdrawApply
        with pytest.raises(ReadOnlyViolationError):
            await withdraw({"coin": "USDT", "address": "x", "amount": "1"})
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    ("exchange", "method"),
    [
        ("mexc", "spotPrivatePostCapitalWithdraw"),
        ("bitget", "privateSpotPostV2SpotWalletWithdrawal"),
    ],
)
async def test_runtime_guard_blocks_new_exchange_implicit_withdraw(
    exchange: str, method: str
) -> None:
    adapter = exchange_registry.create(exchange, _CREDS[exchange], AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]
        client.markets = {}  # skip implicit market loading
        withdraw = getattr(client, method)
        with pytest.raises(ReadOnlyViolationError):
            await withdraw({"coin": "USDT", "address": "x", "amount": "1"})
    finally:
        await adapter.close()


@pytest.mark.parametrize("exchange", ["mexc", "bitget"])
async def test_new_exchange_ws_client_has_no_post_allowlist(exchange: str) -> None:
    adapter = exchange_registry.create(exchange, ExchangeCredentials(), AdapterOptions())
    try:
        assert adapter.ws_public_post_paths == frozenset()  # type: ignore[attr-defined]
    finally:
        await adapter.close()


async def test_runtime_guard_blocks_okx_transfer_via_request() -> None:
    adapter = exchange_registry.create("okx", _CREDS["okx"], AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]
        with pytest.raises(ReadOnlyViolationError):
            await client.request("asset/transfer", ["private"], "POST", {"ccy": "USDT"})
    finally:
        await adapter.close()


async def test_kucoin_ws_guard_allows_only_public_token_post() -> None:
    adapter = exchange_registry.create("kucoin", ExchangeCredentials(), AdapterOptions())
    calls: list[tuple[str, str]] = []

    class _Ws:
        has: ClassVar[dict[str, bool]] = {}

        async def fetch(self, url: str, method: str = "GET", *_: Any) -> Any:
            calls.append((url, method))
            return {}

    try:
        ws = _Ws()
        install_read_only_guard(
            ws,
            "kucoin",
            allowed_post_paths=adapter.ws_public_post_paths,  # type: ignore[attr-defined]
        )
        await ws.fetch("https://api.kucoin.com/api/v1/bullet-public", "POST")
        assert calls == [("https://api.kucoin.com/api/v1/bullet-public", "POST")]
        for url, method in (
            ("https://api.kucoin.com/api/v1/bullet-private", "POST"),
            ("https://api.kucoin.com/api/v1/withdrawals", "POST"),
            ("https://api.kucoin.com/api/v1/bullet-public/x", "POST"),
            ("https://api.kucoin.com/api/v1/bullet-public", "DELETE"),
        ):
            with pytest.raises(ReadOnlyViolationError):
                await ws.fetch(url, method)
        authenticated = _Ws()
        authenticated.apiKey = "k"  # type: ignore[attr-defined]
        with pytest.raises(ReadOnlyViolationError):
            install_read_only_guard(authenticated, "kucoin", allowed_post_paths=frozenset({"/x"}))
        # The REST client (which may hold credentials) never gets the allowlist.
        with pytest.raises(ReadOnlyViolationError):
            await adapter._rest.fetch(  # type: ignore[attr-defined]
                "https://api.kucoin.com/api/v1/bullet-public", "POST"
            )
    finally:
        await adapter.close()
