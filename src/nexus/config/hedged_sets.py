"""Hedged-transfer (HT1) set syntax: ``PAPER_HEDGED_SETS`` and ``PAPER_HEDGED_PERP_TAKER_FEE_PCT``.

``sets``: ``id=venue,venue;id2=venue,...`` (the venues are the perp HEDGE venues of the set; the
spot venues are shared, ``PAPER_HEDGED_SPOT_VENUES``). Errors always name the set / venue and never
echo anything else.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

HT_GO_SET = "ht_excl_conditional"
HT_CONTEXT_SET = "ht_excl_conditional_bn"
DEFAULT_HEDGED_SETS = f"{HT_GO_SET}=okx,kucoin;{HT_CONTEXT_SET}=binance,okx,kucoin"
HEDGE_CAPABLE = frozenset({"binance", "okx", "kucoin"})
"""Venues that have a perp market-data adapter (HT1 scope: no bybit/gateio)."""

_ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def parse_hedged_sets(spec: str) -> dict[str, tuple[str, ...]]:
    """``{set id: hedge venues}`` in order; raises ``ValueError`` on any syntax problem."""
    sets: dict[str, tuple[str, ...]] = {}
    for raw in spec.split(";"):
        entry = raw.strip().lower()
        set_id, sep, body = entry.partition("=")
        set_id = set_id.strip()
        if not sep or not _ID_RE.fullmatch(set_id):
            msg = f"PAPER_HEDGED_SETS: invalid entry for set {set_id[:32]!r} (use id=venue,venue)"
            raise ValueError(msg)
        if set_id in sets:
            msg = f"PAPER_HEDGED_SETS: duplicate set id {set_id!r}"
            raise ValueError(msg)
        venues = tuple(v.strip() for v in body.split(",") if v.strip())
        if not venues or len(set(venues)) != len(venues):
            msg = f"PAPER_HEDGED_SETS: set {set_id!r} needs distinct hedge venues"
            raise ValueError(msg)
        unknown = sorted(set(venues) - HEDGE_CAPABLE)
        if unknown:
            msg = (
                f"PAPER_HEDGED_SETS: set {set_id!r} has venue(s) without a perp adapter: {unknown}"
            )
            raise ValueError(msg)
        sets[set_id] = venues
    return sets


def normalize_hedged_sets(spec: str) -> str:
    """Lowercased, trimmed ``spec`` after validation."""
    return ";".join(f"{k}={','.join(v)}" for k, v in parse_hedged_sets(spec).items())


def parse_perp_fees(spec: str) -> dict[str, Decimal]:
    """``venue=pct`` pairs to fractions (0.05 -> 0.0005); raises ``ValueError``."""
    fees: dict[str, Decimal] = {}
    for raw in spec.split(","):
        venue, sep, pct = raw.strip().lower().partition("=")
        try:
            value = Decimal(pct.strip())
        except InvalidOperation:
            value = Decimal(-1)
        if not sep or venue.strip() not in HEDGE_CAPABLE or not 0 <= value < 5:
            msg = "PAPER_HEDGED_PERP_TAKER_FEE_PCT: expected venue=pct pairs (0 <= pct < 5)"
            raise ValueError(msg)
        fees[venue.strip()] = value / 100
    return fees
