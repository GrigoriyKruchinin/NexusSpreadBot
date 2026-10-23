# 0004 — Source plug-in contract: registry tiers, declared capabilities, reserved DEX seam

Date: 2026-10-23. Status: proposed (architect, Phase 5). DEX build is decided at U2, not here.

**Context.** Adapters are added via `exchange_registry` (OCP holds, B6), but optional
capabilities (WS books, account fees) are discovered with `isinstance` (I2). ADR 0002 makes
bitget/mexc extension-only, yet default `EXCHANGES_ENABLED` still includes them
(`config/groups.py`, `.env.example`). The user mentions DEX/cross-chain; `interfaces/dex.py` is an
unused stub (TD-09).

**Decision.**
1. Registry entries carry `tier = core | extension`. Defaults enable only core venues
   (binance, bybit, gateio, kucoin, okx). Analytics/soak/GO use core only.
2. Adapters declare `capabilities` (`rest_books`, `ws_books`, `account_fees`,
   `transfer_status`, `server_time`); the scanner branches on capabilities, never on names.
3. Reserved seam for non-orderbook venues: `LegQuote` (priced leg for a target size incl. fees
   and gas/network cost, with timestamp). Keep `interfaces/dex.py` as its placeholder port.
   An asset-identity registry is a prerequisite for any DEX/cross-chain leg.
4. Nothing DEX-specific is built until U2 puts it in scope.

**Alternatives.** Delete the DEX stub (rejected: cheap to keep, documents the seam). Build a
generic "venue" abstraction now (rejected: speculative, U2 undecided).

**Consequences.** Adding a CEX = adapter + registry entry + capabilities. Adding a DEX = provider
behind the port + asset registry, without core edits. Migration steps B1, C11, E1–E3.
