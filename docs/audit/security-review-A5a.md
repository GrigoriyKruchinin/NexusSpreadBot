# Security review: A5a backups + restore drill

- Date: 2026-10-23
- Reviewer: security (read-only on code and DBs)
- Scope: commits 5ccf1b6, 597b7d6: `scripts/_backup_common.sh`, `scripts/backup.sh`,
  `scripts/backup_prune.sh`, `scripts/restore_drill.sh`, `scripts/sql/bootstrap_backup_roles.sql`,
  Makefile targets, `.gitignore`, `.dockerignore`, `docs/guides/backups.md`,
  `docs/reports/restore-drill.md`, `tests/unit/scripts/test_backup_scripts.py`.
- Reference: `docs/architecture/target.md` §10.1, §10.5; card AC1-AC8.
- Checks run: `make lint` clean; `uv run pytest tests/unit/scripts -q` 10 passed (see note under
  S-A5a-1); offline guard probes and prune probes run in the session scratchpad on fake files only.
  shellcheck not installed. No psql/docker exec/backup/restore run. `.env` not read.
- Secrets scan of the diff: no passwords, tokens or ping URLs; no dump files tracked by git;
  `backups/`, `nexus-backups/`, `*.dump`, `*.dump.partial`, `*.age` are ignored in git and docker context.

## Verdict: RETURN

The main design is solid. There are no passwords at all: `pg_dump` runs as a passwordless `nexus_ro` over the
container unix socket. Dumps are written under `umask 077` with a `.partial` file and an atomic rename,
then 0600 is checked. The restore guard is an exact match and runs before any Docker call. The heartbeat URL
stays out of argv and logs. One blocking item remains (S-A5a-1, same as tech-lead R1-1). One medium item
(S-A5a-2) should be fixed in the same round because it can silently delete every backup.

## Restore-target guard: bypass attempts (all refused)

`restore_drill.sh:8-14` compares `TARGET_DB` to the literal `nexus_test` with `!=` in `[ ]`, quoted.
I tried these values and all were refused: `nexus`, `postgres`, `nexus_test2`, `Nexus_test`, `NEXUS_TEST`, `""`,
`" nexus_test"`, `"nexus_test "`, `postgresql:///nexus_test`, `dbname=nexus`. Because `-d` always gets
the literal string, libpq connection-string or URI parsing cannot apply. `docker compose exec` does not
forward host `PG*` variables, so `PGDATABASE`/`PGSERVICE`/`PGOPTIONS` on the host have no effect.
Remaining ways around the guard all need a deliberate env change and still never write to `nexus`:
- `TARGET_USER` is not pinned (S-A5a-3). Pointing it at a superuser removes the role-level defence in depth.
- `COMPOSE_FILE`, `DOCKER_HOST`, `DOCKER_CONTEXT` can point the drill at another cluster's
  `nexus_test` (Info).

## Findings

### S-A5a-1 (High, blocking): the unit test can dump the live DB and fire the real heartbeat
`tests/unit/scripts/test_backup_scripts.py:86-91` runs the real `backup.sh` with `PATH=/usr/bin:/bin`.
On this host `docker` exists at `/usr/bin/docker` and `/bin/docker`. With the stack up, every `make test`
therefore runs `docker compose exec postgres pg_dump -d nexus`. That writes a copy of live data into
`/tmp/pytest-of-*`, which pytest keeps (last 3 runs). `_run` (`:16-20`) also inherits `os.environ`, so a
`HEARTBEAT_URL`/`HEARTBEAT_URL_FILE` set in the shell sends a real ping and hides a genuinely missed backup.
This breaks the "unit tests: no DB" rule and the spirit of hard rules 3 and 5.
Note: this review ran the module once as permitted. pytest temp holds no dump from any run (the
`b/` dir is empty), so no live data was copied this session.
Fix: put a fake `docker` first on PATH for every test that runs a script. It should exit non-zero and
record that it was called. Build a minimal env in `_run` (`PATH`, `HOME`, the test vars) instead of
`{**os.environ, ...}`, and leave out `HEARTBEAT_URL*`, `COMPOSE_FILE`, `DOCKER_*` and `BACKUP_DIR`.

### S-A5a-2 (Medium): invalid retention values silently delete every dump
`backup_prune.sh:7-8,17,23`. `KEEP_DAILY`/`KEEP_WEEKLY` are not validated. A non-integer makes `[ -le ]`
fail with status 2. Inside `if` that counts as "false" and is not caught by `set -e`, so the file falls
through to `rm`. Probed on fake files (5 dumps), exit code 0 in every case:
`abc/abc` -> 0 left, `0/0` -> 0 left, `-1/0` -> 0 left, `3x/1` -> 1 left.
Because `backup.sh:26` prunes right after the new dump, even the dump just written gets deleted.
Fix: validate both values with `[[ $v =~ ^[0-9]+$ ]] && (( v >= 1 ))` or die. Never delete the newest
file. Add unit tests for invalid and zero values.

