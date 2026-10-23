# A5c — DB roles and test role (R-09, S-01, S-02)

- id: A5c (migration-plan §A)
- stage: Track 0 (base)
- owner: devops + backend-lead
- reviewers: security, tech-lead
- complexity: medium (grants, default privileges, service wiring, migration ownership)
- depends_on: A1 (done); A5a consumes `nexus_ro` and `nexus_test_owner` from here
- status: todo
- **U4 gate: touches the live DB (role creation, grants, ownership, app credentials switch). User OK is required before execution; take an A5a backup first if the drill is already available. No `docker compose down -v`.**

## Goal
Replace the all-powerful DB credential in app services with least-privilege roles, and add a test
role that physically cannot reach live data.

## Context docs
`docs/architecture/target.md` §10.1 (grant table), `docs/audit/security-review-architecture.md`
(S-01, S-02), `docs/audit/07*` (INF-08), CLAUDE.md hard rule 5, risk R-01.

## Acceptance criteria
1. Roles exist per target.md §10.1: `nexus_migrator` (owner/DDL, `migrator` container only),
   `nexus_app` (DML + sequence USAGE, `NOSUPERUSER NOCREATEDB NOCREATEROLE`, not owner),
   `nexus_ro` (SELECT + `ALTER DEFAULT PRIVILEGES` for future tables), `nexus_test_owner`
   (owner of `nexus_test`, `CONNECT` on `nexus` revoked).
2. Role creation and grants are idempotent scripts or Alembic steps; migrations set
   `ALTER DEFAULT PRIVILEGES` so new tables are covered.
3. SQL/integration check (run on `nexus_test` only): as `nexus_app`, `TRUNCATE`, `DROP TABLE`,
   `CREATE TABLE` in `public` all fail with permission errors; DML on app tables works.
4. Check that the bootstrap superuser variables are absent from the env of scanner, worker-alerts,
   worker-maintenance (compose config test or script).
5. Check that `nexus_test_owner` cannot connect to `nexus` (connection refused by privilege) and can
   fully use `nexus_test`; integration tests and CI switch to this role; R-01 name guard stays.
6. `statement_timeout` / `lock_timeout` set per role via `ALTER ROLE ... SET` (server half of B5).
7. Passwords come from secret files/env following A5b conventions; none in git, logs or this card.
8. Per-service split (`nexus_scanner`, `nexus_alerts`, `nexus_maint`) noted as a trigger for VPS /
   Stage 2, not done here.
9. `make check` not worse than baseline; `make test-integration` green only after user OK.

## Out of scope
Per-service roles, Redis ACL users, Stage 2 executor role, Docker hardening (A5d), backups (A5a).

## Files likely touched
`docker/postgres/init/*.sql` (or equivalent), `docker-compose.local.yml`, `alembic/` (grants),
`src/nexus/config.py`, `tests/integration/` (role checks, conftest), `.env.example`, `.github/workflows/ci.yml`, `todo.md`.

## Risks
Switching the app to `nexus_app` can break existing code that assumes ownership (migrations at
startup, `TRUNCATE` in maintenance purges): audit purge paths first (B7 uses batched `DELETE`).
Ownership transfer of existing tables is a destructive-adjacent op on live data: backup first.
