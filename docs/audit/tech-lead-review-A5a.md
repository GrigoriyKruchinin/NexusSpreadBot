# Tech-lead review: A5a backups + restore drill (round 1)

- Date: 2026-10-23
- Scope: commits 5ccf1b6, 597b7d6 (`scripts/_backup_common.sh`, `backup.sh`, `backup_prune.sh`,
  `restore_drill.sh`, `scripts/sql/bootstrap_backup_roles.sql`, Makefile, `.gitignore`,
  `.dockerignore`, `docs/guides/backups.md`, `docs/reports/restore-drill.md`,
  `tests/unit/scripts/test_backup_scripts.py`).
- Checks run: `uv run pytest tests/unit/scripts -q -k "not test_backup_dir_created_0700"` -> 9 passed;
  ruff + mypy --strict on the test module clean. **`make check` and the full scripts test module were
  NOT run on purpose**, see R1-1 (one test reaches the real Docker / live DB). shellcheck not installed.

## Verdict: RETURN (1 blocking point; the rest non-blocking)

The design is sound: dump over the container unix socket as a passwordless, read-only `nexus_ro`
(stronger than the `.pgpass` wording of AC1), atomic `.partial` -> rename, `pg_restore --list`
integrity check, 0700/0600 enforced, restore guard is exact-match and runs before any Docker call,
heartbeat URL kept out of argv and logs. The drill passed and is documented with counts only.

## Acceptance criteria

| AC | Status | Note |
|---|---|---|
| 1 nexus_ro, no secret in argv/logs/inspect | met | no password at all; trust only on the in-container socket |
| 2 dir outside repo, ignored, 0700/0600 | met (partial) | repo check yes; "outside any compose data volume" not checked by script (default `~/nexus-backups` is fine). See R1-6 |
| 3 retention 7+4, tested on temp dir | met with caveats | R1-2, R1-3 |
| 4 encryption for off-host copy documented | met | guide, `age`/`gpg` |
| 5 restore only into nexus_test, counts recorded | met | weak count check, R1-4 |
| 6 heartbeat, missed backup alerts | **not yet met** | code ready, service not configured and no schedule enabled; todo item ticked anyway, R1-7 |
| 7 Russian guide | met | inaccuracies R1-5 |
| 8 no destructive compose ops, make check | blocked by R1-1 | |

## Blocking

**R1-1. Unit test can dump the live DB and send a real heartbeat.**
`tests/unit/scripts/test_backup_scripts.py:86-91` (`test_backup_dir_created_0700`) runs the real
`scripts/backup.sh` with `PATH=/usr/bin:/bin`, assuming "no docker available". On this machine
`docker` is `/usr/bin/docker`. With the local stack up, every `make test`/`make check` therefore runs
`docker compose exec postgres pg_dump -d nexus` against the **live** DB, writes a dump to tmp, runs
prune, and, if `HEARTBEAT_URL`/`HEARTBEAT_URL_FILE` is in the environment (inherited via
`os.environ`), pings the heartbeat, which would mask a genuinely missed backup. Violates the
"unit tests: no DB" rule and hard rule 3/5 spirit. Fix: put a fake `docker` first on PATH (as the
restore test already does) that exits non-zero and records the call; drop `HEARTBEAT_URL*` from the
env passed to subprocesses (or build a minimal env instead of `{**os.environ, ...}`); assert the fake
was invoked only after the dir exists. Apply the same minimal-env rule to `_run` for all tests.

## Non-blocking (fix in this round if cheap, else carry to a follow-up)

**R1-2. "7 daily" counts files, not days.** `backup_prune.sh:15-19` keeps the 7 newest *files*.
Manual `make backup` runs, drills and the cron job on the same day push real daily coverage below
7 days (7 runs in one day = 1 day of history). Key dailies by `YYYYMMDD` (newest file per day for the
7 most recent days), like the weekly logic already does per ISO week. Add a test with several dumps
per day.

