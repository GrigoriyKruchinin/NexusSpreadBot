# Migration plan — as-is to target, by small steps

Date: 2026-10-23. Author: architect. Status: accepted (U2, ADR 0006). Target: `target.md`.
Each row is a task-card candidate (`docs/pipeline/task-format.md`). Every step: behaviour-preserving
unless stated, `make check` not worse than baseline (481 tests, 89 % branch, ruff 0, mypy 0),
one commit, no big bang.

Revised 2026-10-23 after critical review: B1 first on the critical path; split C reduced to
C0-C6 (5 new classes instead of 12, step IDs renumbered); C9 uses typed optional ports instead
of tiers/flags; E-steps unscheduled (U2 option A).

Legend: cx = complexity (L/M/H); owner = suggested agent; dep = depends on.

## Ordering rules

1. **B1 first**: the default config must match ADR 0002 before any soak or analytics run.
2. Track 0 safety net (test-DB guard, CI) next — nothing below merges without CI green.
3. Small correctness fixes (B) land **before** the split (C): they touch the same code, and
   their new tests become characterization tests for the split.
4. Any Alembic migration (B7, B12) waits for R-09 backups and is a U4 point (P9: backup first).
5. The split (C) moves code without changing behaviour; one component per step.
6. E-steps are **unscheduled** (U2 option A, ADR 0006): DEX is revisited after the GO result.

## A. Track 0 (already in `todo.md`; listed for ordering only)

| ID | Step | owner | cx |
|---|---|---|---|
| A1 | R-01 integration tests refuse any DB except `nexus_test` — **done** (3d5441f) | tester | L |
| A2 | R-05 CI: lint, mypy, unit, integration with services, secret scan, coverage floor 89 % | devops | M |
| A3 | R-06 deps (certifi, protobuf), pip-audit incl. dev group | devops/security | L |
| A4 | R-07 silence httpx INFO, scrub tokens in stdlib loggers | backend-lead | L |
| A5 | R-09 pg_dump backups + external heartbeat; Redis auth; DB roles (minimum `nexus_app`/`nexus_migrator`/`nexus_ro`, target.md §4) | devops | M |

## B. Correctness fixes (pre-split, each with a failing-first test)

| ID | Step | Acceptance (measurable) | owner | cx | dep |
|---|---|---|---|---|---|
| B1 | Add `CORE_EXCHANGES` (binance, bybit, gateio, kucoin, okx) and make it the default `EXCHANGES_ENABLED`; `.env.example` + compose in sync (ADR 0002/0004) | default-settings test lists exactly the five core venues; bitget/mexc still loadable when set explicitly | backend-lead | L | — |
| B2 | R-02 isolate ticker and metadata fan-out: any exception per exchange -> recorded failure, sweep continues (A3, A4) | test: adapter raising `AttributeError` -> sweep completes, heartbeat written, health failure recorded | backend-lead | L | A2 |
| B3 | Log + count failed per-route evaluation tasks (A2); `SweepResult.failed` | test: route task raising -> 1 log event, `failed == 1` | backend-lead | L | — |
| B4 | R-08a fix `_until_stopped` cancellation swallowing (A1) | test: cancelling `run` while a child runs propagates `CancelledError` | backend-lead | L | — |
| B5 | R-04a DB timeouts: `pool_timeout`, asyncpg `timeout`/`command_timeout`, `statement_timeout`, `lock_timeout` via settings | unit test of engine kwargs; integration: slow query is cut | backend-lead | L | A1 |
| B6 | Batch `exchange_health` inserts per sweep (D8) | one transaction per sweep for health rows | backend-lead | L | — |
| B7 | R-04b purge: standalone time indexes on `exchange_health`, `exchange_metadata_stats`; batched `DELETE ... LIMIT` loops; paper tables retention (D3, D4, D7) | EXPLAIN uses index on test DB; purge runs in N bounded transactions | backend-lead | M | A5 (backup), U4 |
| B8 | R-04c measure real row growth for 48 h of soak; decide sampling / index drop / partitioning (D1, D2, D5) | report `docs/reports/db-growth.md` with rows/day per table; decision ADR if partitioning | backend-lead + quant | M | A5, soak |
| B9 | R-03a UNKNOWN transfer status never counts as profitable; stored evaluations carry `cost_complete` flag (M2) | test: UNKNOWN transfer -> not `PROFITABLE`, flag false | backend-lead | M | quant math-review |
| B10 | R-03b fee currency per exchange (base vs quote vs discount token) in market metadata and estimator (M1) | hand-computed cases per venue match | backend-lead + quant | M | B9, crypto-specialist input |
| B11 | R-03c stablecoin peg guard (USDT/USDC vs USD reference) (M3) | depeg above threshold marks evaluations degraded | backend-lead | L | B9 |
| B12 | R-13 reaper for stale `SENDING` alert rows + payload version `v` in Celery events (C1, I8) | test: SENDING older than T -> FAILED and logged; old payload without `v` still accepted | backend-lead | L | — |
| B13 | WS fixes: `_give_up` unwatches; stream errors feed `ExchangeHealthTracker` (A5, A7) | tests on `OrderBookStreams` | backend-lead | L | — |
| B14 | R-08b clock domains (ADR 0005): staleness/skew on local receive time (REST stamped at request start), exchange timestamp optional/diagnostic, host offset probe (median, RTT/2) -> warning + health flag | tests with skewed fake clocks, missing timestamp, negative age; hand-computed math unchanged; before/after STALE share noted in card | backend-lead + crypto | M | B4 |

