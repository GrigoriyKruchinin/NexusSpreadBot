# B15 part 1 -> review (tech-lead, quant-analyst, architect)

Scope done: card Scope 1-4, digest per-set line + "filter"/"estimate" labels, R2-1 fix. AC 1-5, 7, 8.
Part 2 (Scope 5 quant GO report generator, AC 6) is NOT done.

## Changes
- Config: `PAPER_VENUE_SETS` (`src/nexus/config/venue_sets.py`, groups/roles), `.env.example`,
  `docker-compose.local.yml`; fail-closed validation (names, unknown venue, >= 2 venues, `all` present).
- Simulation/scanner: `PaperBook` of independent `PaperTrader`s (own lock, inventory, rebalancing,
  cooldowns, rows); route belongs to a set only if both legs are in it; top-N cap applied per set
  (`engine/candidates.py`); equal fixed capital per set; failure in one set is isolated.
- Persistence: `portfolio_id` on `paper_trades`, `paper_rebalances`, `paper_balance_snapshots`;
  `load_state(portfolio_id)`, `commit(portfolio_id=...)`; B14 digest queries filter on `all`.
- Digest: per-set line (since, trades, hedged P&L), B14 lines labelled filter/estimate.
- R2-1: `_episodes` returns `EpisodeStats(total_excl_conditional=0)` on an empty window (+ unit test).

## Migration b15a7c3e91d2 (down_revision 40c869df951f) - for architect sign-off
- `portfolio_id VARCHAR(32) NOT NULL DEFAULT 'all'` on 3 tables (metadata-only backfill on PG >= 11).
- Old single-column indexes dropped and replaced by composites led by `portfolio_id`:
  trades (portfolio_id, executed_at); rebalances (portfolio_id, started_at) and (portfolio_id, status);
  snapshots (portfolio_id, captured_at). Rationale: every query is per portfolio.
- Server default kept for rolling deploys; no FK/lookup table (set names are config).
- Downgrade deletes non-`all` rows (they would corrupt the single-portfolio restore); `all` rows kept.
- Tests (CI only, not run locally, not applied to any DB here): `tests/integration/test_migration_b15.py`
  (downgrade, seed, upgrade: backfill + row counts, downgrade drops shadow rows),
  `tests/integration/test_paper_portfolios.py` (per-set restore and per-set digest sums).
- Gate: NOT applied to live `nexus`; needs A5a restore drill + user OK (U4).

## Latency (AC7)
Synthetic in-memory stream, 300 symbols x 3 venues, 900 routes, cap 50, 35 sweeps each, fake exchanges
(`bench` ran via the unit Harness; script not committed). Sweep wall time p50 / p95:
1 set 7.7 / 8.2 ms; 2 sets 7.7 / 8.5 and 7.6 / 7.8 (two runs); 4 sets 9.6 / 10.1 and 9.7 / 10.4.
2 sets: no change beyond noise. 4 sets: about +2 ms (+25 %) on a sweep that in production is dominated by
network calls (seconds), so negligible; no NEEDS_USER.

## Checks
772 unit tests, coverage 91 % (>= 89), ruff 0, mypy --strict 0.

## Open risks
- Per-set cap makes the union candidate count grow with sets (bounded by sets x cap).
- Accrual rule: a newly added set has data only from its first snapshot (`since`), no backfill.
- Two intermediate local commits failed pre-commit mypy on partial trees; all work is in one commit f9ac581.
- Part 2 needed before the soak yields GO numbers; migration must be applied (U4) before the soak.

## Round 2 (commit c61b060)
Gate: 794 unit tests, ruff 0, mypy --strict 0; integration tests run in CI only (nothing applied to any DB locally).

| Point | Fix | Tests |
|---|---|---|
| A run registry | `paper_portfolios` (+ `config_hash`, venues, capital, `started_at`) created in the same unapplied migration b15a7c3e91d2; pre-B15 rows become one legacy run of `all` (hash `legacy`) at the earliest row. A definition/hash mismatch (incl. legacy) starts a FRESH run with fresh `PAPER_CAPITAL_USD` instead of refusing: every set always has equal capital and the soak cannot be blocked by a config tweak; old rows stay but are never restored. `since` comes from the registry (survives retention purge). | `test_paper_runs.py`: legacy -> fresh equal capital, same definition resumes, each sizing parameter changes the hash; integration `test_paper_portfolios.py` |
| B coin slot | idle >= 24 h (`groups.py` setting, 0 = never) frees the slot: coin converted to USDT, cost booked, new coin trades; otherwise separate skip reason `COIN_BUDGET_EXHAUSTED` | `test_idle_coin_slot_*`, `test_budget_exhausted_*` |
| C cap stats | `SetSweepStats` (eligible/selected per set) -> `CapStatsBuffer` (`scanner/capstats.py`) -> hourly `paper_cap_stats`, flush failure-tolerant | `test_cap_binding_*`, `test_cap_stats_buffer_*` |
| D migration test | `test_migration_b15.py`: seeded rows in every touched table (incl. paper_trades), backfill, NOT NULL/default/length, expected indexes, legacy run, rolling-deploy insert, downgrade drops shadow rows and new tables | CI |
| E 5-9 | membership fails closed; skip rows survive missing markets; non-Exception BaseException re-raised, cancellation propagates; digest `since` in DIGEST_TZ; empty CONDITIONAL_VENUES documented in `.env.example` (strict sets); one set's resume failure disables only that set | `test_paper_runs.py` |

