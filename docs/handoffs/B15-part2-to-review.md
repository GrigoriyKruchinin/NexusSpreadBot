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
