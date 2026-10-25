# HT1 - Hedged transfer arbitrage as a paper strategy

- id: HT1
- stage: M3 (analysis; runs alongside the keyed soak)
- owner: backend-lead (implementation); quant-analyst (semantics, report review)
- reviewers: tech-lead (diff), quant-analyst (formulas, P&L identity, report), architect (schema, new
  perp adapter interface), security (new public clients have no credentials; no order/transfer surface)
- complexity: high (new perp market-data adapters, position state machine, persistence, report section)
- depends_on: none blocking; deploy needs user OK (U4: image rebuild, migrator, scanner recreate)
- status: todo (spec ready 2026-10-25; architect review ACCEPT with changes 2026-10-25, steps S0-S15 below)
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

## Architect review 2026-10-25: ACCEPT with changes
Review: `docs/architecture/HT1-design-review.md`. ADR draft: `docs/decisions/0009-perp-market-data-and-hedged-paper-strategy.md`.
Where these amendments conflict with Scope above, they override it:
- **Scope 7 is replaced:** HT has its own `paper_hedged_*` tables (runs, positions, events, rebalances,
  snapshots, snapshot_pools). Do **not** reuse `paper_portfolios` / `paper_rebalances`. Reason: the digest
  and the GO report list every `paper_portfolios` row as a spot set (review F1).
- **Scope 5 is changed:** `HedgedBook` is a sibling of `PaperBook`, not a trader inside it, and never in
  `PaperBook.sets` / `[paper] venue_sets`. The sweep calls only a sync `observe_spot(tickers)`. Alert
  handling is a spawned task. Perp polling runs in its own `PerpFeed` loop.
- **Scope 1 is changed:** adapters for okx, kucoin and binance only. No bybit/gateio perp clients in HT1.
- **Hedge venues (legal, 2026-10-25):** set `ht_excl_conditional` hedges on okx + kucoin (GO hypothesis).
  Set `ht_excl_conditional_bn` hedges on binance + okx + kucoin (context only; GO-eligible only after
  G1.1a + G5.3). Both run from day 1.
- **Spec amendment needed from quant before S11:** C1 (sections 2/12/13/14 and the Bonferroni note), C5
  (skip code `PERP_HISTORY_MISSING`), C6 (relative-basis estimator), C8 (final booking of an unpriceable
  hedge).

## Override 2026-10-25 (user): HT is the only strategy
The 4 running spot sets and their data are retired at HT deploy (fresh DB). Therefore: no golden-hash pins
(S0 pins dropped), AC5 and C9 are void, and nothing exists only to keep the old sets byte-identical. Spot
paper code stays (analytical tool). Kept: C2 (own `paper_hedged_*` tables), C3/C4 (HedgedBook separate,
sweep unaffected). S0 reduced to the `test_safety` additions.

## Quant amendment 2026-10-25 (spec amended; C1/C5/C6/C8 done)
- Spec sections 2, 5(b), 5(e), 5.1, 8.1, 11, 12, 13, 14 amended (tagged in the spec). C1: hedge venues per set,
  prior recomputed: GO set keeps 13 / 40 core-venue episodes hedgeable (all T lost; 13 / 15 ex T), 9 pass the
  pessimistic 0.3 %, 0 pass 0.5 %, 8 of the 9 are one coin (ANIME). C5: `PERP_HISTORY_MISSING` (kline coverage
  >= 90 %, tiers loaded on okx/kucoin). C6: relative basis confirmed; buffer needs a parallel time array
  (memory ~17-58 MB, not 9-29 MB); exit perp spread charged in `P_exp`. C8: both legs stay open while the hedge
  is unpriceable; final adverse booking at `t0 + 30 h`.
