# HT1 - Hedged transfer arbitrage as a paper strategy

- id: HT1
- stage: M3 (analysis; runs alongside the keyed soak)
- owner: backend-lead (implementation); quant-analyst (semantics, report review)
- reviewers: tech-lead (diff), quant-analyst (formulas, P&L identity, report), architect (schema, new
  perp adapter interface), security (new public clients have no credentials; no order/transfer surface)
- complexity: high (new perp market-data adapters, position state machine, persistence, report section)
- depends_on: none blocking; deploy needs user OK (U4: image rebuild, migrator, scanner recreate)
- status: todo (spec ready 2026-10-25)
- spec: `docs/quant/hedged-transfer-spec.md` (normative; section numbers below refer to it)

## Goal
Add a second paper strategy that never holds unhedged coin inventory: buy spot on A, short a perp of equal
size on H, move the coin A->B (simulated), sell on B and close the short; USDT is rebalanced back virtually.
Report it in the GO report with MTM ~0 by construction and residual basis shown separately.

## Context docs
`docs/quant/hedged-transfer-spec.md`, `docs/decisions/0001-no-withdrawal-in-code.md`,
`docs/quant/b15-review-and-report-spec.md`, `docs/tasks/m2/B15-shadow-paper-portfolios.md`,
`src/nexus/simulation/portfolio.py`, `src/nexus/scanner/paper.py`, `src/nexus/engine/{estimator,depth,transfer}.py`,
`src/nexus/adapters/cex/ccxt_base.py`, `src/nexus/reports/go_*.py`, `config/nexus.toml`.

## Hard limits
- ADR 0001: no order, withdrawal, transfer, internal-transfer, address or leverage-setting calls anywhere.
  Perp clients are created WITHOUT credentials and get the existing read-only guard
  (`install_read_only_guard`); a test asserts no private/trading method is reachable.
- The definition (config hash) of the 4 running soak sets must not change; they must resume, not restart.
- Integration tests only on `nexus_test` (CI). Never touch the live `nexus` DB. Never read `.env`.

## Scope
1. **Perp market data (read-only, public)**: new narrow interface (e.g. `IPerpMarketData`: `load_perp_markets`,
   `fetch_perp_tickers`, `fetch_perp_order_book`, `fetch_funding`, `fetch_mark_klines`,
   `fetch_funding_history`, optional `fetch_leverage_tiers`) and ccxt adapters for binance (`binanceusdm`),
   okx (swap), kucoin (`kucoinfutures`); bybit/gateio optional, data only. Endpoints: spec 4.3. Domain types
   `PerpMarket`, `PerpTicker`, `FundingInfo` (Decimal; funding sign as ccxt). Own backoff/health; a perp
   outage disables HT entries only.
2. **Transfer metadata extension**: `NetworkInfo` gains `withdraw_min`, `deposit_min`, `deposit_confirmations`,
   `est_arrival_min`, `busy` (all optional); parsers per spec 4.3; `list_transfer_routes()` returning every
   VERIFIED shared network (the cheapest-only `select_transfer_route` stays unchanged for the scanner).
3. **Transfer duration model** (spec 7): pure function, committed block-time table, seeded lognormal draw +
   p_stuck tail, `tau_p50`/`tau_p95`.
4. **Hedged portfolio** (pure Decimal, no I/O, new module next to `portfolio.py`): USDT pools per venue,
   positions with the state machine of spec 1, pre-checks a-f with the skip reasons of spec 5, sizing and
   entry (spec 6), funding accrual, liquidation, exit, forced exit (spec 8), USDT rebalancing (spec 9),
   valuation with open basis MTM. P&L lines S, R, D, U, P, F, L, RB exactly as spec 3.
5. **Wiring**: `HedgedTrader` per HT set inside `PaperBook`, on the same alert hook and sweep hook; perp ticker
   refresh every 30 s; basis history ring buffer (6 h, 30 s samples) per (coin, B, H) in memory, rebuilt after a
   restart (warm-up skip `BASIS_WARMUP`); gap handling via klines/funding history after restarts.
6. **Config**: `[paper_hedged]` table in `config/nexus.toml` with the spec 13 defaults (code default
   `enabled = false`; toml `true`); validation (hedge venues subset of enabled exchanges, sets exist,
   leverage 1-5, thresholds > 0). All parameters in the HT run hash; HT ids `ht_<venue_set>`.
7. **Persistence**: additive Alembic migration (new tables only), e.g. `paper_hedged_positions` (one row per
   attempt incl. SKIPPED + reason, entry/exit prices, sizes, network, tau draw and p95, margin, P_liq, all P&L
   lines, status, timestamps) and `paper_hedged_snapshots` (pools, in-transit, margin, rebalance in flight,
   open basis MTM, equity; 15 min). USDT rebalances may reuse `paper_rebalances` with the HT portfolio id.
   Runs reuse `paper_portfolios`. Architect reviews schema and indexes.
8. **GO report**: HT section per spec 11 (same windows/tax/B5/B6 machinery), directional-MTM leak flag,
   basis-dominated flag, hedge-break flag, pessimistic shadow-exit P&L. JSON + Markdown.
9. **Docs**: `docs/guides/` short Russian note for the user (what HT is, how to read the new report section);
   config comments in English.

## Acceptance criteria
1. Hand-computed unit tests (no mocked math) for: P&L identity `total = S+R+D+U+P+F-L-RB` on >= 3 reference
   positions (price up, price down, basis change, dust); funding sign both ways and over multiple funding
   times; liquidation trigger and loss = margin; lot/contract rounding; min-withdraw/min-deposit skips.
2. Each pre-check (a-f) has a test producing exactly its skip reason; first failing check wins; stale-book,
   stale-funding, stale-metadata guards tested.
3. Directional MTM of a portfolio with only hedged positions is 0 within 1e-9 under a uniform price shift of
   all spot and perp prices (property test, several shifts).
4. Transfer model: deterministic for a given seed; `tau_p95 >= tau_p50`; unknown confirmations -> 60 min
   median; p_stuck draws produce `stuck_h`.
5. Golden test: with HT enabled and the committed `config/nexus.toml`, the definition hashes of `all`,
   `excl_conditional`, `excl_bybit`, `excl_gateio` equal the ones computed with HT disabled.
6. Adapter tests on recorded public fixtures (one per venue: markets, tickers, funding, book); no live network
   in unit tests; a test proves perp clients carry no API key and reject non-GET/private calls.
7. Restart: positions in transit resume from the DB; a gap with a kline high >= P_liq books a liquidation;
   missed funding times are booked from history.
8. Report: HT section renders on a fixture DB (integration, CI, `nexus_test`); sums reconcile with positions.
9. `make check` green; unit tests >= current count + new; branch coverage >= 89 % floor (not below 91.5 %
   baseline trend); ruff 0; mypy --strict 0.

## Deploy (after review; U4 user OK required)
Rebuild image -> migrator `alembic upgrade head` (exit 0) -> recreate scanner only. Verify logs: 4x
`paper_resumed`, 0x `paper_run_restarted`, 1x `paper_run_started` for `ht_excl_conditional`; first HT snapshot
within 15 min. Expected soak gap ~1-2 min.

## Out of scope
Real trading, withdrawals, internal transfers, leverage setting, Binance signed leverage brackets, variants
`sell_venue`/`buy_venue` running in the soak, DEX.
