# 0004 — Source plug-in contract: core venue list, composition-time capabilities, DEX seam on paper

Date: 2026-10-23. Status: accepted (architect, delegated by the user).
Revised 2026-10-23: registry tiers replaced by a config list; string capability flags replaced
by typed optional ports; DEX seam documented only (U2 option A).

## Context
Adapters are added through `adapters/registry.py` (open/closed holds, B6). Optional capabilities
(WS books, account fees) are discovered with `isinstance` on Protocols inside the scanner
(`scanner/service.py`, `scanner/streams.py`; I2). ADR 0002 makes bitget/mexc extension-only, yet
the default `EXCHANGES_ENABLED` (`config/groups.py`) still includes them. The user chose DEX option A:
seam only, no DEX code. `interfaces/dex.py` is an unused stub (TD-09).

## Decision drivers
- GO/NO-GO numbers must cover exactly the five core CEX (ADR 0002).
- Which venue is "core" is a user/KYC policy that changes over time, not an adapter property.
- Type safety (mypy --strict) and no venue names in scanner logic.
- YAGNI: no DEX or generic-venue code before GO.

## Considered options
1. **Core list in config + typed optional ports resolved in the composition root. (chosen)**
2. `tier` attribute on registry entries + string capability flags (previous draft) —
   rejected: puts policy into code (a KYC change would need a code change), flags need casts
   after the check, so mypy no longer guards the call.
3. Keep `isinstance` checks in the scanner — rejected: `runtime_checkable` Protocols check only
   method names, run on the hot path and spread discovery across modules.
4. Generic "venue" abstraction for CEX + DEX now — rejected: speculative (U2 = A).

## Decision
1. **Core venues** = one config constant `CORE_EXCHANGES` (binance, bybit, gateio, kucoin, okx).
   Default `EXCHANGES_ENABLED` = `CORE_EXCHANGES` (step B1, first on the critical path).
   Extension venues are enabled by config only. GO/NO-GO analytics filter rows by
   `CORE_EXCHANGES`; no schema change (rows already carry the exchange name).
2. **Capabilities** are resolved once in `container.py`: each enabled venue becomes a small
   frozen `VenueHandle` with typed fields — `books` (required), `ws_books`, `account_fees`,
   `transfer_status`, `server_time` (each `Port | None`). The scanner checks `is not None`,
   never `isinstance`, never venue names.
3. **DEX seam on paper only.** This ADR documents `LegQuote` (priced leg incl. fees and
   gas/network cost, with timestamp) and the asset-identity registry prerequisite.
   `interfaces/dex.py` stays as a placeholder. Nothing is built (steps E1-E3 unscheduled).

## Consequences
- Good: adding a CEX = adapter + registry entry + its optional ports; no scanner edit.
- Good: after Argentine DNI/KYC, enabling bitget/mexc for analysis = config change.
- Good: mypy checks every optional-capability call.
- Bad: one more small type (`VenueHandle`) and container code.
- DEX: not planned. If it is ever opened, a new ADR fixes the `LegQuote` shape against real
  aggregator data.
- E1 (asset-identity registry) may be pulled forward without DEX if network/contract mismatches in CEX transfer routing (evidence-triggered, not scheduled).

## Confirmation
Steps B1 and C9: default-settings test lists exactly the five core venues; no `isinstance` on
ports and no venue-name branches in `scanner/` (grep check in review).