## C. Structure: split `scanner/service.py` and fix layering

Before C1: confirm characterization coverage of `Scanner.sweep`/`run` (B2–B4 add most of it).
Split rule (ADR 0003): extract only stateful components/stages; reuse existing modules; stop when
every module is < ~300 lines.

| ID | Step | Acceptance | owner | cx | dep |
|---|---|---|---|---|---|
| C0 | Characterization pack for `Scanner.sweep`/`run` (repo calls, `SweepResult`, alerts) where missing | coverage of `service.py` not lower; tests independent of internals | tester | L-M | B2–B4 |
| C1 | Extract `ScannerRuntime` (`run`, `_until_stopped`, `_announce_start`, `_spawn`, `_latency_checks`, shutdown) | exception logging and bounded shutdown tested | backend-lead | L | C0 |
| C2 | Extract `TickerCollector` (`_fetch_all_tickers` + batched `_record`) | unit tests; Scanner tests unchanged | backend-lead | L | C0, B6 |
| C3 | Extract `FeeRefiner` (5 fee methods + caches/semaphores) | same | backend-lead | L | C0 |
| C4 | Extract `BookProvider` (`_fetch_book`, `_rest_book_for`, `_confirm_with_rest`, `_update_streams`) | same | backend-lead | M | C2 |
| C5 | Extract `CandidateEvaluator` (`_evaluate_candidates`, `_evaluate`) | same; deadline behaviour tested | backend-lead | M | C3, C4 |
| C6 | Move remaining glue into existing modules: quarantine -> `quarantine.py`, episodes/alerts -> `episodes.py`, metadata refresh -> `universe.py`, paper glue -> `paper.py`; `Scanner` = thin pipeline | every `scanner/` module < ~300 lines; wiring only in `container.py` | backend-lead | M | C1–C5 |
| C7 | Review the 25 `except Exception` (TD-07): narrow, log with context, or justify inline | list in `docs/reports/except-review.md`; zero silent handlers | tech-lead (review) + backend-lead | M | C6 |
| C8 | Layering: move `RouteQuote` + portfolio DTOs to `domain`; move `EstimatorConfig.from_settings` to composition; import contract in CI (`import-linter` dev dep, or a small AST test if no new dep is wanted) | contract passes in CI | backend-lead + devops | L-M | C6, A2 |
| C9 | `VenueHandle` with typed optional ports resolved in `container.py`, replacing `isinstance` discovery (ADR 0004, I2) | no `isinstance` on ports and no venue-name branches in `scanner/`; mypy strict clean | backend-lead | M | C6, B1 |
| C10 | Singleton scanner lease: Redis `SET NX PX`, renewed each sweep (C5) | second instance logs and waits; test with fake store | backend-lead | L | C1 |

## D. Observability seam (with observability-engineer)

| ID | Step | owner | cx | dep |
|---|---|---|---|---|
| D1 | `IMetrics` port with no-op default; components emit counters/latencies (sweep stages, per-exchange errors, stale share, clock offset, queue length) | backend-lead | M | C6 |
| D2 | Stack ADR + dashboards as code (Grafana/Prometheus or alternative, free/OSS) | observability-engineer | M | D1 |

## E. DEX — unscheduled (U2 option A, ADR 0006)

Not task-card candidates now. Revisit after the GO result; if DEX is chosen then, a new ADR fixes
the `LegQuote` shape first. E1 alone may be pulled forward on evidence of CEX network/contract
mismatches (crypto-specialist), without any DEX code.

| ID | Step | owner | cx | dep |
|---|---|---|---|---|
| E1 | Asset identity registry `(venue, symbol) -> (asset_id, network, contract)`; used by transfer routing | crypto-specialist + backend-lead | M-H | C9 |
| E2 | `LegQuote` seam: engine prices legs from `LegQuote`; CEX depth walk produces it (no math change, hand-computed tests identical) | backend-lead + quant | M | C5, E1 |
| E3 | Read-only DEX quote provider (one chain, one aggregator) behind `BaseDEXProvider`; gas in cost; analytics only | dex-engineer (not hired) | H | E2, lawyer DEX review |

## Out of scope until GO (ADR 0001, P7)
Executor, risk module code (the `risk-manager` agent only writes specs in `docs/risk/` from
Stage 2 design), any order or withdrawal code, production deploy, all E-steps.

## Critical path (suggested)
**B1** → A2 → B2–B4, B12, B13 (parallel) → C0 → C1…C6 → C7–C10 → D1.
B1 is first because every soak/analytics run before it would mix extension venues into GO data.
B5–B11, B14 run in parallel with C where files do not overlap (B9–B11 touch `engine/`, C touches
`scanner/`). B7/B8 wait for A5 backups and soak data.
