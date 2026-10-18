"""Centralized exchange adapters.

Importing this package registers every built-in adapter in
:data:`nexus.adapters.registry.exchange_registry`. To add an exchange, create a module with
a registered :class:`~nexus.adapters.cex.ccxt_base.CcxtExchangeAdapter` subclass (or any
:class:`~nexus.interfaces.market_data.BaseExchangeAdapter`) and import it below.
"""

from nexus.adapters.cex import binance, bybit, gateio, kucoin, okx

__all__ = ["binance", "bybit", "gateio", "kucoin", "okx"]
