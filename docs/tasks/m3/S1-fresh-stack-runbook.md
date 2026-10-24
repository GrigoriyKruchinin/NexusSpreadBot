# S1 - fresh-stack runbook (steps 3.1 and 3.2 of docs/guides/soak-fresh-stack.md)

Status: PLAN ONLY (nothing executed). Author: devops, 2026-10-24. Each state-changing command needs the user's
approval at the orchestrator (permission prompt). No secrets are read or printed in any step.

## 1. Current state (read-only checks, 2026-10-24)

- Compose project `nexus-local`. All 7 containers exist and are stopped: scanner, beat (Exited 0), worker-alerts,
  worker-maintenance (Exited 137), migrator, redis, postgres (Exited 0). Stopped ~20 h ago (migrator ~25 h).
- Named volumes (compose `volumes:` has no explicit `name:`, so Docker prefixes the project name):
  - `nexus-local_postgres-data` = live `nexus` Postgres data (mounted at /var/lib/postgresql/data of `postgres`).
  - `nexus-local_redis-data` = Redis AOF/RDB (queues, rate-limit state; not analytics data).
  - plus one anonymous volume (64-hex name), unrelated to compose; leave alone.
- Host dirs: `~/nexus-backups/` (0700) holds only `nexus-20261023T171853Z.dump` (no .counts, no archive/, no
  last_backup.json, no backup.log). `~/nexus-backup-status` does NOT exist yet. `/mnt/c/nexus-backups` does NOT exist yet
  (the copy step creates it if /mnt/c is mounted; otherwise a WARNING and no copy).
- Role `nexus_ro` is needed by backup.sh (`pg_dump -U nexus_ro`). It was created in the old DB on 23.10 via
  `scripts/sql/bootstrap_backup_roles.sql`, so it exists in the old volume. It will NOT exist in a fresh volume (see 3.2).

## 2. Step 3.1 - archive dump of the OLD DB

### What backup-archive needs
`make backup-archive` runs `BACKUP_ARCHIVE=1 scripts/backup.sh`. The script calls
`docker compose -f docker-compose.local.yml exec -T postgres ...` internally (psql counts, pg_dump, pg_restore --list).
This is fine: the permission rule matches the typed command (`make backup-archive`, ask-listed), not the script's inner
calls. Only the `postgres` container is required. Not needed: redis, migrator, scanner, workers, beat, image build.
Writes: `~/nexus-backups/archive/nexus-archive-<stamp>.dump` + `.counts` (0600, dir 0700), then the off-machine copy to
`/mnt/c/nexus-backups` (sha256 verified, then `backup_prune.sh` on the copy dir - archive names do not match the daily
regex, so they are never pruned). No `last_backup.json` and no heartbeat in archive mode (by design).

### Exact command list (run from /home/grisha/projects/NexusSpreadBot)
1. Pre-check (allow-listed, read-only): `docker compose -f docker-compose.local.yml ps -a` (or `ps`) - expect all Exited.
2. `docker compose -f docker-compose.local.yml up -d postgres`  [NOT allow-listed -> prompts the user; needs approval]
   - Starts ONLY postgres (no depends_on, no `--build`, so the app image is not rebuilt, migrator does not run).
   - Compose still interpolates the whole file, so `.env` must define POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN,
     TELEGRAM_CHAT_ID (the user filled them). If it errors with "must be set", stop and ask the user (do NOT read .env).
   - It publishes 127.0.0.1:5432 only. It mounts the OLD volume `nexus-local_postgres-data` (still the compose name).
3. Wait for healthy (allow-listed): `docker compose -f docker-compose.local.yml ps postgres` until STATUS shows `(healthy)`
   (healthcheck 5 s x 20 retries, so up to ~100 s; after an unclean stop it may run WAL recovery first).
4. `make backup-archive`  [ask-listed -> prompts]. Expect log lines: "dumping nexus as nexus_ro", "wrote
   nexus-archive-<stamp>.dump (<N> bytes)", "copied ... (checksums verified)", "archive dump written (never pruned)".