- **HT-only (user decision 2026-10-25):** AC5 and review C9 (golden hashes, "HT on == HT off", 4x
  `paper_resumed`) are dropped. HT sets name `spot_venues` explicitly (no parent-set top-N membership); HT run
  hash = HT params only. Deploy = fresh DB, 2x `hedged_run_started`. S0 golden pins, S11 "parent definition
  hash" and the S13/S15 resume checks need a rewrite by architect/backend-lead.

## Implementation steps (one commit each; `make check` green; HT stays disabled in the TOML until S13)
- [x] **S0 (safety part only; pins dropped) Golden pins + safety rules.** Test pins the literal definition hashes of `all`,
  `excl_conditional`, `excl_bybit`, `excl_gateio` from the committed `config/nexus.toml`. `test_safety`:
  forbid `set_?leverage`, `set_?margin\w*`, `set_?position_?mode`, `(add|reduce)_?margin`. AC: tests pass
  at HEAD with no production code change; the orchestrator records the pinned hashes and cross-checks them
  with `make go-report` (read-only).
- [x] **S1 Domain types + port.** `domain/perp.py` (PerpMarket, PerpTicker, FundingInfo, MarkKline,
  FundingPayment, LeverageTier; Decimal, validation), `interfaces/perp.py` `IPerpMarketData`,
  `adapters/perp/registry.py`. AC: validation unit tests (contract size > 0, sane fees/MMR, funding sign
  kept); mypy strict.
- [x] **S2 ccxt perp base + OKX swap adapter.** No credentials, `install_read_only_guard`,
  `fetchCurrencies: False`, `fetchMarkets` swap only; contracts -> base units; kline paging (100 rows);
  per-instrument funding. AC: recorded public fixtures (markets, tickers, funding, book, klines, tiers);
  falsy `apiKey`; POST/DELETE via `request()` and an implicit method raise `ReadOnlyViolationError`; 429
  -> `ExchangeRateLimitError`; limits written in the docstring.
- [x] **S3 KuCoin futures adapter.** Same AC as S2 (contracts/active as the funding source, multiplier,
  depth20/100).
- [x] **S4 Binance USDⓈ-M adapter.** Same AC as S2. A test asserts that `leverageBracket` (signed) is
  never called.
- [x] **S5 Transfer metadata extension.** `NetworkInfo` gets `withdraw_min`, `deposit_min`,
  `deposit_confirmations`, `est_arrival_min`, `busy` (optional, default None); parsers (ccxt, binance
  public, kucoin, okx); per-venue `transfers_loaded_at_ms` on `MarketUniverse`; pure
  `list_transfer_routes()` (added to the safety allowlist, security sign-off). AC: regression test that
  all pre-existing `NetworkInfo` fields are identical on every existing fixture; `select_transfer_route`
  tests unchanged; S0 pins still pass.
- [x] **S6 Transit-time model** (`simulation/transit.py`, pure): block-time table, seeded lognormal +
  p_stuck, `tau_p50`/`tau_p95`, seed from `position_key`. AC = card AC4.
- [x] **S7 Basis buffer + vol stats** (`simulation/basis.py`, pure): fixed-point `array('q')` ring
  buffer, median/std at lag, z-score, warm-up; sigma_1m and max rise from klines. AC: hand-computed
  stats; memory bound test (keys x 720 x 8 B); missing samples are not imputed.
- [x] **S8 Hedged portfolio I: pre-checks + entry** (`simulation/hedged.py`, pure Decimal): pools,
  pre-checks a-f with their exact skip reasons (first failure wins), sizing, lot/contract rounding, margin,
  P_liq, leg reserve. AC = card AC2 + entry parts of AC1.
- [x] **S9 Hedged portfolio II: hold + exit + capital.** Funding accrual (idempotent per funding time),
  liquidation (kline high and poll), partial/forced exit, unpriceable hedge rule (C8), USDT rebalancing,
  valuation (open basis MTM). AC = card AC1 + AC3; P&L identity sums exactly.
