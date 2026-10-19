"""Binance public capital config: transfer status without an API key (read-only, GET only)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

import httpx
import structlog

from nexus.adapters.cex.ccxt_base import to_decimal
from nexus.domain.errors import (
    ExchangeDataError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
    ReadOnlyViolationError,
)
from nexus.domain.models import ZERO, AssetTransferInfo, NetworkInfo
from nexus.interfaces.market_data import ITransferStatusSource

log = structlog.get_logger(__name__)

BINANCE_PUBLIC_CAPITAL_URL: Final = (
    "https://www.binance.com/bapi/capital/v1/public/capital/getNetworkCoinAll"
)
_HTTP_TOO_MANY_REQUESTS: Final = 429
_HTTP_IP_BANNED: Final = 418

CurrencyMapper = Callable[[str], str]
NetworkMapper = Callable[[str, str], str]
"""``(network_id, currency_code) -> unified network code`` (ccxt ``network_id_to_code``)."""


async def _get_only(request: httpx.Request) -> None:
    """httpx request hook: this client may only read."""
    if request.method != "GET":
        msg = f"[binance] blocked non-read-only {request.method} request"
        raise ReadOnlyViolationError(msg)


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


class BinancePublicTransferSource(ITransferStatusSource):
    """Per-network deposit/withdraw flags, withdrawal fees and contracts from Binance's
    public web endpoint (the same data as the signed ``capital/config/getall``).

    ``currency_code`` / ``network_code`` translate Binance ids into ccxt's unified codes so
    the result matches what the authenticated ccxt path would return.
    """

    exchange: Final = "binance"

    def __init__(
        self,
        *,
        timeout_s: float,
        currency_code: CurrencyMapper,
        network_code: NetworkMapper,
        client: httpx.AsyncClient | None = None,
        url: str = BINANCE_PUBLIC_CAPITAL_URL,
    ) -> None:
        """Create the source; ``client`` allows injecting a test transport."""
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._client.event_hooks["request"] = [*self._client.event_hooks["request"], _get_only]
        self._currency_code = currency_code
        self._network_code = network_code
        self._url = url

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def load_transfer_info(self) -> Mapping[str, AssetTransferInfo] | None:
        """Fetch and parse the public capital config."""
        try:
            response = await self._client.get(self._url)
        except httpx.TimeoutException:
            raise ExchangeUnavailableError(
                self.exchange, "public capital config: timed out"
            ) from None
        except httpx.HTTPError as exc:
            detail = f"public capital config: {type(exc).__name__}"
            raise ExchangeUnavailableError(self.exchange, detail) from None
        if response.status_code in (_HTTP_TOO_MANY_REQUESTS, _HTTP_IP_BANNED):
            raise ExchangeRateLimitError(
                self.exchange, f"public capital config: {response.status_code}"
            )
        if response.status_code != httpx.codes.OK:
            detail = f"public capital config: HTTP {response.status_code}"
            raise ExchangeUnavailableError(self.exchange, detail)
        try:
            body = response.json()
        except ValueError:
            raise ExchangeDataError(self.exchange, "public capital config: invalid JSON") from None
        return self.parse(body)

    def parse(self, body: Any) -> Mapping[str, AssetTransferInfo] | None:
        """Parse the endpoint payload (``Any``: untyped JSON)."""
        if not isinstance(body, Mapping) or body.get("success") is not True:
            raise ExchangeDataError(self.exchange, "public capital config: unsuccessful response")
        coins = body.get("data")
        if not isinstance(coins, list):
            raise ExchangeDataError(self.exchange, "public capital config: no data list")
        result: dict[str, AssetTransferInfo] = {}
        for coin in coins:
            if not isinstance(coin, Mapping) or not isinstance(coin.get("coin"), str):
                continue
            if coin.get("isLegalMoney") is True:
                continue
            code = self._currency_code(coin["coin"])
            result[code] = AssetTransferInfo(
                exchange=self.exchange,
                asset=code,
                networks=tuple(self._parse_networks(code, coin.get("networkList"))),
                withdraw_enabled=_flag(coin.get("withdrawAllEnable")),
                deposit_enabled=_flag(coin.get("depositAllEnable")),
            )
        return result or None

    def _parse_networks(self, code: str, raw: Any) -> list[NetworkInfo]:
        networks: list[NetworkInfo] = []
        for entry in raw if isinstance(raw, list) else ():
            if not isinstance(entry, Mapping) or not isinstance(entry.get("network"), str):
                continue
            fee = to_decimal(entry.get("withdrawFee"))
            contract = entry.get("contractAddress")
            networks.append(
                NetworkInfo(
                    network=self._network_code(entry["network"], code),
                    withdraw_enabled=_flag(entry.get("withdrawEnable")),
                    deposit_enabled=_flag(entry.get("depositEnable")),
                    withdraw_fee=fee if fee is not None and fee >= ZERO else None,
                    contract=contract.strip()
                    if isinstance(contract, str) and contract.strip()
                    else None,
                )
            )
        return networks