5. Verify (read-only, orchestrator):
   - `ls -la ~/nexus-backups/archive/` -> one `.dump` and one `.counts`, both -rw-------, dump size clearly > 0.
   - `cat ~/nexus-backups/archive/nexus-archive-*.counts` -> lines `table|rows_before|rows_after`; rows_before == rows_after
     for the quiet tables (scanner is stopped, so ALL tables must match); record the key tables' counts in the ops log.
   - `ls -la /mnt/c/nexus-backups/` -> same two files. Optionally `sha256sum` both copies and compare (script already did).
   - Absence of "WARNING: off-machine copy of the archive NOT made" in the console output. Success = exit code 0 and no
     "ERROR". `last_backup.json` and `backup.log` are NOT produced by archive mode (backup.log only exists once cron's
     `make backup` ran, and the dir currently has none), so do not use them as the success signal here.
   - Optional deeper check (script already ran `pg_restore --list` on the dump): restore drill is out of scope for 3.1.
6. Stop postgres again: `docker compose -f docker-compose.local.yml stop postgres`  [not allow-listed -> prompts].
   Do NOT use `down` (would remove containers/network; harmless for volumes but unnecessary). Then
   `docker compose -f docker-compose.local.yml ps -a` shows postgres Exited (0). `restart: unless-stopped` means an
   explicitly stopped container is not restarted by the Docker daemon after a WSL/Docker restart.

### Settings lists (.claude/settings.json)
- allow: `docker compose -f docker-compose.local.yml ps:*`, `... logs:*`.
- ask: `make backup-archive`, `make backup`, `make up-local`, `make down-local`, `make migrate`, `make restore-drill`.
- no rule (default prompt): `docker compose -f docker-compose.local.yml up -d postgres`, `... stop postgres`.
- deny: `... exec`, `... run`, `down -v`, `--volumes`, `docker volume rm/prune`, `docker inspect`, `docker run`,
  `docker-compose`, `docker compose -p/--file/--project-name/--env-file`, `config`. The plan uses none of these directly.
  Do not use `make up-local` for 3.1: it builds and starts everything and runs the migrator on the old DB.

### Risks and abort criteria (3.1)
- Old Postgres fails to come up / stays unhealthy > 3 min or logs "database system was interrupted"/corruption:
  ABORT, stop postgres, do not retry in a loop; the Oct-23 dump in `~/nexus-backups` is the fallback. Report logs
  (`docker compose -f docker-compose.local.yml logs postgres`, allow-listed).
- `role "nexus_ro" does not exist` or permission denied: ABORT (do not create roles via exec - denied). Fallback needs a
  user decision: the user runs the bootstrap SQL manually, or archive as owner is not supported by the script.
- Dump empty / `pg_restore --list` failed / "no tables found": ABORT, nothing was moved into place (`.partial` is removed).
- rows_before != rows_after on any table while the scanner is stopped: unexpected writer; investigate before continuing.
- Off-machine copy WARNING: not fatal to the dump, but the user wanted a copy on C:. Check `/mnt/c` is mounted; re-run is
  safe (creates a second, separately named archive). Do not proceed to 3.2 until at least the local archive is verified.
- Disk space: dump is ~0.5 MB for Oct-23 data, so negligible. Port 5432 clash with a Windows-side Postgres: the `up` errors; abort.
- Never proceed to 3.2 until step 5 checks pass and the user has seen the sizes/counts.

## 3. Step 3.2 - NEW empty Postgres volume, old one untouched

### Does it need a code change? YES (one small compose edit, no Python code)
Without a change, `postgres-data` always resolves to `nexus-local_postgres-data` (the old data). There is no allowed
command to rename/remove it (`volume rm`, `down -v` denied) and `-p`/`--project-name`/`--env-file` are denied. A variable
(`${PG_VOLUME}`) would be resolved from `.env` or the shell, which agents must not touch and which the compose file comment
(line ~166) deliberately avoids. So pin the name in the file (git-tracked, reviewable, revertable).

### Exact diff (NOT applied) in docker-compose.local.yml, bottom `volumes:` block
```diff
 volumes:
-  postgres-data:
+  postgres-data:
+    # Soak 2026-10: fresh DB. The previous data stays in volume "nexus-local_postgres-data" (archived 3.1);
+    # to go back to it, restore this key to empty (`postgres-data:`) or set name: nexus-local_postgres-data.
+    name: nexus-local_postgres-data-soak1
   redis-data:
```
- Docker/compose creates `nexus-local_postgres-data-soak1` automatically on the first `up` that uses it (no `volume create`
  needed; empty, so the postgres image runs initdb with POSTGRES_DB=nexus / POSTGRES_USER=nexus from the .env password).
  IMPORTANT: the password in a fresh volume comes from the CURRENT `.env` POSTGRES_PASSWORD (initdb time). The old volume keeps
  its old password. If the user changed POSTGRES_PASSWORD, switching back to the old volume would then fail auth over TCP
  (the app) while the unix-socket backup path still works. Note for rollback.
