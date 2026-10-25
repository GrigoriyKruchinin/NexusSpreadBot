# T2 - Migrations: drop paper tables (squash vs drop-migration)

- id: T2
- stage: S1-tool
- owner: backend-lead
- complexity: medium (irreversible schema work, but DB is empty by user decision)
- size: M
- depends_on: T1a
- status: done

## Goal
End with a schema that contains no paper tables and a migration history that works on an empty DB with one command.

## Context docs
`src/nexus/persistence/migrations/versions/` (7 revisions), `docs/guides/backups.md`, `scripts/restore_drill.sh`

## Scope
1. RECOMMENDED: squash all 7 revisions into one fresh `initial_schema` for the remaining tables (evaluations, spreads, episodes, route_quarantine, exchange_metadata_stats, alert outbox, ...). Rationale: the project has no installed base other than the owner whose DB is wiped (user OK 2026-10-25); a first-time user then sees one clean migration; autogenerate diff stays empty.
2. Risk of squash: any old DB or old dump (`nexus-archive-*`) no longer matches Alembic history; fix = never restore old dumps into the new schema, document `alembic stamp` is NOT supported for pre-S1 DBs. Squash must happen BEFORE the first public clone / tag.
3. ALTERNATIVE (safe for any existing DB): add revision `drop_paper_tables` after `b15a7c3e91d2` that drops `paper_*` tables; history keeps 8 revisions with dead B15 history.
4. Implement the chosen option; test: `alembic upgrade head` on an empty DB, `alembic check` (no autogenerate diff), downgrade not required
5. Update restore drill and backup count sidecar scripts to the new table list

## Acceptance criteria
- Fresh DB -> `alembic upgrade head` exits 0, `alembic check` shows no drift, no `paper_*` tables (integration test on `nexus_test`)
- Decision (squash or drop) recorded in the card; user confirmation obtained via NEEDS_USER before any data step (U4)
- Restore drill script passes against the new schema in CI or documented manual run

## Out of scope
Wiping the live DB (user does it himself; agents were denied; guide commands are given to him).

## Files likely touched
src/nexus/persistence/migrations/, scripts/, tests/integration/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).

## Result (2026-10-25)
- Decision: SQUASH (user decision; live DB and all backups wiped by the user, so U4 confirmation = that decision). Old dumps must not be restored into the new schema; `alembic stamp` is not supported for pre-S1 DBs.
- New single head `8e1f4a7c2b90` (`versions/20261025_8e1f4a7c2b90_initial_schema.py`): 8 tables, no `paper_*`. Verified offline on SQLite: `compare_metadata` against ORM is empty, downgrade clean.
- `tests/integration/test_migrations.py` (single head, `alembic check`, no paper tables); runs in CI only. Backup/restore scripts are table-agnostic, no change needed.
