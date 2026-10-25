"""Read-only perpetual-swap market-data adapters (no credentials, ADR 0009).

Importing this package registers every built-in perp adapter in
:data:`nexus.adapters.perp.registry.perp_registry`.
"""

from nexus.adapters.perp import kucoin_futures, okx_swap

__all__ = ["kucoin_futures", "okx_swap"]