### S-A5a-3 (Low): `TARGET_USER` is overridable, so the role-level defence in depth is optional
`restore_drill.sh:9`. target.md §10.1 relies on `nexus_test_owner` as the second layer behind the name
guard. Setting `TARGET_USER=nexus` (the bootstrap superuser) makes `pg_restore --clean` and arbitrary
SQL from the dump run as superuser. A crafted dump passed as `$1` could then reach other DBs, for example
through extensions. Fix: pin `TARGET_USER` to `nexus_test_owner` (or refuse anything else), and check
`select rolsuper from pg_roles where rolname=current_user` = `f` before the restore.

### S-A5a-4 (Low): repo-path check can fail open; side effects happen before the check
`_backup_common.sh:5,19-25`. `REPO_ROOT` uses logical `pwd`, but the dir is resolved with `pwd -P`. If
the repo is reached through a symlinked path, the `case` never matches and a backup dir inside the repo is
accepted (it is gitignored only under the names `backups/` and `nexus-backups/`). In addition, `mkdir -p`
and `chmod 700` run before the location check, so a mistaken `BACKUP_DIR=$HOME` would chmod `$HOME` to 0700.
Fix: `REPO_ROOT=$(cd ... && pwd -P)`. Resolve the parent dir and check the location before `mkdir`/`chmod`.
Refuse to chmod a dir that already exists and is not 0700; die instead. Optionally check owner == `$(id -u)`.

### S-A5a-5 (Low): heartbeat URL handling
`backup.sh:31-37`.
(a) The file mode is not checked. The guide says 0600, so refuse or warn if the file is group- or world-readable.
(b) The URL is placed inside a double-quoted curl config string without escaping. A `"` or `\` in the
value would change the config. The source is the user's own file, so the risk is low. Fix: reject URLs
that do not match `^https://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+$`.
(c) `HEARTBEAT_URL` as a plain env var is fine for local Stage 1 only (§10.5). Prefer `_FILE`.

### S-A5a-6 (Info): bootstrap SQL least privilege is acceptable for Stage 1
`bootstrap_backup_roles.sql`: both roles are NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION, have no password,
and `nexus_ro` has SELECT only. On PG17, PUBLIC has no CREATE on `public`. `REVOKE CONNECT ... FROM PUBLIC`
on `nexus` (`:27`) is correct and verified in the drill report. Follow-ups for A5c:
- When `nexus_app`/`nexus_migrator` arrive, they need an explicit `GRANT CONNECT ON DATABASE nexus`. They also
  need `ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator ... TO nexus_ro`. `:37-38` only covers the current owner.
  Without it, pg_dump fails loudly (fail-safe).
- `default_transaction_read_only` (`:23`) is a session default the role can override. The real control is the grants.
- The "no TCP login" claim depends on the image's `host all all all scram-sha-256` line and on
  published-port traffic arriving from the bridge gateway, not container loopback. Devops should verify
  once that `psql -h 127.0.0.1 -U nexus_ro` from the host fails, and keep it that way when moving to a VPS
  (where §10.5 says no published port).

### S-A5a-7 (Info): `nexus_test` now holds a full copy of live data
After each drill, `nexus_test` contains live (public market and paper) data. Any role or test with access to
`nexus_test` can read it. This is acceptable at Stage 1 (no PII and no secrets in tables). Revisit if tables
ever hold account or key-derived data.

### S-A5a-8 (Info): pg_restore error output
On `--exit-on-error`, pg_restore prints the failing command. For custom-format COPY that is the
statement only, not the row data, so this is acceptable. Do not switch the dump to `--inserts`. If you do,
filter the "Command was:" lines.

## Acceptance criteria (security view)

| AC | Status |
|---|---|
| 1 nexus_ro, no secret in argv/logs/inspect | met |
| 2 outside repo, ignored, 0700/0600 | met, with hardening S-A5a-4 |
| 3 retention tested | met for happy path; S-A5a-2 open |
| 4 off-host encryption documented | met |
| 5 restore only into nexus_test | met; S-A5a-3 hardening |
| 6 heartbeat secret handling | code met (S-A5a-5 hardening); service/schedule not active (tech-lead R1-7) |
| 8 make check not worse | blocked by S-A5a-1 |

## Required to accept
S-A5a-1 and S-A5a-2 fixed with tests. S-A5a-3 and S-A5a-4 are recommended in the same round (cheap).
S-A5a-5 to S-A5a-8 can be carried to A5c/A5d.
