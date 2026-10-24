# Tech-lead review — B15 part 2 (GO report generator), round 1

- Date: 2026-10-24
- Diff: d81811b (retention thinning), 2c82c7f (`src/nexus/reports/*`, unit tests, fixture, sample, Makefile), 8c1cc16 (integration test)
- Card: `docs/tasks/m2/B15-shadow-paper-portfolios.md` (Scope 5, AC 5-6, F2). Handoff: `docs/handoffs/B15-part2-to-review.md`
- Not run (by instruction, soak running): integration tests, docker, any DB connection.

## Verdict: RETURN (round 1 of max 3)

Checks: `make check` green — 1106 unit tests passed (baseline 1028), ruff 0, mypy --strict 0;
`make test-cov` 91.90 % branch-inclusive total (floor 89 %). `nexus.reports` unit coverage 94 %
(`go_repository.py` 32 %, I/O only, covered by the CI integration test).

What is good: clean split — `go_math` is pure (no DB/clock/I/O), the repository only builds plain
dataclasses, `go_build`/`go_verdict`/`go_render` are pure assembly; Decimal throughout; unknown
`--go-set` and empty DB render a "no verdict" report instead of crashing; engine is disposed in
`finally`; the sample is pinned by `test_committed_sample_matches_the_fixture`. The integration test
cannot hit live `nexus`: `tests/integration/conftest.py` refuses any DB other than the test DB
(`assert_test_database`, exit 2) before migration/TRUNCATE. The retention change is logically
correct: the latest set of every portfolio has no newer row and survives; a set is compared only
with newer rows of the SAME portfolio and SAME UTC day (`timezone('UTC', timestamptz)` makes the day
independent of the session TZ); rows of one set share `captured_at` and are never split; no
over-delete path found.

## Required fixes

1. **Read-only access is not enforced, and `nexus_ro` cannot be used as documented.**
   `go_report.generate` builds `DatabaseSettings()` from `POSTGRES_*`/`.env`, i.e. by default the app
   role `nexus` (owner, full write/DDL). `nexus_ro` has no password and logs in only over the
   container unix socket (`scripts/sql/bootstrap_backup_roles.sql`), so `make go-report` on the host
   cannot use it at all. The code issues SELECTs only, but nothing guarantees that against the live
   DB during the soak. Fix: create the report engine with
   `connect_args={"server_settings": {"default_transaction_read_only": "on", "statement_timeout": "<e.g. 300000>", "lock_timeout": "<e.g. 5000>"}}`
   (e.g. a `read_only=True` option on `create_engine`), add a unit test asserting the options, and
   correct the docstrings (`go_repository.py`, `go_report.py`), Makefile help and handoff: state the
   real role and that the session is read-only by server setting. (Conventions: every network call
   has a timeout — the report session has none today.)
2. **Retention EXISTS is not index-bounded for the last set of each day** (`persistence/repositories.py`
   `RetentionRepository.purge`). For the surviving last-of-day set the subquery finds no same-day row,
   so it walks EVERY newer row of the portfolio via `ix_paper_balance_snapshots_portfolio_captured_at`
   (date_trunc predicate is a filter, not an index bound). This repeats each purge for every old
   kept day x holdings rows x 4 portfolios, growing with the soak, on the live path. Fix (keeps the
   semantics): add `newer.captured_at < PaperBalanceSnapshotRow.captured_at + timedelta(days=1)`
   (same UTC day implies < 24 h later), so the range scan stops within one day.
3. **Retention test does not cover behaviour across portfolios** (`tests/integration/test_paper_portfolios.py::test_since_survives_snapshot_retention`
   uses only `all`). Add a second portfolio with sets on the same old UTC day and on a different
   day; assert each portfolio keeps its own last set per day and its own latest set (the
   `newer.portfolio_id ==` correlation is what protects the other sets — it must be under test).
   Include a set just before the UTC midnight and one just after to pin the day boundary.

## Should fix (this round if cheap, otherwise next)

4. AC 5 integration test is minimal: add (a) rows of an EARLIER run of the same set are excluded and
   the run is listed in `previous_runs`; (b) rows at/after `until` are excluded; (c) several snapshot
   sets inside one hour -> one kept (`pick_hourly` on real rows); (d) `fee_observations` returns the
   hand-computed avg/min/max per venue (buy+sell legs merged); (e) skips and cap hours per set.
5. CLI robustness (`go_report.py`): `--until` should use an argparse `type=` so a bad date gives a
   usage error, not a traceback; `parse_ops` should reject non-object entries with a clear message;
   consider exit code 2 when `--go-set` has no run (today exit 0 with "no verdict" is easy to miss in
   automation).

## Notes (no action required)

- The CLI wires the engine itself rather than via `container.py`; acceptable for a one-shot entry point.
- `fee_observations` uses `ix_spread_evaluations_status_evaluated_at`; profitable rows are never purged, so
  the window is complete. Limits (profitable rows only, flat 0.3 % liquidation) are disclosed — semantics
  are for quant-analyst.
- First real run must be done by the user (not agents) and compared with a manual SQL sum, as the
  handoff says.

## NEEDS_USER
none
