# Handoff D-01b: auto-recovery after WSL/Windows restart + host dead-man (devops -> orchestrator)

## Root cause (confirmed by Docker Desktop logs, exit code 127 itself inferred)
Docker Desktop log `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`, 2026-10-24:
- 15:08:36Z engine shutdown after `wsl --shutdown`; 15:09:20Z distro agent for Ubuntu-22.04 failed ("setup groups").
- 15:09:30-35Z the WSL distro proxy restarted and only THEN logged `mounting /home/grisha/projects/NexusSpreadBot/config/nexus.toml
  to /mnt/wsl/docker-desktop-bind-mounts/Ubuntu-22.04/...` (same for `~/nexus-backup-status`).
- The engine had restarted the `unless-stopped` containers before that moment. Docker Desktop bind-mounts WSL-distro paths via
  its distro proxy, so the bind source was missing/unmounted at container start. postgres/redis (volumes only) were fine.
- Unconfirmed detail: why that surfaces as exit 127 with no app log (container events of that minute were no longer retrievable).
  Not needed for the fix: the design removes the dependency (bind mounts) and adds a recovery path that works for any cause.

## Changes
- `Dockerfile`: `COPY config/nexus.toml ./config/nexus.toml` in the runtime stage (startup secret guard unchanged).
- `docker-compose.local.yml`: bind mount of `nexus.toml` removed from the shared `x-image` and from `worker-maintenance`.
  The only remaining host bind mount is `~/nexus-backup-status:/backups:ro` on `worker-maintenance` (if it is not ready after a
  WSL restart, only that container fails; the host watchdog starts it).
  CONSEQUENCE: any `config/nexus.toml` change now needs `build` + recreate (README note, compose comment).
- `scripts/host_watchdog.sh` (cron */5, outside the stack): `docker compose start` for exited/created/dead services (never
  up/recreate/build/down/exec/inspect/config), Telegram alert after 2 bad runs (repeat 1 h, recovery message), "unhealthy" scanner
  = stale sweep heartbeat (its healthcheck is the Redis heartbeat), optional external heartbeat (`HEARTBEAT_URL_FILE`, same rules
  as backup.sh), pause file `~/.nexus-watchdog-pause`. Token read from `.env` inside the script at runtime, passed to curl via
  stdin config (not argv), never printed.
- Tests: `tests/unit/scripts/test_host_watchdog.py` (12), `tests/unit/test_compose.py` (bake/no-bind test replaces the mount test).
- Guide for the user (Russian): `docs/guides/soak-auto-recovery.md` (Docker Desktop autostart, Task Scheduler keep-alive of
  Ubuntu so cron backups run, crontab line, optional external heartbeat, how to repeat the check).

## Checks
`make check` green; 1122 unit tests, coverage 92 % (total line of `--cov`). shellcheck not installed (`bash -n` ok).
Not run: image build and live run of the script (soak running; CI `docker-build` covers the COPY).

## Deploy (orchestrator, after review + user OK; this recreates ALL app containers = a soak data gap of ~1-2 min)
Updated in round 2 (see below). Pause the watchdog first if already installed: `touch ~/.nexus-watchdog-pause`.
```bash
cd /home/grisha/projects/NexusSpreadBot
git pull --ff-only            # branch chore/agent-pipeline-adoption
git status --short config/ src/ Dockerfile   # MUST be empty: the build bakes the working-tree config/nexus.toml
mkdir -p ~/nexus-backup-status && ls ~/nexus-backup-status   # bind source must exist (create_host_path: false)
# BEFORE: note the paper run ids the scanner is using now
docker compose -f docker-compose.local.yml logs scanner 2>&1 | grep -E 'paper_resumed|paper_run' | tail -5
make up-local                 # = check-env-settings + docker compose up -d --build
docker compose -f docker-compose.local.yml ps -a   # all Up (healthy), migrator Exited (0)
# AFTER: the run ids must equal the BEFORE ids (same run resumed, no new run started)
docker compose -f docker-compose.local.yml logs --tail 50 scanner 2>&1 | grep -E 'paper_resumed|paper_run|key_policy'
docker compose -f docker-compose.local.yml exec worker-maintenance ls /backups   # last_backup.json visible
rm -f ~/.nexus-watchdog-pause
```
Narrower alternative (no scanner restart): not possible; the config mount change recreates every app service. Needs user OK
(soak data gap; same class as the retention deploy). The scanner paper runs resume (same run hash, config unchanged).

## User steps (Russian guide `docs/guides/soak-auto-recovery.md`)
1. Docker Desktop: start at sign-in. 2. Task Scheduler task `wsl.exe -d Ubuntu-22.04 --exec /usr/bin/sleep infinity` at logon.
3. `crontab -e`: add the `host_watchdog.sh` line. 4. Optional: healthchecks.io-style external heartbeat.

## Re-run the D-01 check
User runs `wsl --shutdown`, waits 3-5 min; then `docker compose -f docker-compose.local.yml ps -a`: scanner, beat, workers must be
Up by themselves (worker-maintenance may need the watchdog, up to ~10 min). Telegram "restarted ... now healthy" is acceptable.

## Pitfalls
- Watchdog restarts intentionally stopped containers unless paused (pause file).
- The watchdog cannot detect "PC off" (no cron): that needs the external heartbeat (NEEDS_USER).
- Redis/Postgres on `restart: unless-stopped` come back without help; `docker compose start` skips running ones.

## Round 2 fixes (tech-lead review 1 + security F-1..F-6)
| Point | Fix | Commit |
|---|---|---|
| TL 1 bind may start empty | long-syntax bind, `bind.create_host_path: false`; compose test checks it; guide D-01 step 3 checks `/backups` | 98f511a |
| TL 2 start timeout | `dc_start` uses `WATCHDOG_START_TIMEOUT_S` (240 s); test asserts the timeout args | 8a170ef |
| TL 3 deploy steps | `git status --short config/ src/ Dockerfile` empty; run ids compared before/after (commands above) | this docs commit |
| TL 4 two messages | `recovery_sent` suppresses "healthy again" after "restarted"; test | 8a170ef |
| TL 5 tests | failed recovery (no "restarted", fails=1) and lock-skipped run (exit 0, no docker calls) | 8a170ef |
| TL 6 parked scanner | guide: pause the watchdog while fixing keys | this docs commit |
| Sec F-1 | Telegram reminder when the pause file is older than 12 h (once per 12 h); tests | 8a170ef |
| Sec F-2 | `chmod 700` state dir / `600` log always; guide `mkdir -p -m 700` + chmod; test | 8a170ef + docs |
| Sec F-3 | log rotated to `.1` above 1 MiB (`WATCHDOG_LOG_FILE`, default state dir `watchdog.log`); test | 8a170ef |
| Sec F-6 | header note: never `bash -x`; script also runs `set +x` | 8a170ef |
| Sec F-4/F-5 | note only: `export KEY=` lines are ignored (fails closed, write `KEY=value`); chat_id/text in curl argv accepted (not credentials) | - |
