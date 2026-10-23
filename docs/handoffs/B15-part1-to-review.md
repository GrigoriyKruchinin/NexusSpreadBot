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
