"""Shared ccxt-based CEX adapter.

ccxt ships without type information, so every value crossing this boundary is converted
into typed, Decimal-based domain objects here. Only **read-only** endpoints are used:
markets, tickers, order books, currencies and trading fees. No method of this class (or
any subclass) may call order, withdrawal, transfer or address endpoints.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, TypeVar
from urllib.parse import urlsplit

import ccxt
import ccxt.async_support as ccxt_async
import ccxt.pro as ccxt_pro
import structlog

from nexus.adapters.registry import AdapterOptions
from nexus.config.groups import ExchangeCredentials
from nexus.domain.clock import Clock, SystemClock
from nexus.domain.errors import (
    ConfigurationError,
    DataValidationError,
    ExchangeAuthError,
    ExchangeDataError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
    ReadOnlyViolationError,
)
from nexus.domain.models import (
    MAX_SANE_TAKER_FEE,
    ZERO,
    AssetTransferInfo,
    MarketInfo,
    NetworkInfo,
    OrderBook,
    PriceLevel,
    Ticker,
)
from nexus.interfaces.market_data import (
    BaseExchangeAdapter,
    ITradingFeeSource,
    IWebSocketOrderbook,
)
from nexus.log import scrub

T = TypeVar("T")
log = structlog.get_logger(__name__)

_URL_RE = re.compile(r"https?://\S+|wss?://\S+")

_RETRYABLE: tuple[type[ExchangeError], ...] = (ExchangeUnavailableError,)
"""Rate-limit errors are NOT retried here: the scanner backs off per exchange instead
(repeated 429s escalate to IP bans on some venues)."""

_CONTRACT_KEYS: tuple[str, ...] = (
    "contractAddress",
    "contract_address",
    "ctAddr",
    "addr",
    "contract",
)
"""Keys under a ccxt network's raw ``info`` holding the token contract (KuCoin, Gate, OKX,
Bitget, MEXC, ...)."""


def install_read_only_guard(
    client: Any, exchange: str, *, allowed_post_paths: frozenset[str] = frozenset()
) -> None:
    """Block every non-GET HTTP request issued by an (authenticated) ccxt client.

    ccxt routes all REST traffic (unified methods, implicit API methods and ``request()``)
    through ``Exchange.fetch``. Order placement, withdrawals and transfers require POST /
    DELETE / PUT on every supported venue, so a GET-only client cannot move funds even if a
    future code change (or a mis-scoped API key) would otherwise allow it.

    ``allowed_post_paths`` lists exact URL paths of *public* POST endpoints (e.g. KuCoin's
    WebSocket token ``/api/v1/bullet-public``); it is used only for unauthenticated clients.
    """
    if allowed_post_paths and getattr(client, "apiKey", None):
        msg = f"[{exchange}] public POST allowlist is only allowed on unauthenticated clients"
        raise ReadOnlyViolationError(msg)
    original = client.fetch

    async def guarded_fetch(
        url: str, method: str = "GET", headers: Any = None, body: Any = None
    ) -> Any:
        verb = str(method).upper()
        if verb != "GET" and not (verb == "POST" and urlsplit(url).path in allowed_post_paths):
            msg = f"[{exchange}] blocked non-read-only {str(method).upper()} request"
            raise ReadOnlyViolationError(msg)
        return await original(url, method, headers, body)

    client.fetch = guarded_fetch
    client.nexus_read_only_guard = True


def to_decimal(value: Any) -> Decimal | None:
    """Convert a ccxt number (float/int/str/None) into a finite Decimal or ``None``.

    ``Any``: ccxt values are untyped JSON-derived scalars.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _to_flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