- Redis: recommended to keep `redis-data` (it holds only Celery broker/queues, rate-limit and scanner caches; no analytics).
  Stale keys from the 25 h-old stack are harmless but may contain old queued alert tasks; if a clean slate is wanted use the
  same trick: `redis-data: {name: nexus-local_redis-data-soak1}`. Recommendation: fresh redis too (same diff, one more
  line) so the soak starts with no stale queued tasks; the old redis volume stays for rollback. User may prefer keep.
- Backup status dir `~/nexus-backup-status`: absent today; created by `make up-local` (mkdir -m 755). Nothing to switch.
  `~/nexus-backups/` keeps the old daily dump (Oct 23) and the new archive; the first daily `make backup` on the new DB
  will prune per retention, but the archive is never pruned. No change needed. The cron (03:15 `make backup`) will fail on
  the fresh DB until `nexus_ro` exists (see below) - expect a "backup failed" watchdog alert; do not leave it unfixed.
- Test: `tests/unit/test_compose.py` does not mention volume names (grep found none), so `make check` should stay green;
  run it before committing the diff. Docs: update `docs/audit` mentions only if repo-hygiene wants (they describe the audit
  baseline; leave).

### Command sequence (after approval of the diff)
1. Apply the diff (Edit), `make check`, commit `chore(compose): pin fresh postgres volume name for soak` (+ todo tick).
2. Do NOT start anything yet. `docker volume ls --format '{{.Name}}'` still shows only the old volumes (new one appears at 3.3/3.4).
3. Step 3.3 (not in this plan's scope): `make up-local` or `make migrate` creates the new volume implicitly and runs
   `alembic upgrade head` on the empty DB.
4. REQUIRED extra step (gap in the guide): after the new postgres is up, someone must run the role bootstrap, because
   `make restore-drill` / `make backup` rely on `nexus_ro`, `nexus_test_owner`, and the `nexus_test` DB, which only exist in
   the old volume:
   `docker compose -f docker-compose.local.yml exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1' < scripts/sql/bootstrap_backup_roles.sql`
   `exec` is DENIED for agents -> the USER must run this command in their own terminal (or the user adds a reviewed make target
   `bootstrap-roles` that is ask-listed; that is a code change, so propose it separately). Run it after migrations so the
   `GRANT SELECT ON ALL TABLES` covers existing tables (default privileges also cover later ones). Add this as step 3.3b in the guide.

### Rollback to the old volume
- Before 3.4 ever ran: `git revert` the compose commit (or `git checkout -- docker-compose.local.yml`); the old volume is
  untouched and is used again on the next `up`. The empty `-soak1` volume stays as an unused volume (deleting needs a
  user-approved manual `docker volume rm`, deny-listed for agents).
- After the soak ran: stop the stack (`make down-local`, ask-listed; keeps volumes), revert the compose line, `make up-local`.
  Data written during the soak stays in `-soak1` (archive it with `SOURCE_DB`/`make backup-archive` first if wanted).
  Password caveat above applies.

### Risks and abort criteria (3.2)
- Typo in the volume name creates yet another empty volume: verify with `docker volume ls --format '{{.Name}}'` after 3.3 that
  exactly `nexus-local_postgres-data-soak1` was added and the old one is still listed. If the old one is missing: STOP, tell the user.
- Starting the stack before the diff is committed/applied would write into the OLD volume: forbidden; order is diff first.
- Never run `make up-local` while 3.1 postgres is still running on the old volume (the switch would hit a name conflict on the
  container and start the same container pointing to a different volume; always `stop postgres` and confirm Exited first).
  Note: `up` after the compose edit RECREATES the postgres container with the new volume mount (the container is replaced; the
  old container's anonymous layers are discarded, the named old volume is not deleted).
- Cron `make backup` at 03:15 fails on the fresh DB until the bootstrap SQL runs: acceptable for one night, not for a week.

## 4. NEEDS_USER (for the orchestrator to ask)
1. Approve the compose edit with a pinned dated name (recommended) vs. a project rename (more invasive).
2. Redis: fresh volume (recommended, stale queue clean) or keep.
3. Who runs the role bootstrap SQL (exec is denied): the user manually, or add an ask-listed `make bootstrap-roles` target.
