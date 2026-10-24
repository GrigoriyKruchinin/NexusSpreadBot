# B15 part 2 (GO report generator) -> quant-analyst + tech-lead review

Spec: `docs/quant/b15-review-and-report-spec.md` Part B + Round 2. Card: `docs/tasks/m2/B15-shadow-paper-portfolios.md`.
Run: `make go-report` (app DB role from `POSTGRES_*`; the session is read-only by server setting `default_transaction_read_only=on` plus statement/lock timeouts; `nexus_ro` cannot be used from the host). Sample: `docs/quant/samples/go-report-sample.md` (synthetic, from `tests/go_fixture.py`).

## Spec point -> code
- Query layer (latest run per set, in-run rows only, hourly-thinned snapshots, F2 fee observations): `src/nexus/reports/go_repository.py`
- Pure math (windows, tuning/holdout split, equity, MTM, liquidation reserve, drawdown, std, cap stats, B4 fields): `go_math.py`
- Assembly (B5 stability periods, B6 concentration, B7 venue-access value on the common window, fee table): `go_build.py`
- Verdict and gates (35 % / 15 % tax, GO / GO-HOLD, refutation lines, open legal gates): `go_verdict.py`
- Markdown output: `go_render.py`; CLI entry: `go_report.py`
- F2 fee disclosure and per-set `since` (also earlier runs listed, never mixed): rendered in the report notes and per-set tables.
- Tests: `tests/unit/reports/`; integration (AC 5, CI only, `nexus_test`): `tests/integration/test_go_repository.py`

## Deviations
- F2: no fee-table snapshot at run start; the report discloses the fee source and lists observed effective rates from `spread_evaluations` (profitable rows only). Reason: no schema change during the running soak.
- Integration test was written but not run locally (soak running; CI only).

## d81811b retention change
Old paper snapshot sets are thinned to one per UTC day instead of deleted, so the report can still build daily equity (drawdown, std, stability periods) beyond the full-resolution retention window. Deleting them would have removed the equity history the report needs.

## Known limits
- Fee observations only cover profitable evaluations, effective % derived from USD fee / quote amount.
- Liquidation reserve is a flat 0.3 % (no per-venue spread stored).
- B14-style approximation for ex-top-2 filters inside one set.
- Report not yet run against real soak data; first real run should compare the per-set sums with a manual SQL check.

## Round 1 fixes (backend-lead, 2026-10-24)

| Review point | Status | Commit |
|---|---|---|
| tech-lead 2 (retention EXISTS bounded to same UTC day) | fixed | d571f8b |
| tech-lead 3 (two portfolios, UTC midnight boundary test) | fixed (integration test, CI only, not run locally) | d571f8b |
| tech-lead 1 (read-only session: `default_transaction_read_only=on`, statement/lock timeouts; unit test; docstrings, Makefile, handoff) | fixed | 756dba7 |
| tech-lead 5 (`--until` argparse `type=`, `parse_ops` errors, exit 2 when go-set has no run or ops file is bad) | fixed | 756dba7 |
| quant 1 (liquidation reserve = `end.non_usdt * pct` on every window incl. periods, ex-top-2; test; sample regenerated) | fixed | b9aa8ba |
| quant 4 (refute line with reserve at 2x), quant 2 (MTM residual next to ex-top-2-coins, flag at > 25 %), quant 7 (`membership_missing` > 0 flag) | fixed | this round's last commit |
| tech-lead 4 (wider AC5 integration test a-e) | DEFERRED: cannot run integration tests locally (soak); needs a CI-verified round | - |
| quant 3 (fees tuning vs holdout split, min/max flag, profitable-only note) | DEFERRED: needs a new repository query by window and a model field; next round | - |
| quant 6 (stale seed price / in-flight at 0 counts) | DEFERRED: needs repository counters | - |
| quant 8 (gate table for every set) | DEFERRED: needs verdict evaluation per context set; next round | - |
| quant 5, 9, 10 | DEFERRED (UF runbook item for regimes; overview holdout days; full-window std label) | - |

Note: ex-top-2 recomputes inherit the holdout `total_liq` (full end-of-window reserve kept; conservative).
