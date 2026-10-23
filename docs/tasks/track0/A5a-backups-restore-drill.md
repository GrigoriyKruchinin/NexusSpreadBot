# A5a — Postgres backups with verified restore drill (R-09, S-03, S-12)

- id: A5a (migration-plan §A)
- stage: Track 0 (base)
- owner: devops
- reviewers: security, tech-lead
- complexity: medium (credentials handling, retention, restore verification)
- depends_on: A1 (done); A5c for the `nexus_ro` and `nexus_test_owner` roles (may bootstrap minimal versions of both if A5c is not yet done, same grants as target.md §10.1)
- status: DONE (2026-10-23): roles bootstrapped, backup + restore drill PASSED, see docs/reports/restore-drill.md. Pending: security/tech-lead review
- **U4 gate: touches the live DB and Docker. User OK is required before execution (backups read the `nexus` DB, restore drill creates/overwrites `nexus_test`). Never restore into `nexus`.**

## Goal
Daily `pg_dump` of `nexus` with retention, plus one verified restore into `nexus_test`, so schema
migrations (B7/B8) have a proven safety net.

## Context docs
`docs/audit/security-review-architecture.md` (S-03, S-12), `docs/architecture/target.md` §10.1,
`docs/architecture/migration-plan.md` (ordering rule 4), CLAUDE.md hard rules 4, 5, 7.

## Acceptance criteria
1. Dump runs as `nexus_ro` (SELECT only); password via `.pgpass` or `*_FILE`, never a CLI arg or
   inline in compose; no secret in logs or `docker inspect` output.
2. Backup dir is outside the repo and outside any compose data volume; listed in `.gitignore` and
   `.dockerignore`; directory 0700, files 0600 (checked by script).
3. Retention 7 daily + 4 weekly, pruning tested on a temp dir with fake dated files.
4. If copied off-host the dump is encrypted (`age` or `gpg`); documented, off-host copy itself is
   optional and needs user OK.
5. **Restore drill:** latest dump restored into `nexus_test` as `nexus_test_owner` (never `nexus`);
   script refuses any target DB name other than `nexus_test`; row counts of key tables compared with
   the source and recorded in `docs/reports/restore-drill.md`; drill result is the gate for B7/B8.
6. External heartbeat: free service only; ping URL is a secret (`SecretStr`, scrubbed, from file/env,
   never committed); a missed backup raises an alert. Paid service needs user approval.
7. Russian guide `docs/guides/backups.md` for the user (how to run, where files are, how to restore).
8. No `docker compose down -v`, no `system prune`; `make check` not worse than baseline.

## Out of scope
Per-service roles beyond `nexus_ro`/`nexus_test_owner` (A5c), WAL/PITR, off-host storage setup,
VPS, Alembic migrations (B7).

## Files likely touched
`scripts/backup.sh`, `scripts/restore_drill.sh` (or Python equivalent), `Makefile`, compose file
(backup job/cron), `.gitignore`, `.dockerignore`, `docs/guides/backups.md`,
`docs/reports/restore-drill.md`, `todo.md`.

## Risks
Dump while writes continue is consistent (`pg_dump` snapshot) but large tables slow it; the restore
into `nexus_test` destroys test data (acceptable, test DB only). Credentials leakage via process list.
