# 05 - Quality Baseline (for the quality ratchet)

Measured 2026-10-23 on branch `chore/agent-pipeline-adoption`. Raw: `docs/audit/evidence/`.
Tooling: Python 3.12.12, pytest 9, ruff, mypy (strict), pytest-cov (branch).

## Headline numbers

| Metric | Value |
|---|---|
| Unit tests | 481 passed, 0 failed, 0 skipped, 12 deselected (integration), ~15 s |
| Integration tests | 12 passed, 0 skipped (needed live Postgres; see 04 warning) |
| Coverage (unit, branch) | **89%** total: 4386 stmts, 444 missed, 862 branches, 68 partial |
| ruff format --check | 0 issues (120 files) |
| ruff check | 0 errors (rule sets E W F I B UP N S ASYNC RUF ANN SIM PT C4 DTZ T20 RET PIE TID PERF) |
| mypy --strict | 0 errors in 126 files (+ pydantic plugin, warn_unreachable) |
| Python LOC (wc -l) | src 9,436; src+tests 15,950 (test:code ~0.7:1) |
| Functions in src (ast) | 440; longest: `engine/estimator.py::evaluate` 172 lines |

Ratchet proposal: do not allow coverage below 89% total, tests below 481 passing,
ruff/mypy above 0. No `--cov-fail-under` is configured today (pyproject has none), so the ratchet is
not enforced by tooling; no CI either.

## Flakiness signs

3 additional unit runs (two with `-p no:randomly`, one with `--durations`): 481 passed each time,
14.3-14.6 s. No flaky signs. pytest-randomly/xdist are not installed, so order randomization is
untested. Slowest test: `test_ccxt_adapters.py::test_timeout_maps_to_unavailable` 2.0 s; next
ones <0.35 s. Warning: integration tests share one DB and TRUNCATE it (not parallel-safe).

## Coverage by package (derived from term-missing report; 41 files at 100% are omitted from the report)

Files below 100% (cover %): 
- adapters/cex: binance_public 97, bitget 86, ccxt_base 95
- config: base 94, groups 99, roles 98
- domain: clock 88, digest 95, quarantine 90
- engine: candidates 95, depth 97
- infra: redis_store 93
- notifications: digest 95, formatting 96
- scanner: service 91 (592 stmts, 44 missed), paper 87, quarantine 85, streams 95, health 98
- simulation: portfolio 98
- log 96

Weak spots (the real gaps):
- `cli.py` 0% (55 stmts), `interfaces/dex.py` 0% (18 stmts, interface stub)
- `persistence/repositories.py` 31% in unit run (175 of 266 missed; covered only by integration tests,
  which are excluded from the coverage run)
- `persistence/db.py` 53%, `container.py` 46% (composition root), `workers/tasks.py` 62%
Fully covered (100%, not listed): the rest, including most of `engine/` (estimator, fees, transfer)
and `notifications/`. Estimator/fee math was therefore all hit by unit tests.

## Complexity / duplication

No radon, xenon, vulture, pylint, jscpd, bandit or pip-audit installed or configured; not measured.
Ad-hoc ast scan only: largest functions `engine/estimator.py::evaluate` 172 lines,
`container.py::scanner_scope` 95, migration `upgrade` 94, `persistence/repositories.py::_paper` 93,
`engine/transfer.py::select_transfer_route` 78. `scanner/service.py` is 592 statements in one module
(candidate for splitting). Ruff does not enable C90 (mccabe) or PLR rules, so complexity is unchecked.

## Config observations

- pytest: `--strict-markers --strict-config`, asyncio auto mode. Coverage `source=src/nexus`, branch on.
- Missing guard rails: no `fail_under`, no complexity lint, no dependency/vuln scan, no CI.
