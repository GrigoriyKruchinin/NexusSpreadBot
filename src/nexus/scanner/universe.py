"""Tradable universe: markets and transfer metadata shared by at least two exchanges."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal

from nexus.domain.models import AssetTransferInfo, MarketInfo


@dataclass(frozen=True, slots=True)
class UniverseFilter:
    """Symbol selection rules."""

    quote_assets: frozenset[str]
    whitelist: frozenset[str] = frozenset()
    blacklist: frozenset[str] = frozenset()

    def accepts(self, market: MarketInfo) -> bool:
        """True if ``market`` may be scanned."""
        if market.quote not in self.quote_assets or market.symbol in self.blacklist:
            return False
        return not self.whitelist or market.symbol in self.whitelist


@dataclass(frozen=True, slots=True)
class MarketUniverse:
    """Immutable snapshot of scannable markets per exchange."""

    markets: Mapping[str, Mapping[str, MarketInfo]]
    """exchange -> symbol -> market (only symbols listed on >= 2 exchanges)."""
    transfers: Mapping[str, Mapping[str, AssetTransferInfo] | None] = field(default_factory=dict)
    """exchange -> asset -> transfer info (``None`` when the exchange exposes no data)."""
    transfers_loaded_at_ms: Mapping[str, int] = field(default_factory=dict)
    """exchange -> epoch ms of the last successful transfer metadata load (staleness guard)."""

    @classmethod
    def build(
        cls,
        markets_by_exchange: Mapping[str, Iterable[MarketInfo]],
        transfers: Mapping[str, Mapping[str, AssetTransferInfo] | None],
        rules: UniverseFilter,
        transfers_loaded_at_ms: Mapping[str, int] | None = None,
    ) -> MarketUniverse:
        """Keep active, accepted markets whose symbol trades on at least two exchanges."""
        accepted: dict[str, dict[str, MarketInfo]] = {}
        venues: dict[str, int] = defaultdict(int)
        for exchange, markets in markets_by_exchange.items():
            selected = {m.symbol: m for m in markets if m.active and rules.accepts(m)}
            accepted[exchange] = selected
            for symbol in selected:
                venues[symbol] += 1
        common = {symbol for symbol, count in venues.items() if count >= 2}
        return cls(
            markets={
                ex: {s: m for s, m in by_symbol.items() if s in common}
                for ex, by_symbol in accepted.items()
            },
            transfers=dict(transfers),
            transfers_loaded_at_ms=dict(transfers_loaded_at_ms or {}),
        )

    def with_taker_fees(self, fees: Mapping[tuple[str, str], Decimal]) -> MarketUniverse:
        """Copy with account fees applied: ``(exchange, symbol) -> taker fee`` (fraction)."""
        if not fees:
            return self
        markets = {
            exchange: {
                symbol: replace(market, taker_fee=fees[key], taker_fee_is_default=False)
                if (key := (exchange, symbol)) in fees
                else market
                for symbol, market in by_symbol.items()
            }
            for exchange, by_symbol in self.markets.items()
        }
        return replace(self, markets=markets)

    @property
    def common_symbols(self) -> frozenset[str]:
        """Symbols tradable on at least two exchanges."""
        return frozenset(s for by_symbol in self.markets.values() for s in by_symbol)

    def symbols_for(self, exchange: str) -> frozenset[str]:
        """Scannable symbols on ``exchange``."""
        return frozenset(self.markets.get(exchange, {}))

    def market(self, exchange: str, symbol: str) -> MarketInfo | None:
        """Market metadata, if scannable."""
        return self.markets.get(exchange, {}).get(symbol)

    def transfer_coverage_pct(self, exchange: str) -> int | None:
        """Share (floor %) of scanned base assets on ``exchange`` with a known transfer status.

        Known = the exchange reports a deposit and a withdrawal flag for at least one network
        of the asset, or disables the asset outright. ``None`` when nothing is scanned.
        """
        assets = {market.base for market in self.markets.get(exchange, {}).values()}
        if not assets:
            return None
        known = sum(1 for asset in assets if _status_known(self.transfer_info(exchange, asset)))
        return known * 100 // len(assets)

    def transfer_info(self, exchange: str, asset: str) -> AssetTransferInfo | None:
        """Transfer metadata of ``asset`` on ``exchange`` (``None`` if unknown)."""
        by_asset = self.transfers.get(exchange)
        return by_asset.get(asset) if by_asset is not None else None


def _status_known(info: AssetTransferInfo | None) -> bool:
    if info is None:
        return False
    if info.withdraw_enabled is False or info.deposit_enabled is False:
        return True
    return any(
        n.withdraw_enabled is not None and n.deposit_enabled is not None for n in info.networks
    )
