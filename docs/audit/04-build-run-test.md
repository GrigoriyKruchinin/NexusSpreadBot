# 04 - Build, Run, Test (verified)

Audit date: 2026-10-23, branch `chore/agent-pipeline-adoption`. Raw outputs: `docs/audit/evidence/`.

## Verified commands

| Command | Result | Evidence |
|---|---|---|
| `uv sync` | OK ("Resolved 88 packages", "Audited 86 packages") | `uv-sync.txt` |
| `make lint` (ruff format --check + ruff check on `src tests`) | OK, rc=0: 120 files formatted, all checks passed | `make-lint.txt` |
| `make typecheck` (`mypy src tests`, strict + pydantic plugin) | OK, rc=0: no issues in 126 source files | `make-typecheck.txt` |
| `make test` (`pytest -q -m "not integration"`) | OK, rc=0: 481 passed, 12 deselected, ~15 s | `make-test.txt` |
| `make test-cov` | OK, rc=0: 481 passed, TOTAL 89% (branch coverage on) | `make-test-cov.txt` |
| `uv run pytest -m integration` | 12 passed (see WARNING below) | `pytest-integration.txt` |
| `docker compose -f docker-compose.local.yml config` | OK, rc=0, no stderr; output not stored (contains env values) | `compose-config-stderr.txt` |

Nothing failed. `make check` = lint + typecheck + test, all three green.

**Note (2026-10-24):** the `docker compose ... config` row above is no longer a valid method. Since
2026-10-23 this command is denied (it expands `.env`; key-leak incident, CLAUDE.md rule 4). Do not re-run it;
compose is checked by YAML parsing (`tests/unit/test_compose.py`). The evidence file is kept as it was.
The integration hazard above was closed: integration tests run only against `nexus_test` (R-01, CI).

## WARNING: integration run was destructive to the live local DB

`tests/integration/conftest.py` (`sessions` fixture) runs `TRUNCATE ... RESTART IDENTITY CASCADE`
on 11 tables (alert_log, paper_trades, spread_snapshots, market_pairs, exchange_health, ...), after
`alembic upgrade head`. It targets whatever `DatabaseSettings()` resolves from env/.env.
In this environment that resolved to `localhost:5432`, db `nexus`, which is the published port of the
running `nexus-local-postgres-1` container (the local stack was up for 3 h). So running
`pytest -m integration` for this audit most likely wiped paper-trading/snapshot data in the
local stack's database. This is a defect in the test design: no guard that the DB is a dedicated
test DB (no `_test` name check, no separate DB). Recommendation: require a distinct
`POSTGRES_DB` (e.g. `nexus_test`) or refuse when the name is `nexus`. (The audit brief said not to
start compose; the stack was already running and I did not start it, but I should have checked
the conftest before running integration. Disclosed for the owner to assess data loss.)

## How to run in Docker (as documented in README.md / Makefile)

- `make up-local` = `docker compose -f docker-compose.local.yml up -d --build`; `make ps-local`
  (all services should be healthy); `make logs s=scanner`; `make down-local`; `make migrate`.
- Compose services (from `config`): postgres (postgres:17-alpine), redis (redis:7-alpine),
  migrator, scanner, beat, worker-alerts, worker-maintenance. Image `nexus-spread-bot:local`
  built from `Dockerfile` (multi-stage builder/runtime, `USER nexus`, `CMD ["nexus","--help"]`).
  Postgres, redis, scanner, beat and workers define healthchecks; migrator does not
  (one-shot). Named volumes: `postgres-data`, `redis-data`.
- Observed state: 6 long-running containers (scanner, beat, worker-alerts, worker-maintenance,
  redis, postgres) were Up 3 hours and (healthy) via `docker ps`. Image build itself
  (`make up-local`) was NOT re-run: not verified.
- Postgres is published on 127.0.0.1:5432 (localhost only), which is what makes the
  integration-test hazard above reachable from the host.
- `.env.example` exists; `.env` required for compose (contents not read).

## Not verified / gaps

- Docker image build and fresh `up` from scratch: not run (restricted by the brief).
- No CI: `.github/workflows` absent. Only `.pre-commit-config.yaml` (hooks: end-of-file-fixer,
  trailing-whitespace, check-yaml, check-toml, check-added-large-files, detect-private-key, local
  ruff-format, ruff-check, mypy). Pre-commit hooks were not executed.
- Integration tests skip silently (`pytest.skip`) when the DB is not configured/reachable, so a
  green `make test-integration` without a DB would mean "skipped", not "verified".
- `make test-integration` does not start the stack; README says run `make up-local` first.
