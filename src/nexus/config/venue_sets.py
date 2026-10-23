"""Paper venue sets (``PAPER_VENUE_SETS``): which venues each shadow portfolio may trade.

Syntax: entries separated by ``;``. An entry is ``name`` (only the built-ins ``all`` and
``excl_conditional``) or ``name=spec`` where ``spec`` is either a list of venues to include
(``core=binance,okx,kucoin``) or a list of venues to exclude from ``EXCHANGES_ENABLED``
(``excl_gateio=-gateio`` or ``-gateio,-bybit``). Signs cannot be mixed in one set.
Everything is lowercased; errors always name the set (and the venue). The set ``all`` is
mandatory and always means "every enabled venue".
"""

from __future__ import annotations

import re
from collections.abc import Collection

ALL_SET = "all"
EXCL_CONDITIONAL_SET = "excl_conditional"
DEFAULT_VENUE_SETS = f"{ALL_SET};{EXCL_CONDITIONAL_SET}"
MIN_SET_VENUES = 2

_SET_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_VENUE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _parse_entries(spec: str) -> list[tuple[str, str | None]]:
    """Syntax-only parse: ``[(name, spec-or-None)]`` in order, names validated and unique."""
    entries: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for raw in spec.split(";"):
        entry = raw.strip().lower()
        if not entry:
            msg = "PAPER_VENUE_SETS contains an empty entry"
            raise ValueError(msg)
        name, sep, body = entry.partition("=")
        name = name.strip()
        if not _SET_NAME_RE.fullmatch(name):
            msg = f"PAPER_VENUE_SETS: invalid set name {name!r} (use a-z, 0-9, _; max 32)"
            raise ValueError(msg)
        if name in seen:
            msg = f"PAPER_VENUE_SETS: duplicate set name {name!r}"
            raise ValueError(msg)
        seen.add(name)
        entries.append((name, body.strip() if sep else None))
    return entries


def validate_venue_sets_syntax(spec: str) -> str:
    """Normalize ``spec`` (lowercase, trimmed) after a syntax check; raises ``ValueError``."""
    entries = _parse_entries(spec)
    return ";".join(n if b is None else f"{n}={b}" for n, b in entries)


def _tokens(name: str, body: str) -> tuple[list[str], bool]:
    """``(venues, is_exclusion)`` of a ``name=spec`` entry."""
    tokens = [t.strip() for t in body.split(",") if t.strip()]
    if not tokens:
        msg = f"PAPER_VENUE_SETS: set {name!r} has no venues"
        raise ValueError(msg)
    negative = [t.startswith("-") for t in tokens]
    if any(negative) and not all(negative):
        msg = f"PAPER_VENUE_SETS: set {name!r} mixes included and excluded (-) venues"
        raise ValueError(msg)
    venues = [t.removeprefix("-").strip() for t in tokens]
    for venue in venues:
        if not _VENUE_RE.fullmatch(venue):
            msg = f"PAPER_VENUE_SETS: set {name!r} has an invalid venue name {venue!r}"
            raise ValueError(msg)
    if len(set(venues)) != len(venues):
        dup = next(v for v in venues if venues.count(v) > 1)
        msg = f"PAPER_VENUE_SETS: set {name!r} lists venue {dup!r} twice"
        raise ValueError(msg)
    return venues, all(negative)


def resolve_venue_sets(
    spec: str,
    enabled: Collection[str],
    conditional: Collection[str],
    *,
    strict: bool,
) -> dict[str, tuple[str, ...]]:
    """Resolve ``spec`` against the enabled venues (venues keep ``enabled`` order).

    ``strict=False`` (the variable was never set): the built-in ``excl_conditional`` is
    silently dropped when it would be degenerate (< 2 venues or identical to ``all``) so a
    narrowed ``EXCHANGES_ENABLED`` does not crash a default config. An explicit spec is
    always strict: any problem raises ``ValueError`` naming the set and venue (fail closed).
    """
    entries = _parse_entries(spec)
    names = [n for n, _ in entries]
    if ALL_SET not in names:
        msg = f"PAPER_VENUE_SETS must contain the set {ALL_SET!r}"
        raise ValueError(msg)
    enabled_order = tuple(enabled)
    resolved: dict[str, tuple[str, ...]] = {}
    for name, body in entries:
        if name == ALL_SET:
            if body is not None:
                msg = f"PAPER_VENUE_SETS: the set {ALL_SET!r} cannot be redefined"
                raise ValueError(msg)
            resolved[name] = enabled_order
            continue
        if body is None:
            if name != EXCL_CONDITIONAL_SET:
                msg = f"PAPER_VENUE_SETS: set {name!r} needs '=<venues>'"
                raise ValueError(msg)
            members = tuple(v for v in enabled_order if v not in set(conditional))
            if not strict and (len(members) < MIN_SET_VENUES or members == resolved[ALL_SET]):
                continue
        else:
            venues, exclusion = _tokens(name, body)
            unknown = [v for v in venues if v not in enabled_order]
            if unknown:
                msg = (
                    f"PAPER_VENUE_SETS: set {name!r} names venue {unknown[0]!r} "
                    "which is not in EXCHANGES_ENABLED"
                )
                raise ValueError(msg)
            chosen = set(venues)
            members = tuple(
                v for v in enabled_order if (v not in chosen if exclusion else v in chosen)
            )
        if len(members) < MIN_SET_VENUES:
            msg = f"PAPER_VENUE_SETS: set {name!r} must have at least {MIN_SET_VENUES} venues"
            raise ValueError(msg)
        if members == resolved[ALL_SET]:
            msg = f"PAPER_VENUE_SETS: set {name!r} is identical to {ALL_SET!r}"
            raise ValueError(msg)
        resolved[name] = members
    return resolved