- [x] **S10 Migration + ORM + repository.** Additive revision (`paper_hedged_*` only), `IHedgedPaperRepository` /
  `persistence/hedged_repository.py` (`ensure_run`, atomic commit, restore, idempotent events). AC
  (integration, `nexus_test`/CI): upgrade creates only the new tables, downgrade drops only them; full
  position round trip; duplicate funding event rejected by the unique key.
- [x] **S11 Config.** (done; HT-only: no parent hash, `sets`/`spot_venues` explicit, hash pinned in `tests/unit/config/test_paper_hedged.py`, `payload_version` 1 in the repository codec) `PaperHedgedSettings` (`PAPER_HEDGED_*`, `[paper_hedged]`, code default
  `enabled=false`), `TOML_ALLOWED` keys, validation (hedge venues within the parent set and the enabled
  exchanges, parent set exists, leverage 1-5, thresholds > 0, id <= 32 chars); HT run hash = HT params +
  parent definition hash. TOML gets both HT sets but `enabled = false`. AC: S0 pins pass; config tests;
  the HT hash changes when any HT parameter changes.
- [ ] **S12 PerpFeed** (`scanner/perp_feed.py`): polling loop (30 s / 60 s), cache + ages, per-venue
  backoff/health (separate from spot), kline/tier incremental cache + prefetch API, basis sampling. AC:
  fake-port tests for cadence, 429 pause of the perp venue only, stale flags, cancellation (no hang on
  stop), never-raise loop.
- [ ] **S13 Wiring + restart.** `scanner/hedged.py` (`HedgedTrader`/`HedgedBook`), scanner hooks
  (`observe_spot`, spawned `on_alert`, PerpFeed task), container (perp clients only for hedge venues of
  enabled sets), restart/gap replay and `late_exit`; TOML `enabled = true`. AC = card AC5 (with S0 pins,
  HT on) + AC7; isolation tests: a blocking fake feed never delays `sweep()`, and an exception in HT leaves
  `PaperBook` outcomes identical.
- [ ] **S14 GO report HT section** (`reports/go_hedged.py` + render, JSON + Markdown; directional-MTM
  leak, basis-dominated, hedge-break, late-exit, unpriceable flags; shadow-exit P&L) **plus the short-window
  preliminary verdict, spec section 16.6 fields** (active/gap hours, base + pessimistic rate per 720 active h,
  6 h + day block bootstrap, LB/UB, ex-top-2, label + flags; needs per-hour coverage counters from S10/S13). AC = card AC8
  (integration fixture on `nexus_test`).
- [ ] **S15 Docs + deploy prep.** Russian guide in `docs/guides/`, English config comments, deploy checklist
  (pinned hashes vs the go-report, expected log lines: 4x `paper_resumed`, 0x `paper_run_restarted`, 2x
  `hedged_run_started`). AC = card AC9 + review by quant/tech-lead/security.

## Deploy (after review; U4 user OK required)
Rebuild image -> migrator `alembic upgrade head` (exit 0) -> recreate scanner only. Verify logs: 4x
`paper_resumed`, 0x `paper_run_restarted`, 2x `hedged_run_started` (`ht_excl_conditional`, `ht_excl_conditional_bn`); first HT snapshot
within 15 min. Expected soak gap ~1-2 min.

## Out of scope
Real trading, withdrawals, internal transfers, leverage setting, Binance signed leverage brackets, variants
`sell_venue`/`buy_venue` running in the soak, DEX.

Progress 2026-10-25: S9 (97ef621) and S10 done. S10 adds revision `a7c1d93e5b20` (six `paper_hedged_*` tables incl.
`paper_hedged_coverage` hourly counters, sources `sweep` and `perp:<venue>`; writes wired in S13),
`IHedgedPaperRepository` + `persistence/hedged_repository.py` (JSON payload codec unit-tested; DB round trip and
migration up/down tests are integration, CI-only on `nexus_test`, not run locally). Next: S11.
