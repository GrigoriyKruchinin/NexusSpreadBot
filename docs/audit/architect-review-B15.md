# Architect review — B15 part 1 schema and migration (card AC4)

- reviewer: architect
- date: 2026-10-23
- scope: migration `b15a7c3e91d2` (down `40c869df951f`), `persistence/models.py`, B15 query changes in
  `persistence/repositories.py` (commit f9ac581), `tests/integration/test_migration_b15.py`,
  gate text in `docs/architecture/migration-plan.md`.
- method: static review only. No DB touched, nothing executed; sizes are estimates.

## Verdict: RETURN

The column, backfill and index design are sound and safe to apply later. The return is for one
correctness defect in how the per-set `since` is derived (it breaks Scope 4 once the soak runs past
the paper snapshot retention window) and gaps in the migration test that AC4 asks for. Both are cheap
to fix now, because the migration has not been applied to any persistent DB yet; after U4 the fix
needs a second migration.

## Blocking points (must fix)

1. **Per-set `since` is lost after retention** (`repositories.py` `DigestRepository._portfolios`, and
   the planned part-2 report). `since` = `min(paper_balance_snapshots.captured_at)` per portfolio, but
   `RetentionRepository.purge` deletes snapshots older than `snapshot_retention_days` (default 7) and
   keeps only the latest set per portfolio. On any soak longer than 7 days, `since` moves forward for
   every set, so the digest and the GO report show a wrong accrual start and wrong $/month
   normalisation. Fix (preferred): a small registry table in this same migration:
   `paper_portfolios(portfolio_id VARCHAR(32) PK, created_at timestamptz NOT NULL,
   venues TEXT NOT NULL, capital_usd NUMERIC NOT NULL)`; backfill `'all'` with
   `created_at = least(min(captured_at), min(executed_at), min(started_at))` from the existing rows
   (fall back to `now()` if the tables are empty); insert at startup with `ON CONFLICT DO NOTHING`;
   `since` is read from it. Acceptable alternative if you want no new table: exempt the earliest
   snapshot set per portfolio from retention, and add a test for that. Add an integration test either
   way: purge past the window, and `since` stays the same.
2. **A set's definition can change under the same name.** If `excl_gateio` is later redefined (other
   venues, other capital), its old and new rows mix with nothing to show it, so the counterfactual
   becomes invalid. With the registry from point 1: on startup, compare the configured venues/capital
   with the stored row and fail closed. The error names the set and says to use a new name. Without a
   registry this cannot be detected at all, which is the second reason to prefer the table.
3. **The migration test does not prove what AC4 says** (`tests/integration/test_migration_b15.py`):
   - no `paper_trades` row is seeded, so `assert ids in ([], [("all",)])` passes on an empty table
     and proves nothing for trades. Seed at least one trade (executed, `episode_id` NULL) and assert
     `[("all",)]` exactly for all three tables;
   - the downgrade check covers snapshots only. Seed one non-`all` row in each of the three tables,
     then assert that the per-table counts after downgrade equal `before`;
   - assert the index set after upgrade (the composites exist, the old single-column ones are gone)
     and after downgrade (old ones restored), e.g. via `pg_indexes`;
   - assert `portfolio_id` is NOT NULL with default `'all'` (`information_schema.columns`).
   If point 1 adds the registry table, also cover its backfill and its drop on downgrade.

## Checked and accepted (no change needed)

- **Column**: `VARCHAR(32) NOT NULL DEFAULT 'all'` on all three tables. It matches the validator
  `^[a-z0-9_]{1,32}$` (`venue_sets.py:21`) and the model (`String(32)`, `Mapped[str]` = NOT NULL,
  server default = `DEFAULT_PORTFOLIO_ID` = `"all"`), so there is no autogenerate drift. No FK and no
  enum is the right call, because set names come from config.
- **Backfill**: on PostgreSQL 17 (`postgres:17-alpine`), ADD COLUMN with a constant default plus
  NOT NULL only changes metadata: no table rewrite, and existing rows read as `'all'`. Correct and
  O(1).
- **Indexes vs queries**:
  - `load_state`: max(captured_at) per pid, then the snapshot set at latest, use
    (pid, captured_at) as an index-only backward scan;
  - in-flight rebalances per pid use (pid, status);
  - digest `_paper`: every window predicate binds pid = 'all' plus a time range, which matches the
    composites exactly;
  - the retention correlated `EXISTS` uses (pid, captured_at);
  - the `UPDATE ... WHERE id AND pid` uses the PK.
  - Lifetime sums (`sum(net_usd) WHERE pid AND executed`) scan the whole portfolio, as they did
    before B15 (a sequential scan then), so this is no regression.
  Dropping the old single-column indexes is correct: each one is a strict prefix of nothing a query
  still uses on its own, apart from the two cases in N2.
- **Locks and duration** (estimate): Alembic runs the migration in one transaction (`env.py`). It takes
  ACCESS EXCLUSIVE on the three paper tables (brief for ADD COLUMN), and the lock is held to commit
  across the non-concurrent CREATE INDEX builds. The paper tables are small: snapshots are written
  only on change, rebalances are rare, and trades are at most about 10^5-10^6 rows. So the whole
  migration should take well under 10 s. This is fine because the `migrator` service runs before the
  scanner starts. `CONCURRENTLY` is not needed.
- **Rolling safety**: an old writer still running after the upgrade gets `'all'` from the server
  default, and old readers see only `'all'` rows until new code writes shadow rows. Safe.
- **Downgrade semantics**: deleting non-`all` rows before dropping the column is the only correct
  option, because the restore code before B15 sums all rows. It is accepted, with one condition: shadow
  soak data cannot be regenerated (re-creating it means re-running the soak). So on live `nexus`, a
  downgrade is allowed only right after a fresh A5a `pg_dump`, and the U4 runbook must state this.
  Apart from those rows, the migration is fully reversible: `'all'` rows and the original indexes come
  back.
- **Live apply after U4**: safe as designed, provided the order is A5a backup, then verified restore
  drill, then stop the scanner, then `migrator`, then start the scanner.

## Non-blocking recommendations (track, do not hold B15)

- N1. Contract step after the deploy has settled: drop the server default and the ORM `default=`
  (follow-up migration). A future writer that forgets `portfolio_id` should then fail, instead of
  silently writing into the `all` GO baseline. `commit()` already requires the kwarg, so today this is
  only a latent risk.
- N2. Two queries do not bind `portfolio_id`: the retention `DELETE ... captured_at < X`, and the
  digest `_portfolios` GROUP BY. With the old `captured_at` index dropped they fall back to scans
  (PostgreSQL 17 has no skip scan). That is fine at the current sizes, but B7 (batched purge with time
  indexes) should re-check it against B8 growth numbers. If snapshots grow, add back a standalone
  `(captured_at)` index there; do not add it now.
- N3. The paper-trade row rate grows by up to N sets (skip rows included). Feed this into B8
  (`docs/reports/db-growth.md`) as rows/day per set.
- N4. Add the B15 migration and its "stop scanner, fresh dump before any downgrade" note to the U4
  runbook / `migration-plan.md` gate list (today the plan names only B7 and B12).

## Re-review

Points 1-3 only. Expect one short round.