Sets x cap expansion with 4 sets (all, excl_conditional, excl_bybit, excl_gateio): union candidate count is bounded by 4 x cap (200 at cap 50). Sets are nested subsets of `all`, so their top-N overlap strongly and the union is expected well below the bound. NOT measured on live data (no production access); the new `paper_cap_stats` table records eligible/selected per set per hour, so the soak measures it. Earlier synthetic latency (4 sets +2 ms/sweep) stands.

Non-blocking follow-ups: expose union-size per sweep as a Prometheus metric; commit the latency bench script; A7 config file replaces the long env set definition.

## Round 3 (commits 2854904, 8ffb9c3 + docs commit)
Gate: 806 unit tests, ruff 0, mypy --strict 0; integration tests in CI only.

| Point | Fix | Tests |
|---|---|---|
| R2-1 [High] capital growth on recycle | `PaperPortfolio._fund_from_recycled_usdt`: a new coin seed is paid from the USDT freed by a conversion (excess of the USDT seed over `usdt_per_exchange`, derived from seeds so it survives restart): USDT seed and balance debited, sum of seeds unchanged. Conversion cost (0.3 %) and `rebalance_costs` unchanged. | `test_idle_slot_is_converted_back_to_usdt_and_reused` (fixed: capital == before, mtm identity), new `test_capital_is_fixed_after_many_recycles` (6 recycles, capital constant, mtm = total - realized + rebal) |
| R2-2 [Med] digest `_paper` run scope | every query of `DigestRepository._paper` (snapshot, IN_FLIGHT, window, lifetime and excl totals) bounded by the current `all` run `started_at` | integration `test_digest_paper_block_ignores_rows_of_earlier_runs` (old run incl. IN_FLIGHT 900 USDT, trades, rebalances excluded) |
| R2-3 + R2-N1 | `PortfolioRun.previous_hash`; restart logs `paper_run_restarted` at WARNING (portfolio, run_id, old/new hash prefix, since_ms, capital; no secrets); digest line "Набор X перезапущен <since>" via `PortfolioSummary.restarted` (run began in the window and an earlier run existed); `.env.example` note | `test_changed_strategy_starts_a_fresh_run_and_warns`, `test_digest_says_when_a_set_restarted_with_its_new_since`, integration `test_digest_flags_a_set_restarted_inside_the_window` |
| C1 strategy in hash | `strategy` sub-dict: whole `EstimatorConfig` (thresholds, ages, skew, gross caps, verified flags, taxes), route trade cooldown, plus container-provided latency, candidate cap, alert cooldown, re-alert growth, default taker fee, unverified cap, min quote volume | `test_strategy_parameters_are_part_of_the_run_hash`, `test_strategy_settings_change_the_run_hash` (5 env settings) |
| R2-4 tz | non-UTC digest test (Asia/Tokyo) | `test_digest_since_is_rendered_in_the_digest_timezone` |
| R2-5 flush timeout | `CapStatsBuffer.flush` under `asyncio.timeout(3 s, FLUSH_TIMEOUT_S)`; timeout/failure logs a warning, counters put back; cancellation also puts back and re-raises. Covers sweep and shutdown paths | `test_cap_stats_flush_times_out_without_losing_counters`, `test_cap_stats_flush_cancellation_keeps_counters` |
| 7 | "Soak checkpoint" section in the task card | - |

Notes: per-venue fee tiers fetched from exchanges at runtime are not config and are not hashed (default taker fee is). A restart-line stays in the digest only for the day of the restart. CI run of the first commit failed on a test bug (fixture trade stamped before the new run); fixed in the docs commit.

## Follow-ups F1/F3 (after round 3 ACCEPT)
- F1 closed: `_fund_from_recycled_usdt` now returns the amount actually funded and the new coin
  seed is sized to it when a recycled excess exists (a USDT shortfall shrinks or skips the seed;
  fresh capital is never injected). Test: `test_recycle_with_a_usdt_shortfall_never_injects_capital`
  (reproduced 1500 -> 1740 before the fix). `PaperTrader._check_capital` logs WARNING
  `paper_capital_drift` (once per value, no secrets) if seeds exceed the configured capital.
- F3 closed: run-hash `strategy` now includes quote_assets, symbols whitelist/blacklist,
  orderbook_depth and the four QUARANTINE_* thresholds (`container.py`); parametrized test in
  `tests/unit/test_container_paper.py`. Existing runs restart fresh once on deploy (hash change).
- F2 open: moved to part 2 of the card (fee disclosure in the GO report).
