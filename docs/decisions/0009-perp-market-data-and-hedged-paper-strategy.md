# 0009 — Public perp market-data port and the hedged paper strategy as a sibling of PaperBook

Date: 2026-10-25. Status: proposed (architect; accepted when tech-lead and security sign off the HT1
design review `docs/architecture/HT1-design-review.md`).
Superseded 2026-10-25 by [ADR 0010](0010-self-hosted-alert-tool.md): never accepted; HT1 removed after NO-GO (f603178).

## Context
The user chose a hedged-transfer strategy (HT): buy spot on A, short a perp on H, move the coin A->B in a
simulated transfer, sell on B and close the short. It runs as paper only (ADR 0001). It needs data the
system does not collect today: perpetual-futures markets, tickers, books, funding and mark klines. It also
needs a second paper strategy family. The existing paper code (`PaperBook`/`PaperTrader`,
`paper_portfolios`) is read by the daily digest and the GO report as "spot-inventory sets", and it drives
the scanner's per-set candidate selection. Four soak runs are live and must resume with unchanged
definition hashes.

## Decision drivers
- ADR 0001: no order, withdrawal, transfer, leverage or margin calls. Perp access is public and has no key.
- The running soak must not be affected: hashes, sweep timing, candidate selection, digest content.
- The deploy recreates the scanner only, so old worker code must stay correct against the new schema.
- Small, testable components (ADR 0003, target.md sections 3 and 5).

## Considered options
1. **New narrow port `IPerpMarketData` + own `perp_registry`. The HT strategy is a sibling `HedgedBook`
   with its own tables and its own polling loop. (chosen)**
2. Extend `BaseExchangeAdapter` / the spot ccxt clients with `defaultType: swap` calls. Rejected: it mixes
   spot and derivatives on one client (shared throttle, one health state, so a perp 429 would pause the
   spot venue). It also widens the spot interface for every venue.
3. HT traders inside `PaperBook.traders`, reusing `paper_portfolios`/`paper_rebalances`. Rejected: the
   digest (worker-alerts, not recreated) and the GO report would list HT as a B15 set. Per-set top-N and cap
   stats would gain a set. Both change the observable behaviour of the running soak.
4. Fetch perp data inside the sweep. Rejected: perp/DB latency would sit on the sweep path.

## Decision
- **Port** `interfaces/perp.py` `IPerpMarketData`: markets, all tickers, book (amounts in base units),
  funding (current + history), 1 m mark klines, optional leverage tiers. It has no account methods.
  Domain types live in `domain/perp.py`, all Decimal.
- **Adapters** `adapters/perp/` (binanceusdm, okx swap, kucoinfutures; others only by a later decision).
  Clients are built **without credentials**, with `install_read_only_guard`, `fetchCurrencies: False`, their
  own throttle and their own health/backoff state. They are built only for hedge venues of enabled HT sets.
- **Strategy** `simulation/hedged*.py` (pure Decimal, no I/O) + `scanner/hedged.py` `HedgedBook` /
  `HedgedTrader` + `scanner/perp_feed.py` `PerpFeed`. `HedgedBook` is a sibling of `PaperBook`. It sees the
  alert stream of a named parent spot set. It is never part of `PaperBook.sets` or `[paper] venue_sets`.
  The sweep calls only a sync in-memory hook. Alert handling and the perp loop run as scanner-owned
  background tasks.
- **Persistence**: one additive migration with its own `paper_hedged_*` tables (runs, positions, events,
  rebalances, snapshots, snapshot pools). Existing tables are untouched.
- **Config**: own settings group `PaperHedgedSettings` / TOML `[paper_hedged]`. Nothing HT-related enters
  `EstimatorConfig`, `PaperConfig` or the spot `strategy` map. The current four definition hashes are pinned
  in a golden test.

## Consequences
- Good: the spot soak is provably unchanged (pinned hashes, no shared tables, no sweep-path I/O). A perp
  outage disables only HT entries. The read-only and no-key properties are testable per client.
- Good: a later real executor (Stage 2) would sit behind a separate, reserved port (target.md section 7).
  This port stays market-data-only.
- Bad: ~6 new tables and a second report family. Some repository code (`ensure_run`) is duplicated for
  `paper_hedged_runs`; extract a shared helper only if a third family appears.
- Bad: HT is not in the daily digest until worker-alerts is redeployed with an HT digest block (out of
  HT1).
- A real HT would need withdrawals and internal transfers. That requires a new ADR superseding parts of
  0001, plus U4/U5.

## Confirmation
HT1 tests:
- Golden hashes (S0/S13).
- No-credential + guard tests per perp client.
- AST safety test extended with leverage/margin setters.
- Isolation tests: an HT failure does not change `PaperBook` outcomes, and the sweep never awaits HT I/O
  (fake feed that blocks forever).
- Migration test on `nexus_test`: upgrade adds only `paper_hedged_*`.