**R1-3. First weekly keeper can fall in the same ISO week as the oldest daily.** With dumps ending
Fri 2026-10-23, dailies are Oct 17-23 and the first "weekly" is Oct 16 (ISO week 42, already covered
by Oct 17/18). Effective history is ~26 days, not 7 days + 4 weeks. Either mark weeks touched by the
dailies as seen, or document the actual horizon in the guide. Test should assert the oldest kept date.

**R1-4. Restore count check is weak.** `restore_drill.sh:33` accepts any `0 < restored <= source`
(1 restored row of 11062 passes). Suggest: exact match required for tables with no rows newer than
the dump time, or a tolerance (e.g. restored >= 99 % of source), or capture source counts inside the
dump snapshot (`pg_dump --snapshot` / record counts in the same transaction). Also a table missing in
`nexus_test` aborts via `set -e` without the "drill FAILED" line; make it an explicit MISMATCH.

**R1-5. Guide inaccuracies (`docs/guides/backups.md`).**
- Line 36: says the result "is written" to `docs/reports/restore-drill.md`; the script only prints to
  stdout. Say that it must be copied manually (or have the script write a report outside the repo).
- Line 28: crontab line lacks `HEARTBEAT_URL_FILE=...`, so scheduled runs never ping. On WSL2 cron is
  not started automatically (`sudo service cron start` / systemd in wsl.conf); mention it. The
  `backup.log` grows without rotation.
- Line 11: retention wording should match the real behaviour after R1-2/R1-3.

**R1-6. `ensure_backup_dir` side effects before the guard** (`_backup_common.sh:18-27`): `mkdir -p`
and `chmod 700` run before the in-repo check, so a bad `BACKUP_DIR` creates a dir inside the repo
(the test then has to `rmdir` it, and leaves it behind if an assert fails) and `BACKUP_DIR=$HOME`
would chmod the home dir to 0700. Resolve the path and check first, then create. `REPO_ROOT` uses
`pwd` while the target uses `pwd -P`; use `-P` on both so a symlinked checkout is still caught.

**R1-7. AC6 open but todo ticked.** `todo.md:24` is `[x]` while the heartbeat service and the daily
schedule are not configured (STATE "in flight" item 2). Either untick / split into "A5a-ops: enable
schedule + heartbeat (user)" or set the card status to "DONE except AC6, pending user". Until a
schedule runs, "backups running" (soak precondition, todo:59) is not true.

**R1-8. Small robustness items.**
- `backup.sh:31`: `HEARTBEAT_URL_FILE` set but unreadable silently degrades to "not configured";
  log a WARNING instead. Optionally warn if the file mode is not 0600.
- `_backup_common.sh:31`: `latest_dump` uses the loose glob `nexus-*.dump`; a hand-named
  `nexus-manual.dump` sorts after digit names and would be restored as "latest". Use the strict
  pattern from `backup_prune.sh:11`.
- `backup_prune.sh:22`: a malformed date in a matching name aborts prune via `set -e` after the dump
  was written (backup exits non-zero, no heartbeat). Acceptable (loud), but log which file.
- Bootstrap SQL: default privileges are only for `current_user`; tables later created by A5c
  per-service roles will not be readable by `nexus_ro` and `pg_dump` will fail. Carry into A5c card.
- `test_bootstrap_sql_is_idempotent_and_has_no_secrets` is a text heuristic only; fine as a guard,
  do not count it as proof of idempotency.

## Tests quality
Prune tests exercise the real script on a temp dir (good) but miss multi-dump-per-day and the oldest
kept date. Restore-guard test is good: real script, fake docker marker, 5 bad targets incl. empty.
No positive-path guard test (`TARGET_DB=nexus_test` passes the guard and reaches the fake docker);
add one with the fake docker so a regression that refuses everything is caught.

## Required for round 2
R1-1 (blocking). Recommended in the same round: R1-2, R1-5 (first bullet), R1-6, R1-7.
