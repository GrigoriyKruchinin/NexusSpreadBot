# Security review — S0 pre-soak gates (S0a + S0b)

- Reviewer: security (read-only)
- Date: 2026-10-23
- Scope: card `docs/tasks/m3/S0-pre-soak-gates.md`; S0a commit 3bb5746 (`docker-compose.local.yml`,
  `scripts/backup.sh`, `scripts/_backup_common.sh`, `Makefile`, `docs/guides/backups.md`); S0b commits
  110fb91, 46456e4 (watchdog, sweep isolation, `[watchdog]` TOML); handoffs S0a/S0b; env-expansion sweep
  after the 2026-10-23 key-leak incident (commit 0698385).
- Method: diff and file reading, grep. Not done (by rule): reading `.env`, `docker compose config/exec/
  run/inspect`, `printenv`, stack start, DB access, running backup scripts.

## Verdict: ACCEPT (with follow-ups)

No Critical/High finding. The follow-ups below are Low/Medium and may be fixed in a follow-up commit
before the fresh-stack soak (S-1 and S-3 recommended before the soak, the rest whenever convenient).

## What was checked and is fine
- **Copy path validation** (`copy_offsite`): absolute path required, `..` rejected, physical path via
  `pwd -P` (symlinked dest resolved before the repo/BACKUP_DIR checks), refuses BACKUP_DIR and the repo,
  creates the dir only if the parent exists and `/mnt/<x>` is a real mountpoint, temp + sha256 + rename,
  never fails the dump. Empty value disables the copy (status `copied=false` -> alert).
- **Prune safety**: `backup_prune.sh` only touches regular files matching the exact
  `nexus-YYYYMMDDTHHMMSSZ.dump|.counts` names (`find -maxdepth 1 -type f`), never the newest dump, strict
  KEEP_* validation. Pointing BACKUP_COPY_DIR at a broad dir cannot delete foreign files.
- **Status file**: fields `finished_at`, `ok`, `dump` (file name only), `copied`; no secrets, no paths;
  atomic temp + rename; 0600 in BACKUP_DIR, 0644 mirror in `~/nexus-backup-status`. Only the mirror dir is
  mounted, read-only, at `/backups`; the 0700 dump dir is not mounted. Reader caps the file at 4 KiB.
- **Restart wrapper**: `sh -c` script contains no secret; env is inherited as before (no new exposure in
  argv/`ps`). Exit 3 -> 0 avoids a signed key-introspection loop (A6 intent preserved).
- **Watchdog Telegram texts**: events carry only `check`, reason code and minutes; Russian text is a fixed
  template, HTML-escaped; no paths, hostnames, URLs or exception text. Logs carry check/reason codes and
  `type(error).__name__` only (no message, so no path/URL leakage).
- **Redis**: broker URL taken via `get_secret_value()` only for the client, never logged; keys
  `nexus:watchdog:<check>` are namespaced, tiny, no TTL by design.
- **A7**: 6 new keys `WATCHDOG_*` in `TOML_ALLOWED`, none secret-like; `backup_status_path` validated
  absolute. `.env.example` unchanged.
- **Tests** are hermetic: sandboxed HOME/BACKUP_DIR/BACKUP_COPY_DIR/BACKUP_STATUS_DIR; `test_compose.py`
  parses YAML, does not call `docker compose config`.
- **Env-expansion sweep (S0 scope)**: no S0 script, Makefile target, guide or handoff tells anyone to run
  `docker compose config`, `docker inspect`, `exec ... env`, `printenv` or to print `.env`.
  `pg_run` uses `compose exec -T postgres pg_dump/psql` (no env output; run by the user's cron, not agents).

## Findings

| # | Severity | Area | Finding | Recommendation |
|---|----------|------|---------|----------------|
| S-1 | Medium | Docs / agent instructions (outside S0 code, found by the sweep) | Open cards instruct an implicit `.env` expansion: `docs/tasks/track0/A5b-redis-auth.md` criterion 5 "(verified in compose config)", `docs/tasks/track0/A5c-db-roles-test-role.md` criterion 4 "compose config test or script". An agent following them would repeat today's incident (deny rules catch only exact prefixes). | Reword both to "verified by parsing `docker-compose.local.yml` as YAML (like `tests/unit/test_compose.py`); never `docker compose config`". Historical mentions (`docs/audit/04`, done card B1a) are fine as records. |
| S-2 | Low | Windows ACL on `C:\nexus-backups` | On drvfs `chmod 600` is ignored (unless `metadata` mount option); the folder inherits the C:\ root ACL, where by default *Authenticated Users* get Modify on subfolders. Any local Windows account can read, change or delete the unencrypted dumps. Single-user PC and dumps hold market analytics (no secrets) -> Low; user accepted "no encryption". | Add to the Russian guide one optional step: `icacls C:\nexus-backups /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"`. Keep "never put it under OneDrive". |
| S-3 | Low | Symlink/TOCTOU in copy dir | Temp name `.$name.partial` is fixed and `cp` follows a pre-existing symlink at that path, so a writer of the copy dir could redirect the write (the copy dir is writable by other Windows users, see S-2). | `rm -f -- "$tmp"` before `cp`, or `cp --remove-destination`, or `mktemp` in the dest dir. One-line fix. |
| S-4 | Low | Status dir mount guard | Nothing prevents `BACKUP_STATUS_DIR` = `BACKUP_DIR` (or a dir containing dumps): the status file would be chmod 0644 there and the dump dir mounted into the worker (still unreadable by uid 10001 at 0700/0600, so defence in depth only). Also compose interpolates `BACKUP_STATUS_DIR` from `.env` while `make up-local`/cron use the shell value -> possible mismatch and a root-owned dir. | In `write_status` refuse a status dir whose physical path equals BACKUP_DIR or contains `nexus-*.dump`; document "set BACKUP_STATUS_DIR only in the shell/crontab, not in `.env`". |
| S-5 | Info | No OneDrive guard | "Outside OneDrive" is a guide statement only; a custom `BACKUP_COPY_DIR` under `/mnt/c/Users/*/OneDrive*` would sync dumps to the cloud. | Optional: reject paths matching `*/OneDrive*` (case-insensitive) with a WARNING. |
| S-6 | Info | Redis integrity | Watchdog state sits in the unauthenticated broker Redis (A5b open): anything on the compose network could set `firing=true` and suppress alerts. Not reachable from the host (port unpublished). | Covered by A5b (auth); no S0 action. |
| S-7 | Info | Deny-list gaps (user-owned config, not S0) | Deny rules are prefix matches: variants like `docker compose --file docker-compose.local.yml config`, `docker compose -f ./docker-compose.local.yml config`, plain `env`, `docker exec` are not covered. | Orchestrator to raise with the user (settings change = user decision); agent prompts keep the explicit "never" list. |
| S-8 | Info | Availability (for tech-lead/devops) | The wrapper maps a clean SIGTERM exit to 0; with `on-failure` the scanner may not come back after a Docker/WSL restart (Windows update), only the watchdog alerts. Not a security issue. | Confirm behaviour on the first soak restart or note it in the guide. |

## Secrets check
No secret values in the reviewed diffs, texts, logs or tests. `.env` not read; no env-expanding command run.
