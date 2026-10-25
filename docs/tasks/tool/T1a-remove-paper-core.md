# T1a - Remove paper portfolios and GO report: code, config, make target

- id: T1a
- stage: S1-tool
- owner: backend-lead
- complexity: high (wide cut through scanner/container/config with 1041 tests to keep green)
- size: L
- depends_on: T0
- status: todo

## Goal
Delete the paper-trading and GO-report machinery completely while the scanner, alerts and spread/episode persistence keep working.

## Context docs
`docs/tasks/m2/B15-shadow-paper-portfolios.md` (what B15 added), `docs/reports/go-no-go.md`, `docs/architecture/migration-plan.md`

## Scope
1. Delete `src/nexus/simulation/` (portfolio.py), `src/nexus/scanner/paper.py`, `src/nexus/scanner/capstats.py` (cap stats are paper-only; confirm by grep before deleting), `src/nexus/reports/` (go_*.py), `src/nexus/config/venue_sets.py` if only used by paper
2. Unhook paper from `scanner/service.py` (sweep must not call paper hooks), `container.py`, `config/groups.py` (`[paper]`, `PAPER_VENUE_SETS`), `config/provenance.py`, `config/roles.py`, `cli.py` (go-report command)
3. Remove `[paper]` from `config/nexus.toml`; remove `make go-report` and its mention in `help`
4. Remove paper domain events/repository interfaces/ORM models (`persistence/models.py`, `repositories.py`, `interfaces/repositories.py`) - ORM models removed together with T2 so Alembic autogenerate stays consistent
5. Delete tests: `tests/unit/scanner/test_paper_sets.py`, `tests/unit/test_container_paper.py`, `tests/integration/test_paper_portfolios.py`, `tests/integration/test_migration_b15.py`, go-report tests; trim paper cases in settings/config/scanner tests
6. Remove dead references in `scripts/` (backup counts of paper tables, `scripts/sql/`) and CI

## Acceptance criteria
- `grep -rniE 'paper|portfolio|go_report|go-report|venue_sets' src tests scripts Makefile config .github` returns only intentional hits (documented in the card)
- `make check` green; unit test count drops only by deleted paper tests; ruff 0, mypy --strict 0; branch coverage >= 89 % floor (record new baseline in the card, tick ratchet in CLAUDE.md proposal T12)
- Scanner sweep still persists spreads, evaluations and episodes (existing tests prove it)
- Coverage of the remaining code does not drop because paper tests are gone: any lost coverage on kept modules is re-covered

## Out of scope
Digest/watchdog D-08 (T1b); migrations (T2); docs (T12).

## Files likely touched
src/nexus/{simulation,scanner,reports,config,container.py,cli.py,persistence,interfaces,domain}, tests/, Makefile, config/nexus.toml, scripts/, .github/workflows/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
