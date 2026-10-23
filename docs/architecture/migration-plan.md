# Migration plan — as-is to target, by small steps

Date: 2026-10-23. Author: architect. Target: `target.md`. Each row is a task-card candidate
(`docs/pipeline/task-format.md`). Every step: behaviour-preserving unless stated, `make check`
not worse than baseline (481 tests, 89 % branch, ruff 0, mypy 0), one commit, no big bang.

Legend: cx = complexity (L/M/H); owner = suggested agent; dep = depends on.

## Ordering rules

1. Track 0 safety net first (test-DB guard, CI) — nothing below merges without CI green.
2. Small correctness fixes (B) land **before** the split (C): they touch the same code, and
   their new tests become characterization tests for the split.
3. Any Alembic migration (B7, B12) waits for R-09 backups and is a U4 point (P9: backup first).
4. The split (C) moves code without changing behaviour; one collaborator per step.
5. E-steps run only if U2 puts DEX in scope.

## A. Track 0 (already in `todo.md`; listed for ordering only)

| ID | Step | owner | cx |
|---|---|---|---|
| A1 | R-01 integration tests refuse any DB except `nexus_test` (in progress: `tests/db_guard.py`) | tester | L |
| A2 | R-05 CI: lint, mypy, unit, integration with services, secret scan, coverage floor 89 % | devops | M |
| A3 | R-06 deps (certifi, protobuf), pip-audit incl. dev group | devops/security | L |
| A4 | R-07 silence httpx INFO, scrub tokens in stdlib loggers | backend-lead | L |
| A5 | R-09 pg_dump backups + external heartbeat; Redis auth; per-service DB roles | devops | M |

## B. Correctness fixes (pre-split, each with a failing-first test)

| ID | Step | Acceptance (measurable) | owner | cx | dep |
|---|---|---|---|---|---|
| B1 | Default `EXCHANGES_ENABLED` = 5 core venues; `.env.example` + compose in sync (ADR 0002) | default settings test lists exactly binance, bybit, gateio, kucoin, okx | backend-lead | L | — |
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
| B14 | R-08b clock domains (ADR 0005): staleness/skew on local receive time, host offset probe via public server time, degraded flag | tests with skewed fake clocks; no change in hand-computed math | backend-lead + crypto | M | B4 |

## C. Structure: split `scanner/service.py` and fix layering

Before C1: confirm characterization coverage of `Scanner.sweep`/`run` (B2–B4 add most of it).

| ID | Step | Acceptance | owner | cx | dep |
|---|---|---|---|---|---|
| C0 | Characterization pack for `Scanner.sweep`/`run` (repo calls, `SweepResult`, alerts) where missing | coverage of `service.py` not lower; tests independent of internals | tester | L-M | B2–B4 |
| C1 | Extract `TaskSupervisor` (`_spawn`, `_latency_checks`, shutdown) | bounded size, exception logging tested | backend-lead | L | C0 |
| C2 | Extract `HealthRecorder` + `TickerCollector` (`_record`, `_fetch_all_tickers`) | unit tests per class; Scanner tests unchanged | backend-lead | L | C0, B6 |
| C3 | Extract `FeeRefiner` (5 fee methods + caches/semaphores) | same | backend-lead | L | C0 |
| C4 | Extract `BookProvider` (`_fetch_book`, `_rest_book_for`, `_confirm_with_rest`, `_update_streams`) | same | backend-lead | M | C2 |
| C5 | Extract `CandidateEvaluator` (`_evaluate_candidates`, `_evaluate`) | same; deadline behaviour tested | backend-lead | M | C3, C4 |
| C6 | Extract `QuarantineCoordinator` (quarantine methods, `_route_transfer`, `_parked_evaluations`) | same | backend-lead | M | C0 |
| C7 | Extract `EpisodeCoordinator` + `AlertGate` (`_track_episodes`, `_announce_closed`, `_check_latency`, `_alert`, `_alert_episode`) | same | backend-lead | M | C1 |
| C8 | Extract `MetadataRefresher`; reduce `Scanner` to `SweepPipeline` + `ScannerRuntime` | `service.py` (or successors) each < 300 lines; container wiring only in `container.py` | backend-lead | M | C1–C7 |
| C9 | Review the 25 `except Exception` (TD-07): narrow, log with context, or justify inline | list in `docs/reports/except-review.md`; zero silent handlers | tech-lead (review) + backend-lead | M | C8 |
| C10 | Layering: move `RouteQuote` + portfolio DTOs to `domain`; move `EstimatorConfig.from_settings` to composition; add import contract check to CI (new dev dep `import-linter`, minor) | contract passes in CI | backend-lead + devops | L-M | C8, A2 |
| C11 | Registry tiers (`core`/`extension`) + declared adapter capabilities replacing `isinstance` (ADR 0004, I2) | no `isinstance(..., IWebSocketOrderbook/ITradingFeeSource)` in `scanner/`; tier visible in DB health/analytics | backend-lead | M | C8, B1 |
| C12 | Singleton scanner lease in Redis (C5) | second instance logs and waits; test with fake store | backend-lead | L | C8 |

## D. Observability seam (with observability-engineer)

| ID | Step | owner | cx | dep |
|---|---|---|---|---|
| D1 | `IMetrics` port with no-op default; components emit counters/latencies (sweep stages, per-exchange errors, stale share, clock offset, queue length) | backend-lead | M | C8 |
| D2 | Stack ADR + dashboards as code (Grafana/Prometheus or alternative, free/OSS) | observability-engineer | M | D1 |

## E. Conditional on U2 (DEX in scope)

| ID | Step | owner | cx | dep |
|---|---|---|---|---|
| E1 | Asset identity registry `(venue, symbol) -> (asset_id, network, contract)`; used by transfer routing | crypto-specialist + backend-lead | M-H | C11 |
| E2 | `LegQuote` seam: engine prices legs from `LegQuote`; CEX depth walk produces it (no math change, hand-computed tests identical) | backend-lead + quant | M | C5, E1 |
| E3 | Read-only DEX quote provider (one chain, one aggregator) behind `BaseDEXProvider`; gas in cost; analytics only | dex-engineer | H | E2, lawyer DEX review |

## Out of scope until GO (ADR 0001, P7)
Executor, risk-manager module, any order or withdrawal code, production deploy.

## Critical path (suggested)
A1 → A2 → B1–B4, B12, B13 (parallel) → C0 → C1…C8 → C9–C12 → D1.
B5–B11, B14 run in parallel with C where files do not overlap (B9–B11 touch `engine/`, C touches
`scanner/`). B7/B8 wait for A5 backups and soak data.
