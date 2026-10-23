"""Conditional venues: data is collected, but the user may not be able to trade there now."""

from __future__ import annotations

from collections.abc import Collection


def touches_conditional(buy: str, sell: str, conditional: Collection[str]) -> bool:
    """True if EITHER leg of the route is a conditional venue."""
    return buy in conditional or sell in conditional


def conditional_legs(buy: str, sell: str, conditional: Collection[str]) -> tuple[str, ...]:
    """The conditional venues among the legs of a route (buy first, no duplicates)."""
    legs = [venue for venue in (buy, sell) if venue in conditional]
    return tuple(dict.fromkeys(legs))
