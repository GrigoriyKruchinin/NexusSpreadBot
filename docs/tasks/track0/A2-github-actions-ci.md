# A2 — GitHub Actions CI (R-05)

- id: A2 (migration-plan §A; todo.md Track 0 R-05)
- stage: Track 0 (base)
- owner: devops
- reviewers: security (workflow permissions, secrets, pinned actions), tech-lead (gates vs baseline)
- complexity: medium (several jobs, service containers, test-DB safety)
- depends_on: A1 (done, 3d5441f), B1 (so CI runs the final default config)
- status: todo

## Goal
Every push/PR to `main` and working branches runs lint, mypy, unit tests with a coverage floor,
integration tests against a throwaway `nexus_test` service container, a secret scan, and a Docker
image build, so nothing merges without green CI.

## Context docs
`docs/audit/04*`, `docs/audit/05*` (baseline), `docs/architecture/migration-plan.md` (ordering rule 2),
`.claude/skills/secrets-scan/SKILL.md`, CLAUDE.md hard rules 4-6, risk R-05.

## Scope
- `.github/workflows/ci.yml` with jobs: `lint` (`make lint`), `typecheck` (`make typecheck`),
  `unit` (`make test-cov` with `--cov-fail-under=89`, floor also set in `pyproject.toml`
  `[tool.coverage.report] fail_under = 89`), `integration`, `secret-scan`, `docker-build`.
- `integration`: Postgres and Redis as GitHub service containers; `POSTGRES_DB=nexus_test` set in the
  job env only; run `make test-integration`; the R-01 guard must stay active (job fails if DB name is
  not `nexus_test`). Fake credentials only, defined inline in the workflow, never repo secrets.
- `secret-scan`: gitleaks (or equivalent OSS) over full history on PR; no secrets uploaded or echoed.
- `docker-build`: `docker build` of the existing Dockerfile, no push, no registry login.
- uv via pinned `astral-sh/setup-uv` + `uv sync --frozen`; cache keyed on `uv.lock`.
- Hardening: `permissions: contents: read`, actions pinned to a major tag or SHA, concurrency
  cancel-in-progress, job timeouts, no `pull_request_target`.
- Short Russian guide note for the user on enabling branch protection (user action, U4).

## Out of scope
Deploy/CD, image push, release tagging, pip-audit and dependency bumps (A3/R-06), import-linter
(C8), dashboards, branch-protection settings (user does it via guide), any use of real exchange keys
or live DB.

## Files likely touched
`.github/workflows/ci.yml`, `pyproject.toml` (coverage floor), `Makefile` (optional `ci` targets),
`docs/guides/ci-branch-protection.md` (new, Russian), `todo.md` (R-05 tick), `docs/pipeline/STATE.md`.

## Acceptance criteria
1. First workflow run on the branch is green with all six jobs; run link recorded in the card.
2. Baseline held in CI output: >= 481 unit tests (plus B1 additions), branch coverage >= 89 %,
   ruff 0, mypy --strict 0.
3. Negative checks demonstrated once on a throwaway branch (not merged): coverage below 89 % fails
   `unit`; a planted fake token fails `secret-scan`; `POSTGRES_DB` != `nexus_test` fails
   `integration`. Results noted in the card.
4. Integration job connects only to the service container (host `localhost`, DB `nexus_test`); no
   reference to the live `nexus` DB, no `docker compose down -v`, no `system prune`.
5. `grep -r "secrets\." .github` shows no repo secrets required; workflow has least-privilege
   `permissions`; security reviewer signs off.
6. `make check` locally unchanged; `todo.md` R-05 ticked in the same commit as the verified green
   run; Conventional Commit `ci: add GitHub Actions pipeline (R-05)`.

## Risks
- Integration tests were never run in CI; they may expose environment-specific failures (Alembic
  migrations, Redis) that need small test fixes, which stay within this card only if tiny.
- Pushing the branch to trigger CI needs user consent for push (hard rule 6; working branch only,
  never `main`). The orchestrator must ask via U4 if not already granted.
- Secret scan over history may flag false positives (docs examples); use a minimal allowlist file,
  reviewed by security.
- Coverage floor of 89 % leaves no margin; flaky coverage on async paths could block merges.