class CcxtExchangeAdapter(BaseExchangeAdapter, IWebSocketOrderbook, ITradingFeeSource):
    """Read-only spot market-data adapter backed by ccxt (REST) and ccxt.pro (WebSocket)."""

    name: ClassVar[str]
    ccxt_id: ClassVar[str]
    requires_passphrase: ClassVar[bool] = False
    ccxt_options: ClassVar[Mapping[str, Any]] = {"defaultType": "spot"}
    order_book_limits: ClassVar[tuple[int, ...] | None] = None
    """Allowed ``limit`` values for order book requests (``None`` = any up to the max)."""
    max_order_book_limit: ClassVar[int] = 200
    ws_order_book_limits: ClassVar[tuple[int, ...] | None] = None
    """Allowed WebSocket ``limit`` values when they differ from REST (``None`` = same)."""
    static_market_fees: ClassVar[bool] = False
    """True when ``market["taker"]`` is a library constant or a public list rate, not the
    account tier (alert candidates then look up the account rate per symbol)."""
    bulk_account_fees: ClassVar[bool] = True
    """False when ccxt's ``fetchTradingFees`` does not return account-tier rates."""
    ws_public_post_paths: ClassVar[frozenset[str]] = frozenset()
    """Public POST endpoints the (unauthenticated) WebSocket client needs, e.g. a WS token."""
    max_attempts: ClassVar[int] = 3
    retry_backoff_s: ClassVar[float] = 0.5

    def __init__(
        self,
        credentials: ExchangeCredentials,
        options: AdapterOptions,
        *,
        clock: Clock | None = None,
        rest_client: Any = None,
        ws_client: Any = None,
    ) -> None:
        """Create the adapter.

        ``rest_client`` / ``ws_client`` allow injecting ccxt-compatible test doubles.
        """
        if (
            self.requires_passphrase
            and credentials.is_configured
            and not (credentials.api_passphrase)
        ):
            msg = f"{self.name}: API passphrase is required together with key/secret"
            raise ConfigurationError(msg)
        self._credentials = credentials
        self._options = options
        self._clock: Clock = clock or SystemClock()
        self._rest: Any = rest_client or getattr(ccxt_async, self.ccxt_id)(self._client_config())
        if hasattr(self._rest, "fetch"):
            install_read_only_guard(self._rest, self.name)
        if getattr(self._rest, "precisionMode", ccxt.TICK_SIZE) != ccxt.TICK_SIZE:
            msg = f"{self.name}: unsupported ccxt precision mode (expected TICK_SIZE)"
            raise ConfigurationError(msg)
        self._ws: Any = ws_client
        self._closed = False
        self._log = log.bind(exchange=self.name)

    # ------------------------------------------------------------------ lifecycle

    def _client_config(self, *, authenticated: bool = True) -> dict[str, Any]:
        config: dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": self._options.timeout_ms,
            "options": dict(self.ccxt_options),
        }
        creds = self._credentials
        if authenticated and creds.api_key is not None and creds.api_secret is not None:
            config["apiKey"] = creds.api_key.get_secret_value()
            config["secret"] = creds.api_secret.get_secret_value()
            if creds.api_passphrase is not None:
                config["password"] = creds.api_passphrase.get_secret_value()
        return config

    async def close(self) -> None:
        """Close REST and WebSocket clients."""
        self._closed = True
        clients = [c for c in (self._rest, self._ws) if c is not None]
        results = await asyncio.gather(*(c.close() for c in clients), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self._log.warning("adapter_close_failed", error=repr(result))

    # ------------------------------------------------------------------ calls

    async def _call(self, operation: str, func: Callable[[], Awaitable[T]]) -> T:
        """Run a ccxt call with error translation, an overall timeout and bounded retries."""
        timeout_s = self._options.timeout_ms / 1000 * 2
        attempt = 1
        while True:
            cause: BaseException
            try:
                return await asyncio.wait_for(func(), timeout=timeout_s)
            except TimeoutError as exc:
                cause = exc
                error: ExchangeError = ExchangeUnavailableError(
                    self.name, f"{operation}: timed out"
                )
            except ccxt.BaseError as exc:
                cause = exc
                error = self._translate(operation, exc)
            except (IndexError, KeyError, TypeError) as exc:
                cause = exc
                error = ExchangeDataError(self.name, f"{operation}: malformed data ({exc!r:.120})")
            if not isinstance(error, _RETRYABLE) or attempt >= self.max_attempts:
                # Drop the ccxt cause: its message may contain signed URLs and raw bodies.
                error.add_note(f"cause: {type(cause).__name__}")
                raise error from None
            self._log.info("retrying", operation=operation, attempt=attempt, error=str(error))
            await asyncio.sleep(self.retry_backoff_s * 2 ** (attempt - 1))
            attempt += 1

    def _translate(self, operation: str, exc: Exception) -> ExchangeError:
        # ccxt messages embed request URLs (signed query strings) and raw bodies: strip them.
        message = scrub(_URL_RE.sub("<url>", str(exc)))[:160]
        detail = f"{operation}: {type(exc).__name__}: {message}"
        if isinstance(exc, ccxt.RateLimitExceeded | ccxt.DDoSProtection):
            return ExchangeRateLimitError(self.name, detail)
        if isinstance(exc, ccxt.AuthenticationError):
            return ExchangeAuthError(self.name, detail)
        if isinstance(exc, ccxt.NetworkError):
            return ExchangeUnavailableError(self.name, detail)
        return ExchangeDataError(self.name, detail)

    # ------------------------------------------------------------------ metadata

    async def load_markets(self) -> Sequence[MarketInfo]:
        """Load active and inactive spot markets with fees, lot steps and minimums."""
        raw: Mapping[str, Any] = await self._call(
            "load_markets", lambda: self._rest.load_markets(True)
        )
        account_fees = await self._load_account_taker_fees()
        markets: list[MarketInfo] = []
        for symbol, market in raw.items():
            if not market.get("spot") or market.get("base") is None:
                continue
            try:
                markets.append(self._parse_market(symbol, market, account_fees.get(symbol)))
            except DataValidationError as exc:
                self._log.warning("market_skipped", symbol=symbol, error=str(exc))
        return markets

    def _parse_market(
        self, symbol: str, market: Mapping[str, Any], account_fee: Decimal | None
    ) -> MarketInfo:
        if account_fee is not None:
            fee: Decimal | None = account_fee
            is_default = False
        else:
            fee = to_decimal(market.get("taker"))
            is_default = self.static_market_fees or fee is None or fee <= ZERO
        if fee is None or fee <= ZERO:
            fee = self._options.fallback_taker_fee
        limits = market.get("limits") or {}
        precision = market.get("precision") or {}
        return MarketInfo(
            exchange=self.name,
            symbol=symbol,
            base=str(market["base"]),
            quote=str(market["quote"]),
            taker_fee=fee,
            amount_step=to_decimal(precision.get("amount")),
            min_amount=to_decimal((limits.get("amount") or {}).get("min")),
            min_cost=to_decimal((limits.get("cost") or {}).get("min")),
            active=market.get("active") is not False,
            taker_fee_is_default=is_default,
        )

    async def _load_account_taker_fees(self) -> dict[str, Decimal]:
        """Best-effort account-tier taker fees (requires read-only credentials)."""
        if not (
            self.bulk_account_fees
            and self._credentials.is_configured
            and self._rest.has.get("fetchTradingFees")
        ):
            return {}
        try:
            raw: Mapping[str, Any] = await self._call(
                "fetch_trading_fees", lambda: self._rest.fetch_trading_fees()
            )
        except ExchangeError as exc:
            self._log.warning("account_fees_unavailable", error=str(exc))
            return {}
        fees: dict[str, Decimal] = {}
        for symbol, entry in raw.items():
            taker = to_decimal((entry or {}).get("taker"))
            if taker is not None and taker > ZERO:
                fees[symbol] = taker
        return fees

    async def fetch_taker_fee(self, symbol: str) -> Decimal | None:
        """Account-tier taker fee of one symbol (``fetchTradingFee``, read-only credentials).

        The scanner calls it only for markets still priced with a default fee (e.g. OKX, whose
        ccxt markets carry a library constant and which has no bulk ``fetchTradingFees``).
        """
        if not self._credentials.is_configured or not self._rest.has.get("fetchTradingFee"):
            return None
        raw: Mapping[str, Any] = await self._call(
            "fetch_trading_fee", lambda: self._rest.fetch_trading_fee(symbol)
        )
        raw = raw or {}
        if raw.get("symbol") not in (None, symbol):
            self._log.warning("trading_fee_symbol_mismatch", symbol=symbol)
            return None
        taker = self._taker_from_fee_entry(symbol, raw)
        if taker is None or not ZERO < taker < MAX_SANE_TAKER_FEE:
            self._log.warning("trading_fee_implausible", symbol=symbol, taker=str(taker))
            return None
        return taker

    def _taker_from_fee_entry(self, symbol: str, raw: Mapping[str, Any]) -> Decimal | None:
        """Taker fee (fraction) from a unified ccxt trading-fee entry; overridable."""
        return to_decimal(raw.get("taker"))

    async def load_transfer_info(self) -> Mapping[str, AssetTransferInfo] | None:
        """Per-asset network deposit/withdrawal status and withdrawal fees (read-only)."""
        if not self._rest.has.get("fetchCurrencies"):
            return None
        try:
            raw: Mapping[str, Any] = await self._call(
                "fetch_currencies", lambda: self._rest.fetch_currencies()
            )
        except ExchangeAuthError as exc:
            self._log.warning("transfer_info_requires_credentials", error=str(exc))
            return None
        if not raw:
            return None  # exchange exposes currency data only to authenticated clients
        fee_overrides = await self._load_withdraw_fee_overrides(raw)
        result: dict[str, AssetTransferInfo] = {}
        for code, currency in raw.items():
            networks = self._parse_networks(str(code), currency or {}, fee_overrides)
            result[str(code)] = AssetTransferInfo(
                exchange=self.name,
                asset=str(code),
                networks=networks,
                withdraw_enabled=_to_flag((currency or {}).get("withdraw")),
                deposit_enabled=_to_flag((currency or {}).get("deposit")),
            )
        return result

    def _parse_networks(
        self,
        code: str,
        currency: Mapping[str, Any],
        fee_overrides: Mapping[tuple[str, str], Decimal],
    ) -> tuple[NetworkInfo, ...]:
        parsed: list[NetworkInfo] = []
        currency_withdraw = _to_flag(currency.get("withdraw"))
        currency_deposit = _to_flag(currency.get("deposit"))
        for network_code, network in (currency.get("networks") or {}).items():
            if not isinstance(network, Mapping):
                continue
            withdraw = _to_flag(network.get("withdraw"))
            deposit = _to_flag(network.get("deposit"))
            # A currency-level "disabled" overrides unknown network-level flags.
            if withdraw is None and currency_withdraw is False:
                withdraw = False
            if deposit is None and currency_deposit is False:
                deposit = False
            fee = self._network_withdraw_fee(network)
            if fee is None and not self._has_unmodelled_withdraw_fee(network):
                fee = fee_overrides.get((code, str(network_code)))
            parsed.append(
                NetworkInfo(
                    network=str(network_code),
                    withdraw_enabled=withdraw,
                    deposit_enabled=deposit,
                    withdraw_fee=fee if fee is None or fee >= ZERO else None,
                    contract=self._extract_contract(network),
                )
            )
        return tuple(parsed)

    def _network_withdraw_fee(self, network: Mapping[str, Any]) -> Decimal | None:
        """Flat withdrawal fee (in the asset) of a ccxt network, ``None`` when not modelled."""
        if self._has_unmodelled_withdraw_fee(network):
            return None
        return to_decimal(network.get("fee"))

    def _has_unmodelled_withdraw_fee(self, network: Mapping[str, Any]) -> bool:
        """True when the venue charges an extra fee the flat-fee model cannot express.

        Such networks get an unknown fee, so a route over them is never ``VERIFIED``.
        """
        return False

    def _extract_contract(self, network: Mapping[str, Any]) -> str | None:
        """Token contract address from the raw network ``info`` (``None`` if not published)."""
        info = network.get("info")
        if not isinstance(info, Mapping):
            return None
        for key in _CONTRACT_KEYS:
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    async def _load_withdraw_fee_overrides(
        self, currencies: Mapping[str, Any]
    ) -> dict[tuple[str, str], Decimal]:
        """Fill missing network fees via ``fetchDepositWithdrawFees`` when available."""
        missing = any(
            to_decimal((n or {}).get("fee")) is None
            for c in currencies.values()
            for n in ((c or {}).get("networks") or {}).values()
        )
        if not (
            missing
            and self._credentials.is_configured
            and self._rest.has.get("fetchDepositWithdrawFees")
        ):
            return {}
        try:
            raw: Mapping[str, Any] = await self._call(
                "fetch_deposit_withdraw_fees", lambda: self._rest.fetch_deposit_withdraw_fees()
            )
        except ExchangeError as exc:
            self._log.warning("withdraw_fees_unavailable", error=str(exc))
            return {}
        overrides: dict[tuple[str, str], Decimal] = {}
        for code, entry in raw.items():
            for network_code, network in ((entry or {}).get("networks") or {}).items():
                fee = to_decimal(((network or {}).get("withdraw") or {}).get("fee"))
                if fee is not None and fee >= ZERO:
                    overrides[(str(code), str(network_code))] = fee
        return overrides

    # ------------------------------------------------------------------ market data

    async def fetch_tickers(self, symbols: Sequence[str]) -> Mapping[str, Ticker]:
        """Fetch all spot tickers in one request and keep the requested ``symbols``."""
        raw: Mapping[str, Any] = await self._call(
            "fetch_tickers", lambda: self._rest.fetch_tickers()
        )
        wanted = set(symbols)
        tickers: dict[str, Ticker] = {}
        for symbol, entry in raw.items():
            if (wanted and symbol not in wanted) or not isinstance(entry, Mapping):
                continue
            bid = to_decimal(entry.get("bid"))
            ask = to_decimal(entry.get("ask"))
            timestamp = entry.get("timestamp")
            tickers[symbol] = Ticker(
                exchange=self.name,
                symbol=symbol,
                bid=bid if bid is not None and bid > ZERO else None,
                ask=ask if ask is not None and ask > ZERO else None,
                quote_volume_24h=to_decimal(entry.get("quoteVolume")),
                timestamp_ms=int(timestamp) if isinstance(timestamp, int | float) else None,
            )
        return tickers

    def order_book_limit(self, depth: int, *, websocket: bool = False) -> int:
        """Translate a desired depth into a limit the exchange accepts."""
        allowed = self.order_book_limits
        if websocket and self.ws_order_book_limits is not None:
            allowed = self.ws_order_book_limits
        if allowed is None:
            return max(1, min(depth, self.max_order_book_limit))
        candidates = [limit for limit in allowed if limit >= depth]
        return min(candidates) if candidates else max(allowed)

    async def fetch_order_book(self, symbol: str, depth: int) -> OrderBook:
        """Fetch a REST order book snapshot."""
        limit = self.order_book_limit(depth)
        raw: Mapping[str, Any] = await self._call(
            f"fetch_order_book {symbol}", lambda: self._rest.fetch_order_book(symbol, limit)
        )
        return self._parse_order_book(symbol, raw, depth)

    async def watch_order_book(self, symbol: str, depth: int) -> OrderBook:
        """Await the next WebSocket order book update (public stream, no credentials)."""
        if self._closed:
            msg = f"{self.name}: adapter is closed"
            raise ExchangeUnavailableError(self.name, msg)
        if self._ws is None:
            self._ws = getattr(ccxt_pro, self.ccxt_id)(self._client_config(authenticated=False))
            if hasattr(self._ws, "fetch"):
                # Unauthenticated today; the guard keeps it read-only if that ever changes.
                install_read_only_guard(
                    self._ws, self.name, allowed_post_paths=self.ws_public_post_paths
                )
        limit = self.order_book_limit(depth, websocket=True)
        raw: Mapping[str, Any] = await self._call(
            f"watch_order_book {symbol}", lambda: self._ws.watch_order_book(symbol, limit)
        )
        return self._parse_order_book(symbol, raw, depth)

    async def unwatch_order_book(self, symbol: str) -> None:
        """Unsubscribe from a WebSocket order book stream (best effort)."""
        if self._ws is None or self._closed or not self._ws.has.get("unWatchOrderBook"):
            return
        try:
            await asyncio.wait_for(
                self._ws.un_watch_order_book(symbol), self._options.timeout_ms / 1000
            )
        except (ccxt.BaseError, TimeoutError) as exc:
            self._log.info("unwatch_failed", symbol=symbol, error=type(exc).__name__)

    def _parse_order_book(self, symbol: str, raw: Mapping[str, Any], depth: int) -> OrderBook:
        received = self._clock.now_ms()
        timestamp = raw.get("timestamp")
        try:
            return OrderBook(
                exchange=self.name,
                symbol=symbol,
                bids=self._parse_levels(raw.get("bids"), depth),
                asks=self._parse_levels(raw.get("asks"), depth),
                timestamp_ms=int(timestamp) if isinstance(timestamp, int | float) else received,
                received_at_ms=received,
            )
        except DataValidationError as exc:
            raise ExchangeDataError(self.name, str(exc)) from exc

    @staticmethod
    def _parse_levels(raw_levels: Any, depth: int) -> tuple[PriceLevel, ...]:
        levels: list[PriceLevel] = []
        for entry in raw_levels or ():
            if len(levels) >= depth:
                break
            if not isinstance(entry, list | tuple) or len(entry) < 2:
                continue
            price = to_decimal(entry[0])
            amount = to_decimal(entry[1])
            if price is None or amount is None or price <= ZERO or amount <= ZERO:
                continue
            levels.append(PriceLevel(price, amount))
        return tuple(levels)
