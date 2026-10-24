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
Pause the watchdog first if already installed: `touch ~/.nexus-watchdog-pause`.
```bash
cd /home/grisha/projects/NexusSpreadBot
git pull --ff-only            # branch chore/agent-pipeline-adoption
make up-local                 # = check-env-settings + docker compose up -d --build (rebuild + recreate changed services)
docker compose -f docker-compose.local.yml ps -a   # all Up (healthy), migrator Exited (0)
docker compose -f docker-compose.local.yml logs --tail 20 scanner   # 'paper_resumed', key policy pass
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
